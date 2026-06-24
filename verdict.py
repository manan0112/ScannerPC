"""
verdict.py — Compare scanned hardware against the promised laptop specs
and produce a colour-coded terminal report.

Promised spec:
  - Brand     : HP
  - CPU       : Intel Core i7, 8th generation
  - RAM       : 8 GB
  - Storage   : 256 GB SSD
  - Screen    : 15 inches
  - Colour    : Silver (cosmetic — not checkable via software)
"""

import math

# ── ANSI colours (work on Windows 10+ with ENABLE_VIRTUAL_TERMINAL_PROCESSING) ─
_RESET  = "\033[0m"
_BOLD   = "\033[1m"
_GREEN  = "\033[92m"
_YELLOW = "\033[93m"
_RED    = "\033[91m"
_CYAN   = "\033[96m"
_WHITE  = "\033[97m"
_DIM    = "\033[2m"

PASS  = f"{_GREEN}  PASS {_RESET}"
WARN  = f"{_YELLOW}  WARN {_RESET}"
FAIL  = f"{_RED}  FAIL {_RESET}"
INFO  = f"{_CYAN}  INFO {_RESET}"
SKIP  = f"{_DIM}  SKIP {_RESET}"


def _enable_ansi():
    """Enable ANSI escape codes on Windows console."""
    try:
        import ctypes, sys
        if sys.platform == "win32":
            kernel32 = ctypes.windll.kernel32
            # ENABLE_PROCESSED_OUTPUT | ENABLE_VIRTUAL_TERMINAL_PROCESSING
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Individual check helpers
# ─────────────────────────────────────────────────────────────────────────────

def _check_brand(report: dict) -> list:
    lines = []
    cpu_name = (report.get("system_info", {})
                      .get("cpu", {})
                      .get("name", "")).upper()
    if "HP" in cpu_name or "HEWLETT" in cpu_name:
        lines.append((PASS, "Brand", "HP detected in system strings"))
    else:
        # Try BIOS/system manufacturer from WMI (best-effort)
        mfr = (report.get("system_info", {})
                     .get("manufacturer", "") or "").upper()
        if "HP" in mfr or "HEWLETT" in mfr:
            lines.append((PASS, "Brand", f"HP — {mfr}"))
        else:
            lines.append((WARN, "Brand",
                          "Cannot confirm HP from software; check physically"))
    return lines


def _check_cpu(report: dict) -> list:
    cpu = report.get("system_info", {}).get("cpu", {})
    name = (cpu.get("name") or cpu.get("processor") or "").strip()
    lines = []

    # i7 check
    if "i7" in name.lower():
        lines.append((PASS, "CPU Model", f"Core i7 confirmed — {name}"))
    else:
        lines.append((FAIL, "CPU Model",
                      f"NOT i7 — found: {name or 'unknown'}"))

    # 8th-gen check: codenames Coffee Lake / Whiskey Lake use model numbers 8xxx
    gen = None
    import re
    m = re.search(r'i\d-(\d)(\d{3})', name, re.IGNORECASE)
    if m:
        gen = int(m.group(1))
    if gen == 8:
        lines.append((PASS, "CPU Generation", f"8th Gen confirmed (model: {m.group(0)})"))
    elif gen is not None:
        lines.append((FAIL, "CPU Generation",
                      f"Expected 8th Gen — found {gen}th Gen (model: {m.group(0)})"))
    else:
        lines.append((WARN, "CPU Generation",
                      f"Cannot determine gen from name: '{name}'"))

    mhz = cpu.get("mhz")
    if mhz:
        lines.append((INFO, "CPU Speed", f"{mhz} MHz base clock"))

    cores = cpu.get("physical_cores")
    if cores:
        lines.append((INFO, "CPU Cores", f"{cores} logical processors"))

    return lines


