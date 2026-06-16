"""
collectors/software.py — Reads installed software from the Windows registry.
Covers 64-bit, 32-bit (WOW6432Node), and per-user Uninstall keys.
Returns a deduplicated, sorted list of dicts.
"""

import winreg
from config import REGISTRY_PATHS

# Registry value names we want to capture per entry.
_FIELDS = [
    "DisplayName",
    "DisplayVersion",
    "Publisher",
    "InstallDate",
    "InstallLocation",
    "EstimatedSize",   # KB
    "UninstallString",
]

_HIVE_MAP = {
    "HKEY_LOCAL_MACHINE": winreg.HKEY_LOCAL_MACHINE,
    "HKEY_CURRENT_USER":  winreg.HKEY_CURRENT_USER,
}


def _read_subkey(hive_handle, subkey_path: str) -> list:
    """Open a single Uninstall subkey and return a list of software dicts."""
    results = []
    try:
        root = winreg.OpenKey(hive_handle, subkey_path,
                              access=winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
    except OSError:
        return results

    idx = 0
    while True:
        try:
            child_name = winreg.EnumKey(root, idx)
        except OSError:
            break
        idx += 1

        try:
            child = winreg.OpenKey(root, child_name)
        except OSError:
            continue

        entry = {"_key": child_name}
        for field in _FIELDS:
            try:
                val, _ = winreg.QueryValueEx(child, field)
                entry[field] = val
            except OSError:
                pass
        winreg.CloseKey(child)

        # Skip entries with no display name (system components / patches).
        if "DisplayName" not in entry:
            continue

        results.append(entry)

    winreg.CloseKey(root)
    return results


def _normalise(entry: dict) -> dict:
    """Return a clean, consistently-keyed dict for JSON output."""
    # Registry values can be DWORD (int) instead of REG_SZ — coerce to str defensively.
    def _s(key: str) -> str:
        v = entry.get(key)
        return str(v).strip() if v is not None else ""

    size_kb = entry.get("EstimatedSize")
    return {
        "name":             _s("DisplayName"),
        "version":          _s("DisplayVersion"),
        "publisher":        _s("Publisher"),
        "install_date":     _s("InstallDate"),
        "install_location": _s("InstallLocation"),
        "size_kb":          int(size_kb) if size_kb is not None else None,
        "uninstall_string": _s("UninstallString"),
    }


def collect() -> list:
    """Return deduplicated list of installed software, sorted by name."""
    seen: set = set()
    software: list = []

    for hive_name, subkey in REGISTRY_PATHS:
        hive = _HIVE_MAP.get(hive_name)
        if hive is None:
            continue
        for entry in _read_subkey(hive, subkey):
            norm = _normalise(entry)
            key = (norm["name"].lower(), norm["version"].lower())
            if key in seen or not norm["name"]:
                continue
            seen.add(key)
            software.append(norm)

    software.sort(key=lambda x: x["name"].lower())
    return software