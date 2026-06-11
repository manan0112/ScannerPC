"""
analysis/hardware_score.py — Scores each scanned machine and produces an upgrade priority list.

Score starts at 100; deductions are applied for RAM, OS age, disk fullness, and CPU generation.
The lower the score, the more urgent the upgrade need.
"""
import re

# Regex to extract Intel CPU generation from processor name string
_GEN_RE = re.compile(r"(\d+)(?:st|nd|rd|th)\s+Gen", re.IGNORECASE)
_CORE_RE = re.compile(r"i[357]-(\d{4,5})", re.IGNORECASE)


def _cpu_generation(cpu_name: str) -> int:
    """Estimate Intel CPU generation from name string. Returns 0 if unknown."""
    m = _GEN_RE.search(cpu_name)
    if m:
        return int(m.group(1))
    # Fallback: infer from model number (e.g. i5-2400 → gen 2, i5-10400 → gen 10)
    m = _CORE_RE.search(cpu_name)
    if m:
        model = int(m.group(1))
        if model < 3000:
            return 2
        if model < 4000:
            return 3
        if model < 5000:
            return 4
        if model < 6000:
            return 5
        if model < 7000:
            return 6
        if model < 8000:
            return 7
        if model < 10000:
            return 8
        return int(str(model)[:2])  # e.g. 10400 → 10
    return 0


def _c_drive(scan: dict) -> dict:
    for d in scan.get("system_info", {}).get("disks", []):
        if d.get("drive", "").upper().startswith("C"):
            return d
    return {}


