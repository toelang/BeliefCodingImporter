"""
Builds and renders a human-readable preview of the destination folder
structure the importer proposes to create - without touching Google
Drive at all. Used by main.py's default (plan) mode so the full proposed
structure can be reviewed and explicitly approved before anything is
created or uploaded.
"""

from datetime import datetime, timezone

import config
from logger import format_bytes

_FILES_KEY = "__files__"


def build_plan(db):
    """Turn the 'discovered' table into a nested tree plus summary stats.

    Returns (root_files, programmes, stats):
      - root_files: list of (name, size, status) tuples that will sit
        directly in the destination root (single-resource programmes and
        standalone linked files).
      - programmes: {programme_name: node} where each node is
        {"__files__": [...], subfolder_name: node, ...} - a plain nested
        dict mirroring the folders/files that will be created.
      - stats: summary counts for the report header.
    """
    root_files = []
    programmes = {}
    total_files = 0
    total_size = 0
    already_uploaded = 0
    duplicates = 0

    for row in db.iter_all_discovered():
        total_files += 1
        size = row["size"] or 0
        total_size += size
        status = row["status"]
        if status == "uploaded":
            already_uploaded += 1
        elif status == "duplicate":
            duplicates += 1

        entry = (row["name"], size, status)
        programme = row["programme"]

        if not programme:
            root_files.append(entry)
            continue

        node = programmes.setdefault(programme, {_FILES_KEY: []})
        subpath = row["dest_subpath"] or ""
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
        "duplicates": duplicates,
        "pending": total_files - already_uploaded - duplicates,
    }
    return root_files, programmes, stats


def _status_marker(status):
    return {
        "uploaded": " [already imported]",
        "duplicate": " [duplicate - will be skipped]",
        "inaccessible": " [inaccessible - will be skipped]",
        "error": " [previous error - will be retried]",
    }.get(status, "")


def _render_node(node, indent, lines):
    prefix = "    " * indent
    for name, size, status in sorted(node.get(_FILES_KEY, []), key=lambda e: e[0].lower()):
        lines.append(f"{prefix}{name}  ({format_bytes(size)}){_status_marker(status)}")
    for key in sorted((k for k in node.keys() if k != _FILES_KEY), key=str.lower):
        lines.append(f"{prefix}{key}/")
        _render_node(node[key], indent + 1, lines)


def render_plan_report(root_files, programmes, stats, db, destination_folder_name=None):
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
        f"  Already imported in a previous run: {stats['already_uploaded']}\n"
        f"  Detected as duplicates:             {stats['duplicates']}\n"
        f"  Still pending upload:               {stats['pending']}"
    )
    lines.append("")
    lines.append("NOTHING HAS BEEN UPLOADED OR CREATED IN GOOGLE DRIVE YET.")
    lines.append("Review the structure below. Re-run with --execute once you approve it.")
    lines.append("=" * 78)
    lines.append("")
    lines.append("(destination root)/")
    for name, size, status in sorted(root_files, key=lambda e: e[0].lower()):
        lines.append(f"    {name}  ({format_bytes(size)}){_status_marker(status)}")
    for programme_name in sorted(programmes.keys(), key=str.lower):
        lines.append(f"    {programme_name}/")
        _render_node(programmes[programme_name], indent=2, lines=lines)

    broken = list(db.iter_broken_links())
    if broken:
        lines.append("")
        lines.append("=" * 78)
        lines.append(f"BROKEN / INACCESSIBLE LINKS ({len(broken)})")
        lines.append("=" * 78)
        for row in broken:
            lines.append(f"  [{row['source_pdf']}] {row['url']}")
            lines.append(f"      reason: {row['reason']}")

    lines.append("")
    return "\n".join(lines)
