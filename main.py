"""
Belief Coding Resource Importer - entry point.

Usage:
    python main.py             Plan mode (default, safe): crawl Drive
                                read-only and print/save the exact
                                destination structure that WOULD be
                                created. Uploads or creates nothing.
    python main.py --execute   Actually create destination folders and
                                upload files, using the same crawl result.

What it does, in order:
  1. Authenticate with Google Drive (first run opens a browser; after that
     the cached token in token.json is reused automatically).
  2. Parse every PDF in config.PDF_FOLDER for Google Drive links.
  3. Crawl every link found (plus config.ADDITIONAL_DRIVE_FOLDERS)
     recursively, flattening marketing wrapper folders and working out
     where each file should land in the destination. This step never
     writes to Google Drive.
  4. In plan mode: print the proposed structure and save it to
     import_plan.txt, then stop - nothing is uploaded.
     In --execute mode: upload every newly discovered file that isn't a
     duplicate, creating destination folders as needed.
  5. Write import_log.csv and print a summary (execute mode only).

Safe to interrupt (Ctrl+C) and re-run at any time - already-uploaded
files are never re-uploaded, and the destination folder structure already
created is reused rather than duplicated. Re-running in plan mode after
an --execute run will show already-imported files marked accordingly.
"""

import argparse
import logging
import shutil
import sys
import time
import uuid

import config
import drive_crawler
import drive_uploader
import duplicate_detector
import pdf_parser
import plan_report
from database import Database
from drive_uploader import InaccessibleError
from logger import CsvLogger, ProgressReporter, setup_logging

log = logging.getLogger("belief_coding_importer.main")


def _validate_config():
    problems = []
    if not config.PDF_FOLDER.exists():
        problems.append(f"PDF folder not found: {config.PDF_FOLDER}")
    if not config.DESTINATION_FOLDER_URL:
        problems.append("config.DESTINATION_FOLDER_URL is empty")
    return problems


def _upload_one(service, db, csv_logger, progress, row):
    """Handle a single pending 'discovered' row: duplicate check, download,
    upload, record outcome. Never raises - all failure paths log and
    update the database so the row won't be retried forever on real errors
    without a trace of why."""
    source_id = row["source_id"]
    name = row["name"]
    size = row["size"]
    mime_type = row["mime_type"]
    programme = row["programme"]
    dest_subpath = row["dest_subpath"] or ""

    progress.set_current_programme(programme or "(destination root)")

    # --- duplicate check (metadata only, no download) ----------------
    dup = duplicate_detector.check_before_download(
        db, source_id, name, size, row["md5"], row["sha256"]
    )
    if dup:
        db.update_status(source_id, "duplicate", reason=dup.reason)
        csv_logger.log("duplicate", name=name, source_id=source_id, programme=programme or "",
                        reason=dup.reason, size_bytes=size or "")
        progress.duplicate_skipped()
        log.info("Duplicate, skipped: %s (%s)", name, dup.reason)
        return

    # --- work out / create the destination folder ----------------------
    try:
        root_id = drive_uploader.resolve_folder_id_from_url(config.DESTINATION_FOLDER_URL)
        path_segments = ([programme] if programme else []) + (
            dest_subpath.split("/") if dest_subpath else []
        )
        parent_id = drive_uploader.ensure_path(service, db, root_id, path_segments)
    except InaccessibleError as exc:
        db.update_status(source_id, "error", reason=f"destination folder error: {exc}")
        csv_logger.log("skipped", name=name, source_id=source_id, programme=programme or "",
                        reason=str(exc))
        progress.marked_error()
        log.error("Could not prepare destination for %s: %s", name, exc)
        return

    # --- defensive live check against the destination itself ------------
    live_dup = duplicate_detector.check_against_live_destination(service, parent_id, name, size)
    if live_dup:
        db.update_status(source_id, "duplicate", reason=live_dup.reason)
        csv_logger.log("duplicate", name=name, source_id=source_id, programme=programme or "",
                        reason=live_dup.reason, size_bytes=size or "")
        progress.duplicate_skipped()
        log.info("Duplicate (found already in destination), skipped: %s", name)
        return

    # --- download to a temp file, then upload ----------------------------
    config.TEMP_DIR.mkdir(parents=True, exist_ok=True)
    temp_path = config.TEMP_DIR / f"{uuid.uuid4().hex}_{_safe_filename(name)}"
    started = time.time()
    computed_sha256 = None
    try:
        native_export = config.GOOGLE_NATIVE_EXPORTS.get(mime_type)
        if native_export:
            drive_uploader.download_export(service, source_id, native_export["export_mime"], temp_path)
        else:
            drive_uploader.download_binary(service, source_id, temp_path)

        # If Drive never gave us a checksum (common for native Doc/Sheet/
        # Slide exports), compute one ourselves now for future dedup runs.
        if not row["sha256"] and not row["md5"]:
            computed_sha256 = duplicate_detector.sha256_of_file(temp_path)
            content_dup = db.find_uploaded_by_checksum(computed_sha256, None)
            if content_dup:
                db.update_status(source_id, "duplicate", reason="identical content (sha256, computed locally)")
                csv_logger.log("duplicate", name=name, source_id=source_id, programme=programme or "",
                                reason="identical content (sha256, computed locally)")
                progress.duplicate_skipped()
                log.info("Duplicate (content match after download), skipped: %s", name)
                return

        if native_export:
            uploaded = drive_uploader.upload_as_native(service, temp_path, name, parent_id, mime_type)
        else:
            uploaded = drive_uploader.upload_binary(service, temp_path, name, parent_id, mime_type)

    except InaccessibleError as exc:
        db.update_status(source_id, "inaccessible", reason=str(exc))
        csv_logger.log("inaccessible", name=name, source_id=source_id, programme=programme or "",
                        reason=str(exc))
        progress.marked_inaccessible()
        log.warning("Inaccessible, skipped: %s (%s)", name, exc)
        return
    except Exception as exc:
        db.update_status(source_id, "error", reason=str(exc))
        csv_logger.log("skipped", name=name, source_id=source_id, programme=programme or "",
                        reason=f"error: {exc}", size_bytes=size or "")
        progress.marked_error()
        log.exception("Failed to import %s", name)
        return
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)

    dest_path_str = plan_report.compute_dest_path(programme, dest_subpath, name)
    db.update_status(
        source_id, "uploaded",
        dest_file_id=uploaded.get("id"),
        dest_path=dest_path_str,
        sha256=uploaded.get("sha256Checksum") or computed_sha256,
    )
    csv_logger.log("imported", name=name, source_id=source_id, programme=programme or "",
                    dest_path=dest_path_str, size_bytes=size or "")
    duration = time.time() - started
    progress.file_uploaded(size or 0, duration)
    log.info("Uploaded: %s -> %s", name, dest_path_str)


