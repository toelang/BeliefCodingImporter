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
from pathlib import Path

import config
import drive_crawler
import drive_uploader
import duplicate_detector
import local_uploader
import pdf_parser
import plan_report
from database import Database
from drive_uploader import InaccessibleError
from local_uploader import LocalStorageError
from logger import CsvLogger, ProgressReporter, setup_logging

log = logging.getLogger("belief_coding_importer.main")

# InaccessibleError (Drive) and LocalStorageError (local disk) are both
# "this destination operation failed" - treated the same way everywhere
# below regardless of which mode is active.
_DESTINATION_ERRORS = (InaccessibleError, LocalStorageError)


def _validate_config():
    problems = []
    if not config.PDF_FOLDER.exists():
        problems.append(f"PDF folder not found: {config.PDF_FOLDER}")
    if config.DESTINATION_MODE not in ("drive", "local"):
        problems.append(f"config.DESTINATION_MODE must be 'drive' or 'local', not {config.DESTINATION_MODE!r}")
    elif config.DESTINATION_MODE == "drive" and not config.DESTINATION_FOLDER_URL:
        problems.append("config.DESTINATION_FOLDER_URL is empty")
    elif config.DESTINATION_MODE == "local" and not config.LOCAL_DESTINATION_FOLDER:
        problems.append("config.LOCAL_DESTINATION_FOLDER is empty")
    return problems


def _local_filename(name: str, native_export: dict) -> str:
    """A native Google Doc/Sheet/Slide has no file extension in its Drive
    name (Drive tracks its type via mimeType instead) - add the exported
    format's extension so it opens correctly as a plain file on disk."""
    if not native_export:
        return name
    ext = native_export["extension"]
    return name if name.lower().endswith(ext.lower()) else f"{name}{ext}"


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
        progress.duplicate_skipped(size)
        log.info("Duplicate, skipped: %s (%s)", name, dup.reason)
        return

    is_local = config.DESTINATION_MODE == "local"
    path_segments = ([programme] if programme else []) + (
        dest_subpath.split("/") if dest_subpath else []
    )

    # --- work out / create the destination folder ----------------------
    try:
        if is_local:
            dest_dir = local_uploader.ensure_path(config.LOCAL_DESTINATION_FOLDER, path_segments)
        else:
            root_id = drive_uploader.resolve_folder_id_from_url(config.DESTINATION_FOLDER_URL)
            parent_id = drive_uploader.ensure_path(service, db, root_id, path_segments)
    except _DESTINATION_ERRORS as exc:
        db.update_status(source_id, "error", reason=f"destination folder error: {exc}")
        csv_logger.log("skipped", name=name, source_id=source_id, programme=programme or "",
                        reason=str(exc))
        progress.marked_error(size)
        log.error("Could not prepare destination for %s: %s", name, exc)
        return

    # --- defensive live check against the destination itself ------------
    if is_local:
        already_there = local_uploader.find_existing(dest_dir, name, size)
    else:
        already_there = duplicate_detector.check_against_live_destination(service, parent_id, name, size)
    if already_there:
        reason = already_there.reason if hasattr(already_there, "reason") else \
            "file with same name/size already present in destination folder"
        db.update_status(source_id, "duplicate", reason=reason)
        csv_logger.log("duplicate", name=name, source_id=source_id, programme=programme or "",
                        reason=reason, size_bytes=size or "")
        progress.duplicate_skipped(size)
        log.info("Duplicate (found already in destination), skipped: %s", name)
        return

    # --- download to a temp file, then save/upload ----------------------
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
                progress.duplicate_skipped(size)
                log.info("Duplicate (content match after download), skipped: %s", name)
                return

        if is_local:
            final_path = local_uploader.place_file(temp_path, dest_dir, _local_filename(name, native_export))
            dest_identifier = str(final_path)
            result_sha256 = None
        elif native_export:
            uploaded = drive_uploader.upload_as_native(service, temp_path, name, parent_id, mime_type)
            dest_identifier = uploaded.get("id")
            result_sha256 = uploaded.get("sha256Checksum")
        else:
            uploaded = drive_uploader.upload_binary(service, temp_path, name, parent_id, mime_type)
            dest_identifier = uploaded.get("id")
            result_sha256 = uploaded.get("sha256Checksum")

    except _DESTINATION_ERRORS as exc:
        db.update_status(source_id, "inaccessible", reason=str(exc))
        csv_logger.log("inaccessible", name=name, source_id=source_id, programme=programme or "",
                        reason=str(exc))
        progress.marked_inaccessible(size)
        log.warning("Inaccessible, skipped: %s (%s)", name, exc)
        return
    except Exception as exc:
        db.update_status(source_id, "error", reason=str(exc))
        csv_logger.log("skipped", name=name, source_id=source_id, programme=programme or "",
                        reason=f"error: {exc}", size_bytes=size or "")
        progress.marked_error(size)
        log.exception("Failed to import %s", name)
        return
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)

    dest_path_str = plan_report.compute_dest_path(programme, dest_subpath, name)
    db.update_status(
        source_id, "uploaded",
        dest_file_id=dest_identifier,
        dest_path=dest_path_str,
        sha256=result_sha256 or computed_sha256,
    )
    csv_logger.log("imported", name=name, source_id=source_id, programme=programme or "",
                    dest_path=dest_path_str, size_bytes=size or "")
    duration = time.time() - started
    progress.file_uploaded(size or 0, duration)
    log.info("Saved: %s -> %s", name, dest_path_str)


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


