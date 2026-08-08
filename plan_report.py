"""
Builds and renders a human-readable preview of the destination folder
structure the importer proposes to create - without touching Google
Drive at all. Used by main.py's default (plan) mode so the full proposed
structure can be reviewed and explicitly approved before anything is
created or uploaded.
"""

from datetime import datetime, timezone

import config
import duplicate_detector
from logger import format_bytes

_FILES_KEY = "__files__"


def compute_dest_path(programme, dest_subpath, name):
    """The exact '/'-joined destination path a file will have, relative
    to the destination root folder. Shared with main.py's upload phase so
    the plan and the real result can never disagree."""
    parts = ([programme] if programme else []) + (
        dest_subpath.split("/") if dest_subpath else []
    ) + [name]
    return "/".join(p for p in parts if p)


def _status_marker(status):
    return {
        "uploaded": " [already imported]",
        "will_move": " [already imported - will be moved here]",
        "duplicate": " [duplicate - was skipped]",
        "planned_duplicate": " [duplicate - will be skipped]",
        "inaccessible": " [inaccessible - previously failed]",
        "error": " [previous error - will be retried]",
    }.get(status, "")


def find_pending_moves(db):
    """Rows already uploaded in a past run whose freshly recomputed
    destination (after this run's crawl) no longer matches where the file
    actually is. Re-crawling always recomputes organisation, so this
    surfaces whenever grouping logic or config changes after some files
    were already imported. --execute performs these as a Drive-side move
    (metadata only) rather than a re-upload."""
    moves = []
    for row in db.iter_all_discovered():
        if row["status"] != "uploaded":
            continue
        new_path = compute_dest_path(row["programme"], row["dest_subpath"] or "", row["name"])
        if row["dest_path"] and new_path != row["dest_path"]:
            moves.append((row, new_path))
    return moves


def build_plan(db):
    """Turn the 'discovered' table into a nested tree plus summary stats.

    Returns (root_files, programmes, stats):
      - root_files: list of (name, size, status, reason, full_path) tuples
        that will sit directly in the destination root (single-resource
        programmes and standalone linked files).
      - programmes: {programme_name: node} where each node is
        {"__files__": [...], subfolder_name: node, ...} - a plain nested
        dict mirroring the folders/files that will be created.
      - stats: summary counts for the report header.
    """
    predictions = duplicate_detector.simulate_pending_duplicates(db)
    moves_by_source_id = {row["source_id"]: new_path for row, new_path in find_pending_moves(db)}

    root_files = []
    programmes = {}
    all_files = []  # flat list of (full_path, size, status, reason) for every file

    total_files = 0
    total_size = 0
    already_uploaded = 0
    duplicates = 0
    inaccessible = 0
    errors = 0
    will_move = 0

    for row in db.iter_all_discovered():
        total_files += 1
        size = row["size"] or 0
        total_size += size
        status = row["status"]
        reason = row["reason"] or ""

        if status == "pending":
            would_dup, dup_reason = predictions.get(row["source_id"], (False, None))
            if would_dup:
                status = "planned_duplicate"
                reason = dup_reason
        elif status == "uploaded" and row["source_id"] in moves_by_source_id:
            status = "will_move"
            reason = f"currently at: {row['dest_path']}"

        if status == "uploaded":
            already_uploaded += 1
        elif status == "will_move":
            will_move += 1
        elif status in ("duplicate", "planned_duplicate"):
            duplicates += 1
        elif status == "inaccessible":
            inaccessible += 1
        elif status == "error":
            errors += 1

        programme = row["programme"]
        subpath = row["dest_subpath"] or ""
        full_path = compute_dest_path(programme, subpath, row["name"])
        entry = (row["name"], size, status, reason)
        all_files.append((full_path, size, status, reason))

        if not programme:
            root_files.append(entry)
            continue

        node = programmes.setdefault(programme, {_FILES_KEY: []})
        current = node
        if subpath:
            for part in subpath.split("/"):
                current = current.setdefault(part, {_FILES_KEY: []})
        current[_FILES_KEY].append(entry)

    stats = {
        "total_files": total_files,
        "total_programmes": len(programmes),
        "root_level_files": len(root_files),
        "total_size": total_size,
        "already_uploaded": already_uploaded,
        "will_move": will_move,
        "duplicates": duplicates,
        "inaccessible": inaccessible,
        "errors": errors,
        "pending": total_files - already_uploaded - will_move - duplicates - inaccessible - errors,
    }
    return root_files, programmes, stats, all_files


