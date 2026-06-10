"""
analysis/cleanup_plan.py — Per-machine cleanup recommendations with estimated space savings.
"""

_GB = 1024 ** 3
_MB = 1024 ** 2


def _fmt(b: int) -> str:
    if b >= _GB:
        return f"{b / _GB:.1f} GB"
    return f"{b / _MB:.0f} MB"


# Software known to be redundant, discontinued, or risky in an SME context
_REDUNDANT_PATTERNS = [
    # Multiple remote access tools — keep only one
    ("AnyDesk",       "remote_access", "Keep only one remote access tool"),
    ("TeamViewer",    "remote_access", "Keep only one remote access tool"),
    ("UltraViewer",   "remote_access", "Keep only one remote access tool"),
    # Discontinued
    ("Picasa",        "discontinued",  "Google discontinued Picasa in 2016"),
    # Gaming/consumer — no place on an office PC
    ("Steam",         "non_work",      "Gaming platform — not needed on office PC"),
    ("Xbox",          "non_work",      "Gaming app — not needed on office PC"),
    # Browser — flag if severely outdated
]

_OUTDATED_BROWSERS = {
    "Mozilla Firefox": 120,
    "Google Chrome":   100,
    "Microsoft Edge":  100,
}


def _software_cleanup(software: list) -> list:
    actions = []
    names_seen = {}

    # Track remote access tools — flag if more than one is present
    remote_tools = [s for s in software if any(
        kw in s.get("name", "") for kw in ("AnyDesk", "TeamViewer", "UltraViewer", "VNC", "RemotePC")
    )]
    if len(remote_tools) > 1:
        keep = remote_tools[0]["name"]
        for tool in remote_tools[1:]:
            actions.append({
                "action":   "uninstall",
                "software": tool["name"],
                "reason":   f"Duplicate remote access tool — keep only {keep}",
                "risk":     "low",
            })

    for sw in software:
        name    = sw.get("name", "")
        version = sw.get("version", "")

        # Discontinued software
        if "Picasa" in name:
            actions.append({"action": "uninstall", "software": name,
                             "reason": "Google Picasa discontinued 2016", "risk": "low"})

        # Severely outdated Firefox
        if "Mozilla Firefox" in name and version:
            try:
                major = int(version.split(".")[0])
                if major < 100:
                    actions.append({"action": "update_or_uninstall", "software": name,
                                    "reason": f"Version {version} is severely outdated — security risk",
                                    "risk": "high"})
            except (ValueError, IndexError):
                pass

        # Old Office 2016 — flag if newer licence available
        if "Microsoft Office Professional Plus 2016" in name:
            actions.append({"action": "review", "software": name,
                             "reason": "Office 2016 extended support ends Oct 2025 — plan upgrade to M365",
                             "risk": "medium"})

        # WinPcap on non-IT machines
        if "WinPcap" in name:
            actions.append({"action": "review", "software": name,
                             "reason": "Network packet capture tool — unusual on an accounts PC",
                             "risk": "medium"})

        # Old .NET runtimes — flag versions below 6
        if "Microsoft .NET Runtime - " in name:
            try:
                ver_major = int(version.split(".")[0])
                if ver_major < 6:
                    actions.append({"action": "uninstall", "software": name,
                                    "reason": f".NET {ver_major} is end-of-life",
                                    "risk": "low"})
            except (ValueError, IndexError):
                pass

    return actions


def _junk_actions(junk: dict) -> list:
    actions = []
    cats = junk.get("categories", {})

    for key, cat in cats.items():
        size = cat.get("size_bytes", 0) or sum(
            cat.get(k, 0) for k in ("size_bytes",)
        )
        # Flatten paths list if present
        if not size and "paths" in cat:
            size = cat.get("size_bytes", 0)
        if size > 50 * _MB and cat.get("safe_to_delete"):
            actions.append({
                "action":      "delete",
                "category":    key,
                "size_bytes":  size,
                "size_human":  _fmt(size),
                "path":        cat.get("path") or str(cat.get("paths", [])),
                "description": cat.get("description", ""),
                "risk":        "none",
            })

    actions.sort(key=lambda x: x["size_bytes"], reverse=True)
    return actions


def _onedrive_actions(user_folders: dict, onedrive: dict) -> list:
    actions = []
    od_installed = onedrive.get("client_installed", False)

    for folder_name, data in user_folders.items():
        if not data.get("exists"):
            continue
        size  = data.get("size_bytes", 0)
        types = data.get("by_type_bytes", {})
        ages  = data.get("by_age_bytes",  {})

        office_bytes = types.get("office_docs", 0) + types.get("tally_data", 0)
        video_bytes  = types.get("videos", 0)
        old_bytes    = ages.get("over_3_years", 0)

        if folder_name == "videos" and video_bytes > 500 * _MB:
            actions.append({
                "folder":     folder_name,
                "action":     "review_and_delete",
                "size_bytes": video_bytes,
                "size_human": _fmt(video_bytes),
                "reason":     "Videos unlikely to be work-related — review then delete",
            })

        if folder_name in ("documents", "desktop") and office_bytes > 100 * _MB:
            dest = "OneDrive" if od_installed else "Shared network folder"
            actions.append({
                "folder":     folder_name,
                "action":     "move_to_onedrive",
                "size_bytes": office_bytes,
                "size_human": _fmt(office_bytes),
                "reason":     f"Office/PDF files — move to {dest} for backup and sharing",
                "destination": dest,
            })

        if old_bytes > 200 * _MB:
            actions.append({
                "folder":     folder_name,
                "action":     "archive_or_delete",
                "size_bytes": old_bytes,
                "size_human": _fmt(old_bytes),
                "reason":     "Files not modified in 3+ years — archive to NAS or delete",
            })

    return actions


def build_plan(scan: dict) -> dict:
    hostname      = scan.get("system_info", {}).get("hostname", "unknown")
    junk          = scan.get("junk",         {})
    software      = scan.get("software",     [])
    user_folders  = scan.get("user_folders", {})
    onedrive      = scan.get("onedrive",     {})

    junk_acts     = _junk_actions(junk)
    sw_acts       = _software_cleanup(software)
    od_acts       = _onedrive_actions(user_folders, onedrive)

    immediate_savings = sum(a["size_bytes"] for a in junk_acts)

    return {
        "hostname":               hostname,
        "immediate_savings":      immediate_savings,
        "immediate_savings_human": _fmt(immediate_savings),
        "junk_cleanup":           junk_acts,
        "software_cleanup":       sw_acts,
        "onedrive_migration":     od_acts,
    }
