"""
config.py — Central configuration for the Windows Scanner Agent.
Adjust thresholds, scan paths, and output settings here.
"""

import os

# ── Output ────────────────────────────────────────────────────────────────────
OUTPUT_FILE = "scan_report.json"

# ── Large-file detection ──────────────────────────────────────────────────────
# Files equal to or larger than this size (bytes) are reported.
LARGE_FILE_THRESHOLD_BYTES = 100 * 1024 * 1024  # 100 MB

# Maximum number of large files to record (sorted largest-first).
LARGE_FILE_LIMIT = 50

# ── Folder-size scan ──────────────────────────────────────────────────────────
# Root directories whose immediate children will be sized recursively.
FOLDER_SCAN_ROOTS = [
    os.environ.get("USERPROFILE", "C:\\Users\\Default"),
    "C:\\Program Files",
    "C:\\Program Files (x86)",
]

# Maximum depth for recursive folder sizing (0 = only direct children).
FOLDER_MAX_DEPTH = 2

# ── Large-file / metadata scan paths ─────────────────────────────────────────
# Directories walked when hunting for large files.
FILE_SCAN_ROOTS = [
    os.environ.get("USERPROFILE", "C:\\Users\\Default"),
    "C:\\Program Files",
    "C:\\Program Files (x86)",
    "C:\\Windows\\Temp",
    os.environ.get("TEMP", "C:\\Temp"),
]

# Directory names to skip entirely during any walk.
SKIP_DIRS = {
    "$Recycle.Bin",
    "System Volume Information",
    "Recovery",
    ".git",
    "__pycache__",
}

# ── Software registry hives ───────────────────────────────────────────────────
# Each tuple: (hive_constant_name, sub_key)
# Resolved at runtime inside collectors/software.py to avoid importing
# winreg at config load time (keeps config importable on non-Windows for tests).
REGISTRY_PATHS = [
    ("HKEY_LOCAL_MACHINE",
     r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ("HKEY_LOCAL_MACHINE",
     r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    ("HKEY_CURRENT_USER",
     r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
]

# ── Metadata fields collected per large file ─────────────────────────────────
# Supported tokens: "size", "created", "modified", "accessed", "owner"
METADATA_FIELDS = ["size", "created", "modified", "accessed", "owner"]