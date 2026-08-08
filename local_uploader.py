"""
Local-filesystem destination backend.

Used when config.DESTINATION_MODE is "local" instead of "drive": every
file still gets discovered from Google Drive, downloaded, and organised
by programme exactly as before - the only thing that changes is the very
last step, which saves the file into a folder on this PC instead of
uploading it to a Google Drive folder.

Pointing config.LOCAL_DESTINATION_FOLDER at a folder inside your OneDrive
(or Dropbox, etc.) means that app's own desktop client uploads everything
placed here to the cloud automatically - no second cloud API integration
needed.
"""

import logging
import shutil
from pathlib import Path

log = logging.getLogger("belief_coding_importer.local_uploader")

# Characters Windows won't allow in a file/folder name.
_ILLEGAL_CHARS = '<>:"/\\|?*'


class LocalStorageError(Exception):
    """Raised when a local file operation fails in a way that isn't just
    'this one file has a problem' - e.g. disk full, permission denied."""


def safe_component(name: str) -> str:
    """Make a single path component (one folder or file name) safe for
    Windows, without mangling it beyond recognition."""
    cleaned = "".join("_" if c in _ILLEGAL_CHARS else c for c in name)
    cleaned = cleaned.rstrip(" .")
    return cleaned or "_"


def ensure_path(root_path: Path, path_segments) -> Path:
    """Get-or-create a nested folder path under root_path. Unlike Drive,
    creating a local folder that already exists is a cheap no-op, so no
    caching/lookup is needed."""
    current = Path(root_path)
    for segment in path_segments:
        if segment:
            current = current / safe_component(segment)
    try:
        current.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise LocalStorageError(_explain_os_error(exc, current)) from exc
    return current


def find_existing(dest_dir: Path, name: str, size) -> bool:
    """True if a file with this name (and, if known, this size) already
    sits at the destination - covers files you'd already placed there
    yourself before running the importer."""
    candidate = Path(dest_dir) / safe_component(name)
    if not candidate.exists():
        return False
    if size is None:
        return True
    try:
        return candidate.stat().st_size == int(size)
    except (OSError, ValueError):
        return True


def place_file(temp_path: Path, dest_dir: Path, name: str) -> Path:
    """Move a downloaded temp file into its final destination folder."""
    dest_dir = Path(dest_dir)
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        final_path = dest_dir / safe_component(name)
        shutil.move(str(temp_path), str(final_path))
        return final_path
    except OSError as exc:
        raise LocalStorageError(_explain_os_error(exc, dest_dir / name)) from exc


def move_file(current_path: Path, new_dir: Path, name: str) -> Path:
    """Relocate an already-placed file to a different destination folder
    (used when re-crawling recomputes a different, corrected programme)."""
    new_dir = Path(new_dir)
    new_dir.mkdir(parents=True, exist_ok=True)
    new_path = new_dir / safe_component(name)
    current_path = Path(current_path)
    try:
        if current_path.resolve() != new_path.resolve() and current_path.exists():
            shutil.move(str(current_path), str(new_path))
        return new_path
    except OSError as exc:
        raise LocalStorageError(_explain_os_error(exc, new_path)) from exc


def _explain_os_error(exc: OSError, path: Path) -> str:
    path_str = str(path)
    if len(path_str) > 240:
        return (
            f"path too long for Windows ({len(path_str)} characters): {path_str} - "
            "enable long path support (Windows Settings > search 'Enable Win32 long paths') "
            "or shorten LOCAL_DESTINATION_FOLDER in config.py"
        )
    if getattr(exc, "errno", None) == 28 or "No space left" in str(exc):
        return f"no space left on disk while writing {path_str}"
    return f"could not write {path_str}: {exc}"