def _check_ram(report: dict) -> list:
    mem = report.get("system_info", {}).get("memory", {})
    total = mem.get("total_bytes", 0)
    lines = []
    if total:
        total_gb = total / (1024 ** 3)
        total_gb_r = round(total_gb, 1)
        if total_gb >= 7.5:   # 8 GB sticks often show ~7.9 GB usable
            lines.append((PASS, "RAM",
                          f"{total_gb_r} GB installed (promised: 8 GB)"))
        elif total_gb >= 6:
            lines.append((WARN, "RAM",
                          f"Only {total_gb_r} GB — expected 8 GB"))
        else:
            lines.append((FAIL, "RAM",
                          f"Only {total_gb_r} GB — expected 8 GB"))
        used_gb = round(mem.get("used_bytes", 0) / (1024 ** 3), 1)
        avail_gb = round(mem.get("available_bytes", 0) / (1024 ** 3), 1)
        load = mem.get("load_percent", 0)
        lines.append((INFO, "RAM Usage",
                      f"{used_gb} GB used / {avail_gb} GB free ({load}% load)"))
    else:
        lines.append((FAIL, "RAM", "Could not read RAM info"))
    return lines


def _check_storage(report: dict) -> list:
    lines = []
    disks_info = report.get("storage_detail", {}).get("physical_disks", [])

    if not disks_info:
        # Fallback: use basic disk info from system_info
        basic_disks = report.get("system_info", {}).get("disks", [])
        total_gb = sum(
            d.get("total_bytes", 0) for d in basic_disks
            if d.get("type") == "fixed"
        ) / (1024 ** 3)
        if total_gb >= 230:
            lines.append((PASS, "Storage Size",
                          f"{round(total_gb, 0):.0f} GB total fixed drives"))
        else:
            lines.append((FAIL, "Storage Size",
                          f"Only {round(total_gb, 0):.0f} GB — expected 256 GB"))
        lines.append((WARN, "SSD Detection",
                      "Could not determine SSD/HDD — run as admin for full info"))
        return lines

    ssd_found = any(d.get("is_ssd") for d in disks_info)
    for d in disks_info:
        size_gb = d.get("size_gb") or 0
        name = d.get("name", "Unknown")
        media = d.get("media_type", "Unknown")
        health = d.get("health_status") or "Unknown"

        # SSD check
        if d.get("is_ssd"):
            lines.append((PASS, "Drive Type", f"SSD confirmed — {name}"))
        else:
            lines.append((FAIL, "Drive Type",
                          f"HDD detected — {name} ({media}). Expected SSD."))

        # Size check (256 GB drives show ~238 GB in binary)
        if size_gb >= 230:
            lines.append((PASS, "Drive Size",
                          f"{size_gb} GB (promised: 256 GB)"))
        elif size_gb >= 100:
            lines.append((WARN, "Drive Size",
                          f"Only {size_gb} GB — expected ~256 GB"))
        else:
            lines.append((FAIL, "Drive Size",
                          f"Only {size_gb} GB — expected ~256 GB"))

        # Health
        if health.lower() in ("healthy", "ok", "good"):
            lines.append((PASS, "Drive Health", f"{health} — {name}"))
        elif health.lower() == "unknown":
            lines.append((WARN, "Drive Health",
                          f"Health unknown for {name}"))
        else:
            lines.append((FAIL, "Drive Health",
                          f"{health} — {name} may need replacement"))

        # Free space on C:
    basic_disks = report.get("system_info", {}).get("disks", [])
    for bd in basic_disks:
        if bd.get("drive", "").startswith("C"):
            free_gb = round(bd.get("free_bytes", 0) / (1024 ** 3), 1)
            used_gb = round(bd.get("used_bytes", 0) / (1024 ** 3), 1)
            total_gb = round(bd.get("total_bytes", 0) / (1024 ** 3), 1)
            lines.append((INFO, "C: Drive Space",
                          f"{free_gb} GB free / {total_gb} GB total ({used_gb} GB used)"))

    return lines


