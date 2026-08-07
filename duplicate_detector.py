"""
Duplicate detection.

Three checks are applied, in order, exactly as specified:

  1. Google Drive file ID  - has this exact source file already been
     imported in a previous (possibly interrupted) run?
  2. SHA-256 / MD5 hash    - does its content match a file we've already
     uploaded, even under a different name or source location? Drive
     reports checksums as file metadata, so this never requires
     downloading a file purely to hash it - the hash is only computed
     locally (in main.py, during the download that happens anyway for the
     upload) as a final safety net for native-Doc exports where Drive
     itself has no checksum to compare against.
  3. Filename + size        - last-resort fallback for files with no
     checksum available at all (e.g. native Google Docs).

A positive at any stage is treated as a duplicate and the file is never
uploaded again.
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import drive_uploader


@dataclass
class DuplicateMatch:
    reason: str
    existing_dest_path: str
    existing_source_id: str


def check_before_download(db, source_id, name, size, md5, sha256) -> Optional[DuplicateMatch]:
    """Cheap checks using only metadata already known before touching the
    network for content - call this first, for every discovered file."""

    # 1. Same Drive source already imported.
    existing = db.get_discovered(source_id)
    if existing and existing["status"] == "uploaded":
        return DuplicateMatch(
            reason=f"same source file already imported (Drive ID {source_id})",
            existing_dest_path=existing["dest_path"] or "",
            existing_source_id=source_id,
        )

    # 2. Checksum match against anything already uploaded.
    match = db.find_uploaded_by_checksum(sha256, md5)
    if match:
        return DuplicateMatch(
            reason=f"identical content already imported ({'sha256' if sha256 else 'md5'} match)",
            existing_dest_path=match["dest_path"] or "",
            existing_source_id=match["source_id"],
        )

    # 3. Filename + size fallback.
    if name and size is not None:
        match = db.find_uploaded_by_name_size(name, size)
        if match:
            return DuplicateMatch(
                reason="same filename and size already imported",
                existing_dest_path=match["dest_path"] or "",
                existing_source_id=match["source_id"],
            )

    return None


def check_against_live_destination(service, parent_id, name, size) -> Optional[DuplicateMatch]:
    """Defensive check straight against Drive itself, in case the local
    database was deleted/reset but the destination already has the file
    (e.g. from an even earlier, undocumented run)."""
    existing = drive_uploader.find_existing_in_destination(service, parent_id, name, size)
    if existing:
        return DuplicateMatch(
            reason="file with same name/size already present in destination folder",
            existing_dest_path=name,
            existing_source_id=existing.get("id", ""),
        )
    return None


def sha256_of_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Compute the SHA-256 of a local file in fixed-size chunks so large
    videos don't need to be loaded into memory."""
    hasher = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()
