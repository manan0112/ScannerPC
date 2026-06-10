"""
collectors/folders.py — Recursively sizes folders under configured scan roots.
Returns a list of folder records sorted largest-first.
"""

import os
from config import FOLDER_SCAN_ROOTS, FOLDER_MAX_DEPTH, SKIP_DIRS


def _dir_size(path: str, current_depth: int, max_depth: int) -> tuple:
    """
    Recursively compute total size of *path*.
    Returns (total_bytes, list_of_child_dicts) where children are only
    populated when current_depth < max_depth.
    """
    total = 0
    children = []

    try:
        entries = list(os.scandir(path))
    except PermissionError:
        return 0, []
    except OSError:
        return 0, []

    for entry in entries:
        try:
            if entry.is_symlink():
                continue
            if entry.is_file(follow_symlinks=False):
                try:
                    total += entry.stat().st_size
                except OSError:
                    pass
            elif entry.is_dir(follow_symlinks=False):
                if entry.name in SKIP_DIRS:
                    continue
                sub_size, sub_children = _dir_size(
                    entry.path, current_depth + 1, max_depth
                )
                total += sub_size
                if current_depth < max_depth:
                    child_rec = {
                        "path": entry.path,
                        "size_bytes": sub_size,
                    }
                    if sub_children:
                        child_rec["children"] = sub_children
                    children.append(child_rec)
        except OSError:
            continue

    children.sort(key=lambda x: x["size_bytes"], reverse=True)
    return total, children


def _scan_root(root: str) -> list:
    """Return sized records for all immediate children of *root*."""
    records = []
    if not os.path.isdir(root):
        return records

    try:
        entries = list(os.scandir(root))
    except (PermissionError, OSError):
        return records

    for entry in entries:
        try:
            if not entry.is_dir(follow_symlinks=False):
                continue
            if entry.name in SKIP_DIRS:
                continue
            size, children = _dir_size(entry.path, 0, FOLDER_MAX_DEPTH)
            rec = {
                "path": entry.path,
                "size_bytes": size,
            }
            if children:
                rec["children"] = children
            records.append(rec)
        except OSError:
            continue

    return records


def collect() -> list:
    """
    Scan every configured root and return all folder records,
    sorted largest-first by size_bytes.
    """
    all_records = []
    seen_paths: set = set()

    for root in FOLDER_SCAN_ROOTS:
        root = os.path.normpath(root)
        for rec in _scan_root(root):
            p = rec["path"].lower()
            if p not in seen_paths:
                seen_paths.add(p)
                all_records.append(rec)

    all_records.sort(key=lambda x: x["size_bytes"], reverse=True)
    return all_records