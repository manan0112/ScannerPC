"""
analysis/software_audit.py — Fleet-wide software analysis.

Identifies: outdated software, redundant tools, unlicensed risk, and cross-machine consistency.
"""
from collections import defaultdict


def _major_version(ver_str: str) -> int:
    try:
        return int(str(ver_str).split(".")[0])
    except (ValueError, AttributeError):
        return 0


# Minimum acceptable major version for common software
_MIN_VERSIONS = {
    "Google Chrome":              120,
    "Microsoft Edge":             120,
    "Mozilla Firefox":            120,
    "Adobe Acrobat":              24,
    "Microsoft Office":           2019,   # check by year in name
}

_RISKY_SOFTWARE = {
    "WinPcap":          "Network packet capture — remove from non-IT machines",
    "Wireshark":        "Network analyser — not needed on office PCs",
    "PuTTY":            "SSH client — review if needed",
    "Cain & Abel":      "SECURITY RISK: password cracker",
    "nmap":             "Network scanner — remove from non-IT machines",
}

_CONSUMER_SOFTWARE = {
    "Picasa":           "Discontinued Google photo app",
    "Steam":            "Gaming platform",
    "Discord":          "Gaming/social chat",
    "Spotify":          "Music streaming",
    "VLC":              "Media player — low priority",
    "WinRAR":           "Archiver — evaluate if still needed (7-Zip is free alternative)",
    "uTorrent":         "Torrent client — should not be on office machines",
    "BitTorrent":       "Torrent client — should not be on office machines",
}


def audit_machine(scan: dict) -> dict:
    hostname = scan.get("system_info", {}).get("hostname", "unknown")
    software = scan.get("software", [])
    flags    = []

    # Track remote access tools
    remote_tools = []

    for sw in software:
        name    = sw.get("name", "")
        version = sw.get("version", "")
        pub     = sw.get("publisher", "")

        # Outdated browser check
        for browser, min_ver in _MIN_VERSIONS.items():
            if browser in name:
                major = _major_version(version)
                if major and major < min_ver:
                    flags.append({
                        "severity": "high",
                        "software": name,
                        "version":  version,
                        "issue":    f"Version {version} is outdated (minimum {min_ver}) — security risk",
                        "action":   "Update immediately",
                    })

        # Remote access tool tracking
        if any(t in name for t in ("AnyDesk", "TeamViewer", "UltraViewer", "VNC", "RemotePC", "AmmyyAdmin")):
            remote_tools.append(name)

        # Risky software
        for kw, reason in _RISKY_SOFTWARE.items():
            if kw.lower() in name.lower():
                flags.append({
                    "severity": "high",
                    "software": name,
                    "version":  version,
                    "issue":    reason,
                    "action":   "Review and remove if not authorised",
                })

        # Consumer / non-work software
        for kw, reason in _CONSUMER_SOFTWARE.items():
            if kw.lower() in name.lower():
                flags.append({
                    "severity": "low",
                    "software": name,
                    "version":  version,
                    "issue":    reason,
                    "action":   "Remove from office PC",
                })

    # Multiple remote access tools
    if len(remote_tools) > 1:
        flags.append({
            "severity": "medium",
            "software": ", ".join(remote_tools),
            "version":  "",
            "issue":    f"{len(remote_tools)} remote access tools installed simultaneously",
            "action":   f"Keep only one — recommend uninstalling {', '.join(remote_tools[1:])}",
        })

    return {
        "hostname":       hostname,
        "software_count": len(software),
        "flags":          flags,
        "flag_counts": {
            "high":   sum(1 for f in flags if f["severity"] == "high"),
            "medium": sum(1 for f in flags if f["severity"] == "medium"),
            "low":    sum(1 for f in flags if f["severity"] == "low"),
        },
    }


def fleet_software_summary(scans: list[dict]) -> dict:
    """Cross-machine software analysis — finds fleet-wide patterns."""
    per_machine = [audit_machine(s) for s in scans]

    # Count how many machines have each piece of software
    software_counts: dict = defaultdict(int)
    for scan in scans:
        for sw in scan.get("software", []):
            name = sw.get("name", "").strip()
            if name:
                software_counts[name] += 1

    # Find software installed on most machines (standardisation opportunities)
    common = sorted(
        [(name, count) for name, count in software_counts.items() if count > 1],
        key=lambda x: x[1], reverse=True
    )[:30]

    # Find software only on one machine (outliers)
    outliers = [
        name for name, count in software_counts.items()
        if count == 1 and len(scans) > 3
    ]

    high_risk_machines = sorted(
        per_machine, key=lambda x: x["flag_counts"]["high"], reverse=True
    )[:5]

    return {
        "per_machine":            per_machine,
        "most_common_software":   [{"name": n, "machine_count": c} for n, c in common],
        "single_machine_outliers": outliers[:20],
        "highest_risk_machines":  high_risk_machines,
    }
