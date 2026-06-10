"""
collectors/files.py — Walks configured paths and surfaces large files.
Returns a list sorted largest-first, capped at LARGE_FILE_LIMIT.
"""

import os
from config import (
    FILE_SCAN_ROOTS,
    SKIP_DIRS,
    LARGE_FILE_THRESHOLD_BYTES,
    LARGE_FILE_LIMIT,
)


def _walk(root: str):
    """
    Yield (filepath, size_bytes) for every regular file under *root*,
    skipping directories listed in SKIP_DIRS and inaccessible paths.
    Uses os.scandir for performance.
    """
    try:
        entries = list(os.scandir(root))
    except (PermissionError, OSError):
        return

    for entry in entries:
        try:
            if entry.is_symlink():
                continue
            if entry.is_file(follow_symlinks=False):
                try:
                    size = entry.stat().st_size
                    yield entry.path, size
                except OSError:
                    pass
            elif entry.is_dir(follow_symlinks=False):
                if entry.name not in SKIP_DIRS:
                    yield from _walk(entry.path)
        except OSError:
            continue


def collect() -> list:
    """
    Return up to LARGE_FILE_LIMIT files that meet or exceed
    LARGE_FILE_THRESHOLD_BYTES, sorted largest-first.
    """
    candidates: list = []
    seen_paths: set = set()

    for root in FILE_SCAN_ROOTS:
        root = os.path.normpath(root)
        if not os.path.isdir(root):
            continue
        for filepath, size in _walk(root):
            if size < LARGE_FILE_THRESHOLD_BYTES:
                continue
            norm = filepath.lower()
            if norm in seen_paths:
                continue
            seen_paths.add(norm)
            candidates.append({"path": filepath, "size_bytes": size})

    # Sort largest-first and cap.
    candidates.sort(key=lambda x: x["size_bytes"], reverse=True)
    return candidates[:LARGE_FILE_LIMIT]