def _check_gpu(report: dict) -> list:
    gpus = report.get("gpu", {}).get("gpus", [])
    lines = []
    if not gpus:
        lines.append((WARN, "GPU", "No GPU info found"))
        return lines

    for g in gpus:
        name = g.get("name", "Unknown")
        vram = g.get("vram_gb")
        res = g.get("resolution")
        hz = g.get("refresh_hz")
        driver = g.get("driver_version")

        # 8th-gen i7 laptops typically have Intel UHD 620 + optional discrete
        is_intel = "INTEL" in name.upper()
        is_discrete = any(kw in name.upper()
                          for kw in ["NVIDIA", "AMD", "RADEON", "GEFORCE", "GTX", "RTX", "MX"])

        if is_discrete:
            lines.append((PASS, "GPU (Discrete)", f"{name}"))
        elif is_intel:
            lines.append((INFO, "GPU (Integrated)", f"{name} — standard for 8th-gen i7"))
        else:
            lines.append((INFO, "GPU", name))

        if vram:
            lines.append((INFO, "VRAM", f"{vram} GB"))
        if res:
            lines.append((INFO, "Current Resolution", res))
        if hz:
            lines.append((INFO, "Refresh Rate", f"{hz} Hz"))
        if driver:
            lines.append((INFO, "GPU Driver", driver))

    return lines


def _check_screen(report: dict) -> list:
    diag = report.get("gpu", {}).get("screen_diagonal_inches")
    lines = []
    if diag:
        if 14.5 <= diag <= 15.9:
            lines.append((PASS, "Screen Size",
                          f"{diag}\" diagonal (promised: 15\")"))
        else:
            lines.append((FAIL, "Screen Size",
                          f"{diag}\" diagonal — expected ~15\""))
    else:
        lines.append((WARN, "Screen Size",
                      "Could not auto-detect screen size from EDID; verify physically"))
    monitors = report.get("gpu", {}).get("monitors", [])
    for m in monitors:
        mfr = m.get("manufacturer") or ""
        name = m.get("name") or ""
        if mfr or name:
            lines.append((INFO, "Monitor", f"{name} {mfr}".strip()))
    return lines


def _check_battery(report: dict) -> list:
    bat = report.get("battery", {})
    lines = []
    if not bat.get("battery_present"):
        lines.append((WARN, "Battery",
                      "No battery detected (already removed, or desktop system)"))
        return lines

    health_pct = bat.get("health_percent")
    status = bat.get("health_status", "UNKNOWN")
    design = bat.get("design_capacity_mwh")
    full = bat.get("full_charge_capacity_mwh")

    if health_pct is not None:
        if status == "GOOD":
            lines.append((PASS, "Battery Health",
                          f"{health_pct}% ({full} mWh of {design} mWh design)"))
        elif status == "FAIR":
            lines.append((WARN, "Battery Health",
                          f"{health_pct}% — degraded; consider replacement"))
        else:
            lines.append((FAIL, "Battery Health",
                          f"{health_pct}% — severely degraded; needs replacement"))
    else:
        lines.append((WARN, "Battery Health",
                      f"Status: {status}"))
    return lines


def _check_os(report: dict) -> list:
    os_info = report.get("system_info", {}).get("os", {})
    lines = []
    release = os_info.get("release", "")
    version = os_info.get("version", "")
    edition = os_info.get("edition", "")
    arch = os_info.get("architecture", "")
    lines.append((INFO, "OS", f"Windows {release} {edition} ({arch})"))
    lines.append((INFO, "OS Version", version[:60] if version else "unknown"))

    uptime = report.get("system_info", {}).get("uptime_human", "")
    if uptime:
        lines.append((INFO, "Uptime", uptime))
    return lines


def _check_software(report: dict) -> list:
    sw = report.get("software", [])
    lines = []
    if isinstance(sw, list):
        lines.append((INFO, "Installed Apps", f"{len(sw)} apps found in registry"))
        # Flag any suspicious / trial / bloatware software
        bloat_keywords = [
            "trial", "demo", "mcafee", "norton", "avast", "avg trial",
            "candy crush", "farmville", "spotify", "tiktok",
        ]
        bloat_found = [
            s["name"] for s in sw
            if any(kw in s.get("name", "").lower() for kw in bloat_keywords)
        ]
        if bloat_found:
            lines.append((WARN, "Bloatware/Trials",
                          "Found: " + ", ".join(bloat_found[:5])))
        else:
            lines.append((PASS, "Bloatware", "No obvious bloatware/trial apps found"))
    else:
        lines.append((WARN, "Installed Apps", "Could not read software list"))
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Main display function
# ─────────────────────────────────────────────────────────────────────────────

