"""
Logging and progress reporting.

Two things live here:

- CsvLogger: appends one row per outcome (imported / skipped / duplicate /
  inaccessible / broken link) to import_log.csv, so there is always a
  durable record of what happened, independent of the console output.
- ProgressReporter: prints a single, continuously updating status line to
  the console with the live counters the spec asks for.
"""

import csv
import logging
import sys
import time
from pathlib import Path

import config

CSV_FIELDS = [
    "timestamp",
    "event",
    "name",
    "source_id",
    "programme",
    "dest_path",
    "size_bytes",
    "reason",
]


def setup_logging():
    """Configure a root logger: concise on the console, verbose in debug.log."""
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.handlers.clear()

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(console)

    file_handler = logging.FileHandler(config.DEBUG_LOG_FILE, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    )
    root.addHandler(file_handler)

    return logging.getLogger("belief_coding_importer")


class CsvLogger:
    """Appends rows to import_log.csv, creating the header if the file is new."""

    def __init__(self, path: Path = config.LOG_CSV_FILE):
        self.path = Path(path)
        is_new = not self.path.exists() or self.path.stat().st_size == 0
        self._fh = open(self.path, "a", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._fh, fieldnames=CSV_FIELDS)
        if is_new:
            self._writer.writeheader()
            self._fh.flush()

    def log(self, event, name="", source_id="", programme="", dest_path="",
            size_bytes="", reason=""):
        """event should be one of: imported, skipped, duplicate, inaccessible, broken_link"""
        self._writer.writerow({
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "event": event,
            "name": name,
            "source_id": source_id,
            "programme": programme,
            "dest_path": dest_path,
            "size_bytes": size_bytes,
            "reason": reason,
        })
        self._fh.flush()

    def close(self):
        self._fh.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


def _format_eta(seconds):
    if seconds is None or seconds < 0 or seconds != seconds:  # NaN check
        return "unknown"
    seconds = int(seconds)
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def _format_bytes(n):
    if not n:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


class ProgressReporter:
    """Tracks and prints live progress. Call the update_* methods as the
    importer works; call render() after each update."""

    def __init__(self):
        self.folders_scanned = 0
        self.files_discovered = 0
        self.files_uploaded = 0
        self.duplicates_skipped = 0
        self.inaccessible = 0
        self.errors = 0
        self.current_programme = "-"
        self.bytes_uploaded = 0
        self._start_time = time.time()
        self._upload_durations = []  # seconds per uploaded file, for ETA
        self._last_render_len = 0

    def folder_scanned(self):
        self.folders_scanned += 1

    def file_discovered(self):
        self.files_discovered += 1

    def set_current_programme(self, name):
        self.current_programme = name or "-"

    def file_uploaded(self, size_bytes, duration_seconds):
        self.files_uploaded += 1
        self.bytes_uploaded += size_bytes or 0
        if duration_seconds and duration_seconds > 0:
            self._upload_durations.append(duration_seconds)
            # keep a rolling window so ETA adapts to recent throughput
            if len(self._upload_durations) > 25:
                self._upload_durations.pop(0)

    def duplicate_skipped(self):
        self.duplicates_skipped += 1

    def marked_inaccessible(self):
        self.inaccessible += 1

    def marked_error(self):
        self.errors += 1

    def _eta_seconds(self, remaining_files):
        if not self._upload_durations or remaining_files <= 0:
            return None
        avg = sum(self._upload_durations) / len(self._upload_durations)
        return avg * remaining_files

    def render(self, remaining_files=0, final=False):
        eta = _format_eta(self._eta_seconds(remaining_files))
        line = (
            f"Folders scanned: {self.folders_scanned} | "
            f"Files discovered: {self.files_discovered} | "
            f"Uploaded: {self.files_uploaded} ({_format_bytes(self.bytes_uploaded)}) | "
            f"Duplicates skipped: {self.duplicates_skipped} | "
            f"Inaccessible/errors: {self.inaccessible + self.errors} | "
            f"Programme: {self.current_programme} | "
            f"ETA: {eta}"
        )
        pad = max(0, self._last_render_len - len(line))
        end = "\n" if final else ""
        sys.stdout.write("\r" + line + (" " * pad) + end)
        sys.stdout.flush()
        self._last_render_len = len(line)

    def summary(self):
        elapsed = time.time() - self._start_time
        return (
            "\n"
            "=== Import summary ===\n"
            f"Folders scanned:      {self.folders_scanned}\n"
            f"Files discovered:     {self.files_discovered}\n"
            f"Files uploaded:       {self.files_uploaded} ({_format_bytes(self.bytes_uploaded)})\n"
            f"Duplicates skipped:   {self.duplicates_skipped}\n"
            f"Inaccessible/errors:  {self.inaccessible + self.errors}\n"
            f"Elapsed time:         {_format_eta(elapsed)}\n"
        )
