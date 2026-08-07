"""
Recursively crawls Google Drive links, flattens marketing/membership
wrapper folders, applies the "single resource -> no folder" rule, and
records every real file it finds into the database ready for upload.

How organisation is decided
----------------------------
Every link found in a PDF (or listed in config.ADDITIONAL_DRIVE_FOLDERS)
is a "root". Each root is resolved independently:

  * If the root is a single file, it goes straight into the destination
    root folder under its own name.
  * If the root is a folder whose name matches one of
    config.WRAPPER_FOLDER_NAMES, it is transparent: each of its own
    children is treated as an independent root in its own right (this
    also handles a wrapper nested inside another wrapper).
  * Otherwise the root folder is a "programme". Every file anywhere
    inside it (recursively) is collected, with wrapper sub-folders at any
    depth flattened the same way. If that comes to exactly one file, the
    programme folder is skipped and the file goes straight into the
    destination root. If there is more than one file, a single
    destination folder is created for the programme (its Drive name,
    optionally overridden via config.PROGRAMME_RENAMES) and the internal
    folder structure - minus any wrapper folders - is preserved beneath it.

Folders are only ever listed once per run (tracked via
Database.mark_visited) both to avoid infinite loops from shortcuts and to
avoid redundant work when the same folder is reachable from more than one
link. Individual files are de-duplicated later, at upload time, using
duplicate_detector.py.
"""

import logging

import config
import drive_uploader
from drive_uploader import InaccessibleError
from pdf_parser import parse_drive_url

log = logging.getLogger("belief_coding_importer.drive_crawler")

FOLDER_MIME = "application/vnd.google-apps.folder"
SHORTCUT_MIME = "application/vnd.google-apps.shortcut"

_RENAME_MAP = {k.lower(): v for k, v in config.PROGRAMME_RENAMES.items()}


def is_wrapper_folder(name: str) -> bool:
    lowered = (name or "").lower()
    return any(marker in lowered for marker in config.WRAPPER_FOLDER_NAMES)


def apply_rename(name: str) -> str:
    return _RENAME_MAP.get((name or "").lower(), name)


def _enter_folder(db, progress, folder_id) -> bool:
    """Marks folder_id as visited for this run. Returns False if it was
    already visited (caller should skip re-listing it)."""
    if not db.mark_visited(folder_id):
        return False
    progress.folder_scanned()
    return True


def _resolve_shortcut(service, meta, depth: int = 0):
    """Follow Drive shortcuts to their real target, with a depth guard
    against shortcut chains/loops. Returns None if the target is missing
    or inaccessible."""
    if depth > 5:
        log.warning("Shortcut chain too deep, giving up: %s", meta.get("name"))
        return None
    if meta.get("mimeType") != SHORTCUT_MIME:
        return meta
    target_id = (meta.get("shortcutDetails") or {}).get("targetId")
    if not target_id:
        return None
    try:
        target_meta = drive_uploader.get_file_metadata(service, target_id)
    except InaccessibleError:
        return None
    return _resolve_shortcut(service, target_meta, depth + 1)


def _emit(db, progress, meta, programme, dest_subpath):
    size = meta.get("size")
    size = int(size) if size not in (None, "") else None
    db.add_discovered(
        source_id=meta["id"],
        source_kind="file",
        name=meta["name"],
        mime_type=meta.get("mimeType"),
        size=size,
        md5=meta.get("md5Checksum"),
        sha256=meta.get("sha256Checksum"),
        programme=programme,
        dest_subpath=dest_subpath,
    )
    progress.file_discovered()
    log.debug("Discovered: %s (programme=%s, subpath=%s)", meta["name"], programme, dest_subpath)