def _render_node(node, indent, lines):
    prefix = "    " * indent
    for name, size, status, reason in sorted(node.get(_FILES_KEY, []), key=lambda e: e[0].lower()):
        lines.append(f"{prefix}{name}  ({format_bytes(size)}){_status_marker(status)}")
    for key in sorted((k for k in node.keys() if k != _FILES_KEY), key=str.lower):
        lines.append(f"{prefix}{key}/")
        _render_node(node[key], indent + 1, lines)


def render_plan_report(root_files, programmes, stats, db, destination_folder_name=None, all_files=None):
    lines = []
    lines.append("=" * 78)
    lines.append("BELIEF CODING RESOURCE IMPORTER - PROPOSED IMPORT PLAN")
    lines.append("=" * 78)
    lines.append(f"Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    lines.append("")
    dest_label = destination_folder_name or "(destination folder)"
    lines.append(f"Destination root: {dest_label}")
    lines.append(f"                  {config.DESTINATION_FOLDER_URL}")
    lines.append("No extra top-level folder is created above this - everything below")
    lines.append("is placed directly inside it.")
    lines.append("")
    lines.append(
        f"{stats['total_files']} file(s) discovered across {stats['total_programmes']} "
        f"programme folder(s) and {stats['root_level_files']} root-level item(s) "
        f"({format_bytes(stats['total_size'])} total)."
    )
    lines.append(
        f"  Will be uploaded:                   {stats['pending']}\n"
        f"  Already imported, staying put:      {stats['already_uploaded']}\n"
        f"  Already imported, will be moved:    {stats['will_move']}\n"
        f"  Duplicates (will be skipped):       {stats['duplicates']}\n"
        f"  Inaccessible:                       {stats['inaccessible']}\n"
        f"  Previous errors (will retry):       {stats['errors']}"
    )
    lines.append("")
    lines.append("NOTHING WILL BE UPLOADED, MOVED, OR CREATED IN GOOGLE DRIVE UNTIL YOU RUN --execute.")
    lines.append("Review the structure below. Re-run with --execute once you approve it.")
    lines.append("=" * 78)

    moves = find_pending_moves(db)
    if moves:
        lines.append("")
        lines.append("=" * 78)
        lines.append(f"ALREADY-IMPORTED FILES THAT WILL BE MOVED ({len(moves)})")
        lines.append("-" * 78)
        lines.append("These were uploaded by an earlier run before this grouping fix. They will")
        lines.append("be relocated in place (a metadata-only Drive move, not a re-upload) so")
        lines.append("they end up in the same corrected folders as everything else.")
        lines.append("")
        for row, new_path in sorted(moves, key=lambda m: m[1].lower()):
            lines.append(f"  {row['dest_path']}")
            lines.append(f"    -> {new_path}")
        lines.append("=" * 78)

    lines.append("")
    lines.append("FOLDER TREE")
    lines.append("-" * 78)
    lines.append("(destination root)/")
    for name, size, status, reason in sorted(root_files, key=lambda e: e[0].lower()):
        lines.append(f"    {name}  ({format_bytes(size)}){_status_marker(status)}")
    for programme_name in sorted(programmes.keys(), key=str.lower):
        lines.append(f"    {programme_name}/")
        _render_node(programmes[programme_name], indent=2, lines=lines)

    if all_files is not None:
        lines.append("")
        lines.append("=" * 78)
        lines.append(f"FULL FILE LIST - every file with its complete destination path ({len(all_files)})")
        lines.append("-" * 78)
        for full_path, size, status, reason in sorted(all_files, key=lambda e: e[0].lower()):
            reason_suffix = f"  -- {reason}" if reason and status in ("duplicate", "planned_duplicate", "inaccessible", "error") else ""
            lines.append(f"  {full_path}  ({format_bytes(size)}){_status_marker(status)}{reason_suffix}")

    broken = list(db.iter_broken_links())
    if broken:
        lines.append("")
        lines.append("=" * 78)
        lines.append(f"BROKEN / INACCESSIBLE LINKS ({len(broken)})")
        lines.append("-" * 78)
        for row in broken:
            lines.append(f"  [{row['source_pdf']}] {row['url']}")
            lines.append(f"      reason: {row['reason']}")

    lines.append("")
    return "\n".join(lines)