def print_verdict(report: dict) -> None:
    _enable_ansi()

    W = 72
    bar = "─" * W

    def header(title: str):
        print(f"\n{_BOLD}{_CYAN}{'━' * W}{_RESET}")
        pad = (W - len(title) - 2) // 2
        print(f"{_BOLD}{_CYAN}{'━' * pad} {title} {'━' * (W - pad - len(title) - 2)}{_RESET}")
        print(f"{_BOLD}{_CYAN}{'━' * W}{_RESET}")

    def section(title: str):
        print(f"\n{_BOLD}{_WHITE}  ▸ {title}{_RESET}")
        print(f"  {_DIM}{bar[:W-4]}{_RESET}")

    def row(tag: str, label: str, detail: str):
        label_fmt = f"{_BOLD}{label:<22}{_RESET}"
        print(f"  {tag} {label_fmt}  {detail}")

    header("SECOND-HAND LAPTOP VERIFICATION REPORT")

    print(f"\n  {_DIM}Promised spec: HP · Core i7 8th Gen · 8 GB RAM · 256 GB SSD · 15\" screen{_RESET}")
    print(f"  {_DIM}Scanned    : {report.get('system_info', {}).get('hostname', 'unknown')} "
          f"at {report.get('system_info', {}).get('scan_time_utc', '')}{_RESET}")

    all_rows: list[tuple] = []

    # Run all checks
    checks = [
        ("SYSTEM & OS",       _check_os(report)),
        ("CPU",               _check_cpu(report)),
        ("RAM",               _check_ram(report)),
        ("STORAGE / SSD",     _check_storage(report)),
        ("GPU / GRAPHICS",    _check_gpu(report)),
        ("SCREEN SIZE",       _check_screen(report)),
        ("BATTERY HEALTH",    _check_battery(report)),
        ("INSTALLED SOFTWARE", _check_software(report)),
    ]

    pass_count = fail_count = warn_count = 0

    for section_title, rows in checks:
        section(section_title)
        for tag, label, detail in rows:
            row(tag, label, detail)
            all_rows.append((tag, label, detail))
            if "PASS" in tag:
                pass_count += 1
            elif "FAIL" in tag:
                fail_count += 1
            elif "WARN" in tag:
                warn_count += 1

    # ── Summary ──────────────────────────────────────────────────────────────
    header("VERDICT SUMMARY")

    total_checks = pass_count + fail_count + warn_count
    if fail_count == 0 and warn_count == 0:
        verdict = f"{_GREEN}{_BOLD}ALL CLEAR — Laptop matches the promised spec!{_RESET}"
    elif fail_count == 0:
        verdict = f"{_YELLOW}{_BOLD}MOSTLY OK — Minor issues to review (see WARNINGs){_RESET}"
    elif fail_count <= 2:
        verdict = f"{_RED}{_BOLD}ISSUES FOUND — {fail_count} spec mismatch(es) detected{_RESET}"
    else:
        verdict = f"{_RED}{_BOLD}SIGNIFICANT PROBLEMS — Multiple spec failures. Negotiate or walk away.{_RESET}"

    print(f"\n  {verdict}")
    print(f"\n  {_GREEN}PASS{_RESET}  {pass_count}   "
          f"{_YELLOW}WARN{_RESET}  {warn_count}   "
          f"{_RED}FAIL{_RESET}  {fail_count}   "
          f"{_DIM}(out of {total_checks} checks){_RESET}")

    if fail_count > 0:
        print(f"\n  {_RED}{_BOLD}Failed checks:{_RESET}")
        for tag, label, detail in all_rows:
            if "FAIL" in tag:
                print(f"    {FAIL} {_BOLD}{label}{_RESET} — {detail}")

    if warn_count > 0:
        print(f"\n  {_YELLOW}{_BOLD}Warnings:{_RESET}")
        for tag, label, detail in all_rows:
            if "WARN" in tag:
                print(f"    {WARN} {_BOLD}{label}{_RESET} — {detail}")

    print(f"\n  {_DIM}Note: Screen colour (silver) cannot be verified via software — check physically.{_RESET}")
    print(f"\n{_BOLD}{_CYAN}{'━' * W}{_RESET}\n")