def score_machine(scan: dict) -> dict:
    """Return a scoring dict with numeric score (0-100), issues list, and priority label."""
    score   = 100
    issues  = []
    actions = []

    si  = scan.get("system_info", {})
    os_ = si.get("os", {})
    cpu = si.get("cpu", {})
    mem = si.get("memory", {})

    # ── OS ────────────────────────────────────────────────────────────────────
    release = str(os_.get("release", ""))
    if release == "7":
        score  -= 40
        issues.append("CRITICAL: Windows 7 — end of support since Jan 2020, security risk")
        actions.append("Upgrade OS to Windows 10/11 immediately")
    elif release in ("8", "8.1"):
        score  -= 25
        issues.append("HIGH: Windows 8/8.1 — end of support Jan 2023")
        actions.append("Upgrade OS to Windows 10/11")
    elif release == "10":
        score  -= 3
    elif release == "11":
        score += 5  # bonus

    # ── RAM ───────────────────────────────────────────────────────────────────
    ram_gb   = mem.get("total_bytes", 0) / (1024 ** 3)
    ram_load = mem.get("load_percent", 0)
    if ram_gb < 4.5:
        score  -= 30
        issues.append(f"CRITICAL: {ram_gb:.0f} GB RAM — insufficient for modern Windows")
        actions.append("Upgrade RAM to minimum 8 GB")
    elif ram_gb < 8.5 and ram_load > 80:
        score  -= 20
        issues.append(f"HIGH: {ram_gb:.0f} GB RAM at {ram_load}% load — constantly swapping")
        actions.append("Upgrade RAM to 16 GB or reduce startup programs")
    elif ram_gb < 8.5:
        score  -= 8
        issues.append(f"MEDIUM: {ram_gb:.0f} GB RAM — marginal for multi-tasking")
    elif ram_load > 85:
        score  -= 10
        issues.append(f"MEDIUM: RAM at {ram_load}% — reduce startup programs")
        actions.append("Audit and disable unnecessary startup programs")

    # ── CPU generation ────────────────────────────────────────────────────────
    gen = _cpu_generation(cpu.get("name", ""))
    if 0 < gen <= 2:
        score  -= 20
        issues.append(f"HIGH: CPU is {gen}nd Gen Intel — very old, bottlenecks everything")
        actions.append("Replace PC (CPU cannot be upgraded in most systems)")
    elif gen in (3, 4):
        score  -= 12
        issues.append(f"MEDIUM: CPU is {gen}th Gen Intel — aging hardware")
    elif gen in (5, 6):
        score  -= 6
        issues.append(f"LOW: CPU is {gen}th Gen Intel — adequate but aging")
    elif gen == 0 and "DC CPU" in cpu.get("name", ""):
        score  -= 25
        issues.append("HIGH: Unidentified dual-core CPU — likely very old")

    # ── Disk free space ───────────────────────────────────────────────────────
    c = _c_drive(scan)
    if c:
        total  = c.get("total_bytes", 1)
        free   = c.get("free_bytes", total)
        free_p = (free / total) * 100
        if free_p < 8:
            score  -= 20
            issues.append(f"CRITICAL: C: drive only {free_p:.0f}% free ({free//(1024**3)} GB) — system unstable")
            actions.append("Urgent disk cleanup — run junk collector recommendations")
        elif free_p < 15:
            score  -= 10
            issues.append(f"HIGH: C: drive {free_p:.0f}% free — performance degraded")
            actions.append("Disk cleanup needed before further use")
        elif free_p < 25:
            score  -= 4
            issues.append(f"MEDIUM: C: drive {free_p:.0f}% free — getting low")

    # ── Uptime ────────────────────────────────────────────────────────────────
    uptime_days = si.get("uptime_seconds", 0) / 86400
    if uptime_days > 30:
        score -= 5
        issues.append(f"INFO: Machine has not been rebooted in {uptime_days:.0f} days")
        actions.append("Reboot machine — clears RAM and applies pending updates")

    # ── Security ─────────────────────────────────────────────────────────────
    sec = scan.get("security", {})
    if sec.get("pending_reboot"):
        issues.append("INFO: Reboot pending for Windows updates")
        actions.append("Reboot to complete pending Windows updates")
    if not sec.get("antivirus_products"):
        score -= 5
        issues.append("MEDIUM: No AV product detected in SecurityCenter2")

    # ── Disk health ───────────────────────────────────────────────────────────
    dh = scan.get("disk_health", {})
    if dh.get("any_failure_predicted"):
        score -= 35
        for w in dh.get("warnings", []):
            issues.append(f"CRITICAL: Disk health — {w}")
        actions.append("Back up immediately and replace the failing disk")
    else:
        # No SSD detected → an HDD-only machine feels slow regardless of CPU/RAM
        media = {d.get("media_type", "") for d in dh.get("physical_disks", [])}
        if media and "SSD" not in media and any("HDD" in m or "hard" in m.lower() for m in media):
            score -= 10
            issues.append("MEDIUM: No SSD detected — HDD-only system, slow boot and load times")
            actions.append("Install SSD as boot drive — single biggest speed upgrade available")

    # ── Startup bloat ─────────────────────────────────────────────────────────
    startup_count = len(scan.get("startup", []))
    if startup_count > 15:
        score -= 8
        issues.append(f"HIGH: {startup_count} auto-start entries — slows boot significantly")
        actions.append("Audit startup entries; disable non-essential ones")
    elif startup_count > 8:
        score -= 3
        issues.append(f"MEDIUM: {startup_count} auto-start entries")

    score = max(0, min(100, score))

    if score < 30:
        priority = "REPLACE"
        label    = "Replace within 1 month"
    elif score < 50:
        priority = "UPGRADE_URGENT"
        label    = "Upgrade within 3 months"
    elif score < 65:
        priority = "UPGRADE_PLANNED"
        label    = "Upgrade within 6 months"
    elif score < 80:
        priority = "MAINTAIN"
        label    = "Cleanup + maintenance only"
    else:
        priority = "HEALTHY"
        label    = "Healthy — no hardware action needed"

    return {
        "score":    score,
        "priority": priority,
        "label":    label,
        "issues":   issues,
        "actions":  actions,
        "ram_gb":   round(ram_gb, 1),
        "ram_load": ram_load,
        "cpu_gen":  gen,
        "os":       f"Windows {release}",
        "uptime_days": round(uptime_days, 1),
    }


def rank_fleet(scans: list[dict]) -> list[dict]:
    """Score all machines and return sorted list (worst first)."""
    ranked = []
    for s in scans:
        hostname = s.get("system_info", {}).get("hostname", "unknown")
        result   = score_machine(s)
        result["hostname"] = hostname
        ranked.append(result)
    ranked.sort(key=lambda x: x["score"])
    for i, r in enumerate(ranked, 1):
        r["rank"] = i
    return ranked