def _safe_filename(name: str) -> str:
    return "".join(c for c in name if c.isalnum() or c in " ._-")[:150] or "file"


def _crawl_phase(service, db, progress):
    """Read the index PDFs and crawl Drive. Purely read-only against
    Google Drive - never creates a folder or uploads a file. Safe to run
    as often as you like, including just to preview the plan."""
    log.info("Reading index PDFs from %s ...", config.PDF_FOLDER)
    index_pdf_names = pdf_parser.index_pdf_filenames(config.PDF_FOLDER)
    pdf_links = pdf_parser.collect_all_links(config.PDF_FOLDER)
    log.info("Found %d unique Drive link(s) across %d PDF(s).", len(pdf_links), len(index_pdf_names))

    log.info("Crawling Google Drive (this can take a while for large folders)...")
    drive_crawler.crawl(
        service, db, progress,
        pdf_links=pdf_links,
        additional_folder_urls=config.ADDITIONAL_DRIVE_FOLDERS,
        index_pdf_names=index_pdf_names,
    )
    progress.render(final=True)
    log.info("Crawl complete. %d file(s) discovered so far.", progress.files_discovered)


def _show_plan(service, db):
    """Build and print/save the proposed destination structure. Makes no
    changes to Google Drive whatsoever - not even folder creation."""
    root_id = drive_uploader.resolve_folder_id_from_url(config.DESTINATION_FOLDER_URL)
    try:
        dest_meta = drive_uploader.get_file_metadata(service, root_id, fields="id, name")
        dest_name = dest_meta.get("name")
    except InaccessibleError as exc:
        log.error("Could not read the destination folder itself: %s", exc)
        dest_name = None

    root_files, programmes, stats, all_files = plan_report.build_plan(db)
    report = plan_report.render_plan_report(root_files, programmes, stats, db, dest_name, all_files)

    config.PLAN_REPORT_FILE.write_text(report, encoding="utf-8")
    print("\n" + report)
    log.info("Plan also written to %s", config.PLAN_REPORT_FILE.name)
    log.info(
        "Nothing has been uploaded or created in Google Drive. "
        "Review the plan above, then run 'python main.py --execute' to import it."
    )


def _upload_phase(service, db, csv_logger, progress):
    pending_rows = list(db.iter_pending())
    log.info("Uploading %d pending file(s)...", len(pending_rows))

    for i, row in enumerate(pending_rows):
        _upload_one(service, db, csv_logger, progress, row)
        remaining = len(pending_rows) - (i + 1)
        progress.render(remaining_files=remaining)

    progress.render(final=True)
    counts = db.counts()
    log.info(progress.summary())
    log.info("Status breakdown: %s", counts)
    log.info("Full detail written to %s", config.LOG_CSV_FILE.name)


def run(execute: bool):
    setup_logging()
    problems = _validate_config()
    if problems:
        for p in problems:
            log.error(p)
        sys.exit(1)

    log.info("Belief Coding Resource Importer")
    if not execute:
        log.info("Running in PLAN mode - Drive will be crawled (read-only) but nothing will be uploaded.")
    log.info("Authenticating with Google Drive...")
    service = drive_uploader.get_drive_service()

    db = Database(config.DATABASE_FILE)
    csv_logger = CsvLogger(config.LOG_CSV_FILE)
    progress = ProgressReporter()

    try:
        _crawl_phase(service, db, progress)

        if not execute:
            _show_plan(service, db)
            return

        _upload_phase(service, db, csv_logger, progress)

    except KeyboardInterrupt:
        log.warning("\nInterrupted by user. Progress has been saved - re-run main.py to resume.")
    finally:
        csv_logger.close()
        db.close()
        if config.TEMP_DIR.exists():
            shutil.rmtree(config.TEMP_DIR, ignore_errors=True)


def _parse_args():
    parser = argparse.ArgumentParser(
        description="Belief Coding Resource Importer. By default, only crawls Drive and "
                     "shows the proposed destination structure - nothing is uploaded."
    )
    parser.add_argument(
        "--execute", action="store_true",
        help="Actually create destination folders and upload files. Without this flag, "
             "the importer only crawls and prints/saves the proposed structure.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run(execute=args.execute)