def _destination_description(service):
    """Header lines for the plan report describing where files will land,
    and used to sanity-check the destination is reachable before --execute
    does any real work."""
    if config.DESTINATION_MODE == "local":
        folder = Path(config.LOCAL_DESTINATION_FOLDER)
        exists_note = "already exists" if folder.exists() else "will be created"
        return [
            f"Destination: local folder ({exists_note})",
            f"             {folder}",
            "If this folder is inside OneDrive/Dropbox/etc., that app uploads",
            "everything placed here to the cloud automatically.",
        ]

    root_id = drive_uploader.resolve_folder_id_from_url(config.DESTINATION_FOLDER_URL)
    try:
        dest_meta = drive_uploader.get_file_metadata(service, root_id, fields="id, name")
        dest_name = dest_meta.get("name") or "(destination folder)"
    except InaccessibleError as exc:
        log.error("Could not read the destination folder itself: %s", exc)
        dest_name = "(destination folder)"
    return [
        f"Destination root: {dest_name}",
        f"                  {config.DESTINATION_FOLDER_URL}",
    ]


def _show_plan(service, db):
    """Build and print/save the proposed destination structure. Makes no
    changes to Google Drive or the local destination - not even folder
    creation."""
    root_files, programmes, stats, all_files = plan_report.build_plan(db)
    report = plan_report.render_plan_report(
        root_files, programmes, stats, db, _destination_description(service), all_files
    )

    config.PLAN_REPORT_FILE.write_text(report, encoding="utf-8")
    print("\n" + report)
    log.info("Plan also written to %s", config.PLAN_REPORT_FILE.name)
    log.info(
        "Nothing has been saved, moved, or created at the destination. "
        "Review the plan above, then run 'python main.py --execute' to import it."
    )


def _move_phase(service, db, csv_logger, progress):
    """Relocate files an earlier run already placed, but whose correct
    programme folder has since changed (e.g. after a grouping-logic or
    config fix, or after switching DESTINATION_MODE). Never re-downloads
    or re-uploads a file - just relocates it at the destination."""
    moves = plan_report.find_pending_moves(db)
    if not moves:
        return

    is_local = config.DESTINATION_MODE == "local"
    log.info("Reorganising %d already-imported file(s) into their corrected folders...", len(moves))
    if not is_local:
        root_id = drive_uploader.resolve_folder_id_from_url(config.DESTINATION_FOLDER_URL)

    for row, new_path in moves:
        programme = row["programme"]
        dest_subpath = row["dest_subpath"] or ""
        old_path = row["dest_path"]
        try:
            path_segments = ([programme] if programme else []) + (
                dest_subpath.split("/") if dest_subpath else []
            )
            if is_local:
                new_dir = local_uploader.ensure_path(config.LOCAL_DESTINATION_FOLDER, path_segments)
                final_path = local_uploader.move_file(row["dest_file_id"], new_dir, row["name"])
                db.update_status(row["source_id"], "uploaded", dest_file_id=str(final_path), dest_path=new_path)
            else:
                parent_id = drive_uploader.ensure_path(service, db, root_id, path_segments)
                drive_uploader.move_file(service, row["dest_file_id"], parent_id)
                db.update_status(row["source_id"], "uploaded", dest_path=new_path)
            csv_logger.log("moved", name=row["name"], source_id=row["source_id"], programme=programme or "",
                            dest_path=new_path, reason=f"reorganised from: {old_path}")
            log.info("Moved: %s -> %s", old_path, new_path)
        except _DESTINATION_ERRORS as exc:
            log.warning("Could not move %s: %s", row["name"], exc)
        except Exception:
            log.exception("Unexpected error moving %s", row["name"])


def _upload_phase(service, db, csv_logger, progress):
    pending_rows = list(db.iter_pending())
    log.info("Uploading %d pending file(s)...", len(pending_rows))
    progress.set_total_pending_bytes(sum(row["size"] or 0 for row in pending_rows))

    for row in pending_rows:
        _upload_one(service, db, csv_logger, progress, row)
        progress.render()

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
        log.info("Running in PLAN mode - Drive will be crawled (read-only) but nothing will be saved anywhere.")
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

        _move_phase(service, db, csv_logger, progress)
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