def gather_subtree(service, folder_id, db, progress, path=()):
    """Recursively collect every (path_tuple, file_meta) beneath folder_id,
    with wrapper sub-folders flattened transparently at any depth."""
    if not _enter_folder(db, progress, folder_id):
        return []

    results = []
    for child in drive_uploader.list_children(service, folder_id):
        try:
            resolved = _resolve_shortcut(service, child)
            if resolved is None:
                log.warning("Skipping broken shortcut: %s", child.get("name"))
                continue

            name = resolved["name"]
            if resolved["mimeType"] == FOLDER_MIME:
                if is_wrapper_folder(name):
                    results.extend(gather_subtree(service, resolved["id"], db, progress, path))
                else:
                    results.extend(gather_subtree(service, resolved["id"], db, progress, path + (name,)))
            else:
                results.append((path, resolved))
        except Exception:
            log.exception("Error processing child '%s' under folder %s", child.get("name"), folder_id)
            progress.marked_error()

    return results


def process_root_from_metadata(service, db, progress, meta, index_pdf_names, source_label):
    resolved = _resolve_shortcut(service, meta)
    if resolved is None:
        db.record_broken_link(source_label, meta.get("id", "?"), "broken shortcut target")
        progress.marked_inaccessible()
        return

    if resolved.get("trashed"):
        db.record_broken_link(source_label, resolved.get("id", ""), "file/folder is in the trash")
        progress.marked_inaccessible()
        return

    if resolved["mimeType"] == FOLDER_MIME:
        name = resolved["name"]

        if is_wrapper_folder(name):
            if not _enter_folder(db, progress, resolved["id"]):
                return
            for child in drive_uploader.list_children(service, resolved["id"]):
                try:
                    process_root_from_metadata(service, db, progress, child, index_pdf_names, source_label)
                except Exception:
                    log.exception("Error processing wrapper child '%s'", child.get("name"))
                    progress.marked_error()
            return

        subtree = gather_subtree(service, resolved["id"], db, progress, path=())
        subtree = [(p, m) for (p, m) in subtree if m["name"].lower() not in index_pdf_names]

        if not subtree:
            log.debug("Nothing new to import under '%s' (empty, or already processed this run)", name)
            return

        if len(subtree) == 1:
            _, file_meta = subtree[0]
            _emit(db, progress, file_meta, programme=None, dest_subpath="")
        else:
            programme_name = apply_rename(name)
            progress.set_current_programme(programme_name)
            for path, file_meta in subtree:
                _emit(db, progress, file_meta, programme=programme_name, dest_subpath="/".join(path))

    else:
        if resolved["name"].lower() in index_pdf_names:
            log.info("Skipping index PDF also found on Drive: %s", resolved["name"])
            return
        _emit(db, progress, resolved, programme=None, dest_subpath="")


def process_root_from_url(service, db, progress, url, source_label, index_pdf_names):
    parsed = parse_drive_url(url)
    if not parsed:
        db.record_broken_link(source_label, url, "not a recognisable Google Drive link")
        return

    _, drive_id = parsed
    try:
        meta = drive_uploader.get_file_metadata(service, drive_id)
    except InaccessibleError as exc:
        log.warning("Inaccessible link from %s: %s (%s)", source_label, url, exc)
        db.record_broken_link(source_label, url, str(exc))
        progress.marked_inaccessible()
        return
    except Exception as exc:
        log.exception("Unexpected error resolving %s", url)
        db.record_broken_link(source_label, url, f"unexpected error: {exc}")
        progress.marked_error()
        return

    process_root_from_metadata(service, db, progress, meta, index_pdf_names, source_label)


def crawl(service, db, progress, pdf_links, additional_folder_urls, index_pdf_names):
    """Entry point used by main.py. pdf_links is a list of pdf_parser.DriveLink;
    additional_folder_urls is config.ADDITIONAL_DRIVE_FOLDERS (or similar)."""
    db.clear_visited()

    for link in pdf_links:
        process_root_from_url(service, db, progress, link.url, link.source_pdf, index_pdf_names)

    for url in additional_folder_urls:
        process_root_from_url(service, db, progress, url, "config.py", index_pdf_names)
