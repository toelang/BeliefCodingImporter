"""
SQLite-backed state store for the importer.

Everything the importer needs to be resumable lives here: which source
files have been discovered, which have been uploaded (and where), which
destination folders already exist, and which links were broken or
inaccessible. Re-running main.py after an interruption re-crawls (cheap,
metadata-only) but only re-uploads files that are still pending.
"""

import sqlite3
from contextlib import closing
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


SCHEMA = """
CREATE TABLE IF NOT EXISTS discovered (
    source_id           TEXT PRIMARY KEY,
    source_kind         TEXT NOT NULL,          -- 'file' or 'folder' (folders only appear transiently)
    name                TEXT NOT NULL,
    mime_type           TEXT,
    size                INTEGER,
    md5                 TEXT,
    sha256              TEXT,
    programme           TEXT,                   -- destination programme folder name, or NULL for root-level
    dest_subpath        TEXT,                   -- '/' joined path segments under the programme folder (may be empty)
    status               TEXT NOT NULL DEFAULT 'pending',  -- pending | uploaded | duplicate | inaccessible | error
    dest_file_id        TEXT,
    dest_path           TEXT,                   -- human readable full destination path, filled in once uploaded
    reason              TEXT,                   -- extra detail for duplicate/inaccessible/error
    discovered_at       TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dest_folders (
    parent_id  TEXT NOT NULL,
    name       TEXT NOT NULL,
    dest_id    TEXT NOT NULL,
    PRIMARY KEY (parent_id, name)
);

CREATE TABLE IF NOT EXISTS broken_links (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_pdf  TEXT,
    url         TEXT,
    reason      TEXT,
    found_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS visited_nodes (
    node_id  TEXT PRIMARY KEY,
    seen_at  TEXT NOT NULL
);
"""


class Database:
    """Thin wrapper around sqlite3 exposing exactly the operations main.py needs."""

    def __init__(self, path):
        self._conn = sqlite3.connect(str(path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        with closing(self._conn.cursor()) as cur:
            cur.executescript(SCHEMA)
        self._conn.commit()

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    # -- discovery -----------------------------------------------------

    def add_discovered(self, source_id, source_kind, name, mime_type, size,
                        md5, sha256, programme, dest_subpath):
        """Insert a newly discovered source file, or refresh its computed
        programme/path/metadata if it's already known. Re-crawling always
        recomputes organisation (e.g. after a config/logic change), but
        never touches status/dest_file_id/dest_path/reason - a file's
        upload progress is only ever changed by the upload (or move)
        phase, never by discovery."""
        now = _now()
        self._conn.execute(
            """
            INSERT INTO discovered
                (source_id, source_kind, name, mime_type, size, md5, sha256,
                 programme, dest_subpath, status, discovered_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
            ON CONFLICT(source_id) DO UPDATE SET
                name = excluded.name,
                mime_type = excluded.mime_type,
                size = excluded.size,
                md5 = excluded.md5,
                sha256 = COALESCE(discovered.sha256, excluded.sha256),
                programme = excluded.programme,
                dest_subpath = excluded.dest_subpath,
                updated_at = excluded.updated_at
            """,
            (source_id, source_kind, name, mime_type, size, md5, sha256,
             programme, dest_subpath, now, now),
        )
        self._conn.commit()

    def get_discovered(self, source_id):
        cur = self._conn.execute("SELECT * FROM discovered WHERE source_id = ?", (source_id,))
        return cur.fetchone()

    def iter_pending(self):
        cur = self._conn.execute("SELECT * FROM discovered WHERE status = 'pending' ORDER BY rowid")
        for row in cur:
            yield row

    def iter_all_discovered(self):
        """Every discovered file, in a stable order suitable for building
        a human-readable tree (grouped by programme, then by sub-path)."""
        cur = self._conn.execute(
            "SELECT * FROM discovered "
            "ORDER BY COALESCE(programme, ''), dest_subpath, name COLLATE NOCASE"
        )
        for row in cur:
            yield row

    def iter_broken_links(self):
        cur = self._conn.execute(
            "SELECT * FROM broken_links ORDER BY source_pdf, url"
        )
        for row in cur:
            yield row

    def iter_uploaded_with_checksum(self):
        cur = self._conn.execute(
            "SELECT * FROM discovered WHERE status = 'uploaded' AND (sha256 IS NOT NULL OR md5 IS NOT NULL)"
        )
        for row in cur:
            yield row

    def find_uploaded_by_name_size(self, name, size):
        cur = self._conn.execute(
            "SELECT * FROM discovered WHERE status = 'uploaded' AND name = ? AND size = ?",
            (name, size),
        )
        return cur.fetchone()

    def find_uploaded_by_checksum(self, sha256, md5):
        if sha256:
            cur = self._conn.execute(
                "SELECT * FROM discovered WHERE status = 'uploaded' AND sha256 = ?", (sha256,)
            )
            row = cur.fetchone()
            if row:
                return row
        if md5:
            cur = self._conn.execute(
                "SELECT * FROM discovered WHERE status = 'uploaded' AND md5 = ?", (md5,)
            )
            row = cur.fetchone()
            if row:
                return row
        return None

    def update_status(self, source_id, status, dest_file_id=None, dest_path=None,
                       reason=None, sha256=None):
        now = _now()
        self._conn.execute(
            """
            UPDATE discovered
               SET status = ?,
                   dest_file_id = COALESCE(?, dest_file_id),
                   dest_path = COALESCE(?, dest_path),
                   reason = COALESCE(?, reason),
                   sha256 = COALESCE(?, sha256),
                   updated_at = ?
             WHERE source_id = ?
            """,
            (status, dest_file_id, dest_path, reason, sha256, now, source_id),
        )
        self._conn.commit()

    # -- destination folder cache ---------------------------------------

    def get_dest_folder(self, parent_id, name):
        cur = self._conn.execute(
            "SELECT dest_id FROM dest_folders WHERE parent_id = ? AND name = ?",
            (parent_id, name),
        )
        row = cur.fetchone()
        return row["dest_id"] if row else None

    def set_dest_folder(self, parent_id, name, dest_id):
        self._conn.execute(
            "INSERT OR REPLACE INTO dest_folders (parent_id, name, dest_id) VALUES (?, ?, ?)",
            (parent_id, name, dest_id),
        )
        self._conn.commit()

    # -- broken / inaccessible links --------------------------------------

    def record_broken_link(self, source_pdf, url, reason):
        self._conn.execute(
            "INSERT INTO broken_links (source_pdf, url, reason, found_at) VALUES (?, ?, ?, ?)",
            (source_pdf, url, reason, _now()),
        )
        self._conn.commit()

    # -- visited node loop protection -------------------------------------

    def mark_visited(self, node_id) -> bool:
        """Returns True if this is the first time node_id has been marked
        visited in this crawl, False if it was already visited."""
        try:
            self._conn.execute(
                "INSERT INTO visited_nodes (node_id, seen_at) VALUES (?, ?)",
                (node_id, _now()),
            )
            self._conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def clear_visited(self):
        """Call at the start of each run so folders are re-scanned for new
        content, while discovered/uploaded file state is preserved."""
        self._conn.execute("DELETE FROM visited_nodes")
        self._conn.commit()

    # -- counts for progress reporting ------------------------------------

    def counts(self):
        cur = self._conn.execute(
            "SELECT status, COUNT(*) AS n FROM discovered GROUP BY status"
        )
        result = {"pending": 0, "uploaded": 0, "duplicate": 0, "inaccessible": 0, "error": 0}
        for row in cur:
            result[row["status"]] = row["n"]
        return result
