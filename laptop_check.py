"""
laptop_check.py — Second-hand laptop buyer's health check.
Run this on any laptop before you pay. No installation needed.

Usage:
    laptop_check.exe
    laptop_check.exe --promised "HP,i7 8th gen,8GB RAM,256GB SSD,15 inch"
"""

import argparse
import ctypes
import json
import os
import re
import subprocess
import sys
import time
import winreg

# ── Console colour helpers (plain Windows API, no third-party deps) ───────────

_STD_OUTPUT_HANDLE = -11
_RESET   = 0x07   # grey on black
_GREEN   = 0x0A
_YELLOW  = 0x0E
_RED     = 0x0C
_CYAN    = 0x0B
_WHITE   = 0x0F

try:
    _hcon = ctypes.windll.kernel32.GetStdHandle(_STD_OUTPUT_HANDLE)
    def _colour(code):
        ctypes.windll.kernel32.SetConsoleTextAttribute(_hcon, code)
except Exception:
    def _colour(_):
        pass

def _print_ok(msg):
    _colour(_GREEN);  print(f"  [OK]   {msg}");  _colour(_RESET)

def _print_warn(msg):
    _colour(_YELLOW); print(f"  [WARN] {msg}");  _colour(_RESET)

def _print_fail(msg):
    _colour(_RED);    print(f"  [FAIL] {msg}");  _colour(_RESET)

def _print_info(msg):
    _colour(_CYAN);   print(f"         {msg}");  _colour(_RESET)

def _section(title):
    _colour(_WHITE)
    print()
    print("  " + "─" * 56)
    print(f"  {title}")
    print("  " + "─" * 56)
    _colour(_RESET)


# ── PowerShell helper ─────────────────────────────────────────────────────────

def _ps(cmd, timeout=20):
    """Run a PowerShell command and return stdout as string, or '' on failure."""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
            capture_output=True, timeout=timeout,
        )
        return r.stdout.decode("utf-8", errors="replace").strip() if r.stdout else ""
    except Exception:
        return ""


def _ps_json(cmd, timeout=20):
    """Run PS command, return parsed JSON or {} / [] on failure."""
    out = _ps(cmd + " | ConvertTo-Json -Compress", timeout=timeout)
    if not out:
        return {}
    try:
        return json.loads(out)
    except Exception:
        return {}


# ── Collectors ────────────────────────────────────────────────────────────────

def _get_system_info():
    raw = _ps_json(
        "Get-WmiObject Win32_ComputerSystem "
        "| Select-Object Manufacturer, Model, TotalPhysicalMemory, NumberOfLogicalProcessors"
    )
    bios = _ps_json(
        "Get-WmiObject Win32_BIOS "
        "| Select-Object SerialNumber, SMBIOSBIOSVersion, Manufacturer"
    )
    chassis = _ps_json(
        "Get-WmiObject Win32_SystemEnclosure "
        "| Select-Object ChassisTypes"
    )
    return {
        "manufacturer": str(raw.get("Manufacturer", "")).strip(),
        "model":        str(raw.get("Model", "")).strip(),
        "ram_bytes":    int(raw.get("TotalPhysicalMemory", 0)),
        "logical_cpus": int(raw.get("NumberOfLogicalProcessors", 0)),
        "serial":       str(bios.get("SerialNumber", "")).strip(),
        "bios_version": str(bios.get("SMBIOSBIOSVersion", "")).strip(),
        "chassis_types": chassis.get("ChassisTypes", []),
    }


def _get_cpu_info():
    try:
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
        )
        name = str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
        mhz  = winreg.QueryValueEx(key, "~MHz")[0]
        winreg.CloseKey(key)
    except Exception:
        name = ""
        mhz  = 0

    cores = _ps("(Get-WmiObject Win32_Processor).NumberOfCores")
    threads = _ps("(Get-WmiObject Win32_Processor).NumberOfLogicalProcessors")

    return {
        "name":    name,
        "mhz":     int(mhz),
        "cores":   int(cores) if cores.isdigit() else 0,
        "threads": int(threads) if threads.isdigit() else 0,
    }


def _get_ram_info():
    raw = _ps_json(
        "Get-WmiObject Win32_PhysicalMemory "
        "| Select-Object Capacity, Speed, MemoryType, SMBIOSMemoryType, "
        "  Manufacturer, BankLabel, DeviceLocator"
    )
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        raw = []

    sticks = []
    for s in raw:
        cap = int(s.get("Capacity", 0))
        spd = int(s.get("Speed", 0))
        mt  = int(s.get("SMBIOSMemoryType", s.get("MemoryType", 0)))
        # SMBIOSMemoryType: 26=DDR4, 24=DDR3, 34=DDR5
        type_map = {24: "DDR3", 26: "DDR4", 34: "DDR5", 20: "DDR", 21: "DDR2"}
        sticks.append({
            "size_gb":    round(cap / (1024**3), 1),
            "speed_mhz":  spd,
            "type":       type_map.get(mt, "DDR?"),
            "slot":       str(s.get("DeviceLocator", s.get("BankLabel", ""))),
            "maker":      str(s.get("Manufacturer", "")).strip(),
        })

    total_slots = _ps(
        "(Get-WmiObject Win32_PhysicalMemoryArray).MemoryDevices"
    )
    return {
        "sticks":      sticks,
        "total_slots": int(total_slots) if total_slots.isdigit() else 2,
    }


def _get_storage_info():
    # Primary: Get-PhysicalDisk (Windows 8+, most reliable for SSD/HDD)
    raw = _ps_json(
        "Get-PhysicalDisk "
        "| Select-Object FriendlyName, MediaType, Size, OperationalStatus, HealthStatus"
    )
    if isinstance(raw, dict):
        raw = [raw]

    disks = []
    if isinstance(raw, list):
        for d in raw:
            disks.append({
                "name":   str(d.get("FriendlyName", "")),
                "type":   str(d.get("MediaType", "Unspecified")),
                "size_gb": round(int(d.get("Size", 0)) / (1024**3), 0),
                "health": str(d.get("HealthStatus", "")),
                "status": str(d.get("OperationalStatus", "")),
            })

    # Fallback: WMI Win32_DiskDrive
    if not disks:
        raw2 = _ps_json(
            "Get-WmiObject Win32_DiskDrive "
            "| Select-Object Model, Size, Status, InterfaceType"
        )
        if isinstance(raw2, dict):
            raw2 = [raw2]
        if isinstance(raw2, list):
            for d in raw2:
                sz = int(d.get("Size", 0))
                disks.append({
                    "name":   str(d.get("Model", "")),
                    "type":   "SSD" if "SSD" in str(d.get("Model", "")).upper() else "HDD",
                    "size_gb": round(sz / (1024**3), 0),
                    "health": str(d.get("Status", "")),
                    "status": "",
                })

    # SMART failure prediction
    smart_raw = _ps(
        "Get-WmiObject -Namespace root\\WMI -Class MSStorageDriver_FailurePredictStatus "
        "| Select-Object InstanceName, PredictFailure, Reason"
        " | ConvertTo-Json -Compress"
    )
    smart_fail = False
    try:
        s = json.loads(smart_raw) if smart_raw else {}
        if isinstance(s, dict):
            s = [s]
        for entry in (s if isinstance(s, list) else []):
            if entry.get("PredictFailure"):
                smart_fail = True
    except Exception:
        pass

    # C: drive free space
    free_bytes = ctypes.c_ulonglong(0)
    total_bytes = ctypes.c_ulonglong(0)
    ctypes.windll.kernel32.GetDiskFreeSpaceExW(
        "C:\\", None,
        ctypes.byref(total_bytes),
        ctypes.byref(free_bytes)
    )

    return {
        "disks":        disks,
        "smart_fail":   smart_fail,
        "c_total_gb":   round(total_bytes.value / (1024**3), 1),
        "c_free_gb":    round(free_bytes.value / (1024**3), 1),
    }


def _get_battery_info():
    raw = _ps_json(
        "Get-WmiObject -Namespace root\\WMI -Class BatteryFullChargedCapacity "
        "| Select-Object FullChargedCapacity"
    )
    full_cap = 0
    if isinstance(raw, dict):
        full_cap = int(raw.get("FullChargedCapacity", 0))
    elif isinstance(raw, list) and raw:
        full_cap = int(raw[0].get("FullChargedCapacity", 0))

    static = _ps_json(
        "Get-WmiObject -Namespace root\\WMI -Class BatteryStaticData "
        "| Select-Object DesignedCapacity"
    )
    design_cap = 0
    if isinstance(static, dict):
        design_cap = int(static.get("DesignedCapacity", 0))
    elif isinstance(static, list) and static:
        design_cap = int(static[0].get("DesignedCapacity", 0))

    cycle_raw = _ps_json(
        "Get-WmiObject -Namespace root\\WMI -Class BatteryCycleCount "
        "| Select-Object CycleCount"
    )
    cycle_count = 0
    if isinstance(cycle_raw, dict):
        cycle_count = int(cycle_raw.get("CycleCount", 0))
    elif isinstance(cycle_raw, list) and cycle_raw:
        cycle_count = int(cycle_raw[0].get("CycleCount", 0))

    # Fallback: Win32_Battery
    win32_bat = _ps_json(
        "Get-WmiObject Win32_Battery "
        "| Select-Object Name, BatteryStatus, EstimatedChargeRemaining, DesignCapacity"
    )
    if isinstance(win32_bat, dict):
        win32_bat = [win32_bat]

    bat_present = bool(win32_bat) and isinstance(win32_bat, list)
    bat_status_code = 0
    if bat_present and win32_bat:
        bat_status_code = int(win32_bat[0].get("BatteryStatus", 0))
    # BatteryStatus: 1=Other, 2=Unknown, 3=Fully Charged, 4=Low, 5=Critical,
    #                6=Charging, 7=Charging+High, 8=Charging+Low, 9=Charging+Critical,
    #                10=Undefined, 11=Partially Charged

    status_map = {
        1: "Unknown", 2: "Unknown", 3: "Fully Charged", 4: "Low",
        5: "Critical Low", 6: "Charging", 7: "Charging", 8: "Charging (Low)",
        9: "Charging (Critical)", 11: "Partially Charged"
    }
    status_str = status_map.get(bat_status_code, "On AC / No Battery")

    health_pct = 0
    if design_cap > 0 and full_cap > 0:
        health_pct = round((full_cap / design_cap) * 100)
    elif not bat_present:
        health_pct = -1   # desktop / AC only

    return {
        "present":      bat_present,
        "health_pct":   health_pct,
        "design_mwh":   design_cap,
        "current_mwh":  full_cap,
        "cycle_count":  cycle_count,
        "status":       status_str,
    }


def _get_gpu_info():
    raw = _ps_json(
        "Get-WmiObject Win32_VideoController "
        "| Select-Object Name, AdapterRAM, DriverVersion, VideoModeDescription"
    )
    if isinstance(raw, dict):
        raw = [raw]
    gpus = []
    for g in (raw if isinstance(raw, list) else []):
        vram = int(g.get("AdapterRAM", 0))
        gpus.append({
            "name":    str(g.get("Name", "")),
            "vram_mb": round(vram / (1024**2)) if vram > 0 else 0,
            "driver":  str(g.get("DriverVersion", "")),
            "mode":    str(g.get("VideoModeDescription", "")),
        })
    return gpus


def _get_display_info():
    raw = _ps_json(
        "Get-WmiObject Win32_DesktopMonitor "
        "| Select-Object ScreenWidth, ScreenHeight, MonitorType"
    )
    if isinstance(raw, dict):
        raw = [raw]

    monitors = []
    for m in (raw if isinstance(raw, list) else []):
        w = int(m.get("ScreenWidth", 0))
        h = int(m.get("ScreenHeight", 0))
        if w and h:
            monitors.append({"width": w, "height": h, "type": str(m.get("MonitorType", ""))})

    # Try from registry if WMI returned nothing
    if not monitors:
        try:
            import ctypes
            user32 = ctypes.windll.user32
            w = user32.GetSystemMetrics(0)
            h = user32.GetSystemMetrics(1)
            if w and h:
                monitors.append({"width": w, "height": h, "type": "Primary"})
        except Exception:
            pass

    # DPI from registry → estimate physical size
    dpi = 96
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Control Panel\Desktop\WindowMetrics"
        )
        dpi = int(winreg.QueryValueEx(key, "AppliedDPI")[0])
        winreg.CloseKey(key)
    except Exception:
        try:
            dc = ctypes.windll.user32.GetDC(0)
            dpi = ctypes.windll.gdi32.GetDeviceCaps(dc, 88)  # LOGPIXELSX
            ctypes.windll.user32.ReleaseDC(0, dc)
        except Exception:
            pass

    for m in monitors:
        if dpi > 0 and m["width"] and m["height"]:
            diag_px = (m["width"]**2 + m["height"]**2) ** 0.5
            diag_in = round(diag_px / dpi, 1)
            m["diagonal_inches"] = diag_in

    return monitors


def _get_windows_info():
    # Product name + build
    try:
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
        )
        product   = str(winreg.QueryValueEx(key, "ProductName")[0])
        build     = str(winreg.QueryValueEx(key, "CurrentBuild")[0])
        try:
            ubr = str(winreg.QueryValueEx(key, "UBR")[0])
            build = build + "." + ubr
        except Exception:
            pass
        winreg.CloseKey(key)
    except Exception:
        product = "Unknown"
        build   = ""

    # Activation status via WMI
    lic_raw = _ps(
        "(Get-WmiObject SoftwareLicensingProduct | "
        "Where-Object {$_.Name -like 'Windows*' -and $_.LicenseStatus -eq 1})"
        ".LicenseStatus"
    )
    activated = lic_raw.strip() == "1"

    # Simpler fallback
    if not activated:
        act_out = _ps("(Get-WmiObject SoftwareLicensingProduct -Filter "
                      "\"Name like 'Windows%' and PartialProductKey is not null\""
                      ").LicenseStatus")
        activated = "1" in act_out

    # Last Windows Update
    update_raw = _ps(
        "(New-Object -ComObject Microsoft.Update.Session)"
        ".CreateUpdateSearcher().Search('IsInstalled=1').Updates "
        "| Sort-Object LastDeploymentChangeTime -Descending "
        "| Select-Object -First 1 -ExpandProperty LastDeploymentChangeTime"
    )
    last_update = update_raw.strip()[:10] if update_raw.strip() else "unknown"

    return {
        "product":    product,
        "build":      build,
        "activated":  activated,
        "last_update": last_update,
    }


def _get_temps():
    raw = _ps_json(
        "Get-WmiObject -Namespace root\\WMI -Class MSAcpi_ThermalZoneTemperature "
        "| Select-Object InstanceName, CurrentTemperature"
    )
    if isinstance(raw, dict):
        raw = [raw]
    temps = []
    for t in (raw if isinstance(raw, list) else []):
        k = int(t.get("CurrentTemperature", 0))
        if k > 0:
            c = round((k - 2732) / 10.0, 1)
            if 0 < c < 120:
                temps.append(c)
    return temps


# ── CPU generation parser ────────────────────────────────────────────────────

def _parse_cpu_gen(name):
    """Return (brand, generation_int, series) from CPU name string."""
    name_up = name.upper()

    # Intel: i3/i5/i7/i9 with model number
    m = re.search(r"(i[3579])-(\d{4,5})", name, re.IGNORECASE)
    if m:
        series = m.group(1).lower()
        model  = int(m.group(2))
        # Gen detection by model prefix
        if model < 3000:   gen = 2
        elif model < 4000: gen = 3
        elif model < 5000: gen = 4
        elif model < 6000: gen = 5
        elif model < 7000: gen = 6
        elif model < 8000: gen = 7
        elif model < 9000: gen = 8
        elif model < 10000: gen = 9
        else:
            gen = int(str(model)[:2])
        return "Intel", gen, series

    # Explicit "Xth Gen" label
    m = re.search(r"(\d+)(?:st|nd|rd|th)\s*Gen", name, re.IGNORECASE)
    if m:
        gen = int(m.group(1))
        series = "i7" if "i7" in name_up else ("i5" if "i5" in name_up else "")
        return "Intel", gen, series.lower()

    # AMD Ryzen — Ryzen 5 5600 → gen 5xxx (Zen3)
    m = re.search(r"Ryzen\s+[3579]\s+(\d{4})", name, re.IGNORECASE)
    if m:
        model = int(m.group(1))
        gen = int(str(model)[0])   # 5600 → 5, 7700 → 7, 3600 → 3
        return "AMD", gen, "Ryzen"

    if "PENTIUM" in name_up or "CELERON" in name_up:
        return "Intel", 0, "Pentium/Celeron"

    return "Unknown", 0, ""


# ── Result accumulator ────────────────────────────────────────────────────────

class Results:
    def __init__(self):
        self.ok   = 0
        self.warn = 0
        self.fail = 0
        self.warnings  = []
        self.failures  = []
        self.negotiate = []   # negotiation points for price

    def ok_(self, msg):
        self.ok += 1
        _print_ok(msg)

    def warn_(self, msg, negotiate=None):
        self.warn += 1
        self.warnings.append(msg)
        if negotiate:
            self.negotiate.append(negotiate)
        _print_warn(msg)

    def fail_(self, msg, negotiate=None):
        self.fail += 1
        self.failures.append(msg)
        if negotiate:
            self.negotiate.append(negotiate)
        _print_fail(msg)

    def info_(self, msg):
        _print_info(msg)


# ── Main report ───────────────────────────────────────────────────────────────

def run_checks(promised):
    R = Results()

    # Parse promised specs
    promised_mfr    = promised.get("manufacturer", "").upper()
    promised_gen    = promised.get("gen", 0)
    promised_series = promised.get("series", "").lower()
    promised_ram_gb = promised.get("ram_gb", 0)
    promised_ssd_gb = promised.get("ssd_gb", 0)
    promised_price  = promised.get("price", 0)

    print()
    _colour(_WHITE)
    print("  " + "═" * 56)
    print("    SECOND-HAND LAPTOP BUYER'S CHECK")
    print("    Know exactly what you're buying before you pay")
    print("  " + "═" * 56)
    _colour(_RESET)

    if promised_mfr or promised_gen or promised_ram_gb:
        print()
        print("  Promised to you:")
        parts = []
        if promised_mfr:    parts.append(promised_mfr.title())
        if promised_series: parts.append(f"Core {promised_series.upper()}")
        if promised_gen:    parts.append(f"{promised_gen}th Gen")
        if promised_ram_gb: parts.append(f"{promised_ram_gb}GB RAM")
        if promised_ssd_gb: parts.append(f"{promised_ssd_gb}GB SSD")
        if promised_price:  parts.append(f"Rs.{promised_price:,}")
        print("  " + " | ".join(parts))

    print()
    print("  Scanning... please wait")
    print()

    t0 = time.perf_counter()

    # ── 1. Collect all data ───────────────────────────────────────────────────
    sys_info = _get_system_info()
    cpu      = _get_cpu_info()
    ram      = _get_ram_info()
    storage  = _get_storage_info()
    battery  = _get_battery_info()
    gpus     = _get_gpu_info()
    displays = _get_display_info()
    win      = _get_windows_info()
    temps    = _get_temps()

    brand, cpu_gen, cpu_series = _parse_cpu_gen(cpu["name"])

    # ── 2. Report sections ────────────────────────────────────────────────────

    # — System Identity —
    _section("SYSTEM IDENTITY")
    mfr = sys_info["manufacturer"]
    model = sys_info["model"]

    if promised_mfr and mfr.upper():
        if promised_mfr in mfr.upper():
            R.ok_(f"Manufacturer   : {mfr}")
        else:
            R.fail_(f"Manufacturer   : {mfr}  (promised: {promised_mfr.title()})",
                    "Machine brand doesn't match — confirm before buying")
    else:
        R.ok_(f"Manufacturer   : {mfr}")

    R.ok_(f"Model          : {model}")
    serial = sys_info["serial"]
    if serial and serial not in ("Default string", "To Be Filled By O.E.M."):
        R.ok_(f"Serial Number  : {serial}")
        R.info_("Check serial on manufacturer website to verify warranty status")
    else:
        R.warn_("Serial Number  : Not readable — could be a modified/unmarked unit")

    # — CPU —
    _section("PROCESSOR (CPU)")
    if cpu["name"]:
        R.ok_(f"Processor      : {cpu['name']}")
    else:
        R.warn_("Processor      : Could not read CPU name from registry")

    # Generation check
    if cpu_gen > 0:
        if promised_gen and cpu_gen != promised_gen:
            R.fail_(f"Generation     : {cpu_gen}th Gen {brand} {cpu_series.upper()}  "
                    f"(promised: {promised_gen}th Gen)",
                    f"CPU is {promised_gen - cpu_gen} generation(s) older than promised — "
                    f"ask for Rs.{abs(promised_gen - cpu_gen) * 2000:,} discount")
        elif promised_series and cpu_series and promised_series not in cpu_series:
            R.fail_(f"Series         : Core {cpu_series.upper()}  "
                    f"(promised: Core {promised_series.upper()})",
                    f"CPU series doesn't match — this affects performance significantly")
        else:
            R.ok_(f"Generation     : {cpu_gen}th Gen {brand}  {'✓ matches promise' if promised_gen else ''}")
    else:
        R.warn_("Generation     : Could not determine CPU generation")

    if cpu["cores"] > 0:
        R.ok_(f"Cores/Threads  : {cpu['cores']} cores / {cpu['threads']} threads")
    if cpu["mhz"] > 0:
        R.ok_(f"Base Clock     : {cpu['mhz']:,} MHz")

    # — RAM —
    _section("MEMORY (RAM)")
    sticks = ram["sticks"]
    total_ram_gb = sum(s["size_gb"] for s in sticks)
    used_slots   = len(sticks)
    total_slots  = ram["total_slots"]

    if promised_ram_gb and total_ram_gb > 0:
        if abs(total_ram_gb - promised_ram_gb) > 1:
            R.fail_(f"Total RAM      : {total_ram_gb:.0f} GB  (promised: {promised_ram_gb} GB)",
                    f"RAM is {abs(total_ram_gb - promised_ram_gb):.0f}GB less than promised")
        else:
            R.ok_(f"Total RAM      : {total_ram_gb:.0f} GB  ✓ matches promise")
    elif total_ram_gb > 0:
        R.ok_(f"Total RAM      : {total_ram_gb:.0f} GB")

    for i, s in enumerate(sticks, 1):
        R.ok_(f"Stick {i}         : {s['size_gb']:.0f} GB  {s['type']}  {s['speed_mhz']} MHz  [{s['slot']}]")

    free_slots = total_slots - used_slots
    if free_slots > 0:
        R.info_(f"Upgrade room   : {free_slots} slot(s) free — can add more RAM later")
    else:
        R.info_("Upgrade room   : All RAM slots in use")

    # — Storage —
    _section("STORAGE (SSD / HDD)")

    if storage["smart_fail"]:
        R.fail_("SMART Health   : FAILURE PREDICTED — disk may die soon!",
                "DO NOT BUY — the disk is failing. Data loss risk.")
    else:
        R.ok_("SMART Health   : No failure predicted")

    boot_disk_type = "Unknown"
    boot_disk_gb   = 0

    for d in storage["disks"]:
        dtype = d["type"]
        dname = d["name"]
        size  = d["size_gb"]

        is_ssd = any(x in dtype.upper() for x in ("SSD", "NVME", "SOLID")) or \
                 any(x in dname.upper() for x in ("SSD", "NVME", "NVM"))
        is_hdd = "HDD" in dtype.upper() or "HARD" in dtype.lower()

        if "C" in dtype.upper() or size > 100:   # Likely boot disk
            boot_disk_type = "SSD/NVMe" if is_ssd else ("HDD" if is_hdd else dtype)
            boot_disk_gb   = size

        if is_ssd:
            R.ok_(f"Disk Type      : SSD / NVMe  ✓  ({dname})")
        elif is_hdd:
            R.fail_(f"Disk Type      : HDD — NOT an SSD!  ({dname})",
                    "This is a spinning hard disk, NOT SSD. Negotiate Rs.3,000–5,000 off "
                    "or ask them to install an SSD before sale")
        elif "UNSPECIFIED" in dtype.upper() or "UNKNOWN" in dtype.upper():
            R.warn_(f"Disk Type      : Could not confirm SSD/HDD  ({dname})")
        else:
            R.warn_(f"Disk Type      : {dtype}  ({dname})")

        if promised_ssd_gb and size > 0:
            if abs(size - promised_ssd_gb) > 30:
                R.fail_(f"Disk Size      : {size:.0f} GB  (promised: {promised_ssd_gb} GB)",
                        f"Disk is {abs(size - promised_ssd_gb):.0f}GB different from promised")
            else:
                R.ok_(f"Disk Size      : {size:.0f} GB  ✓ matches promise")
        elif size > 0:
            R.ok_(f"Disk Size      : {size:.0f} GB")

        health = d["health"]
        if health and health.lower() not in ("healthy", "ok", ""):
            R.warn_(f"Disk Health    : {health}")

    # C: drive usage
    if storage["c_total_gb"] > 0:
        free_pct = round((storage["c_free_gb"] / storage["c_total_gb"]) * 100)
        R.ok_(f"C: Free Space  : {storage['c_free_gb']:.0f} GB of {storage['c_total_gb']:.0f} GB ({free_pct}% free)")

    # — Battery —
    _section("BATTERY HEALTH")
    if not battery["present"] or battery["health_pct"] == -1:
        R.info_("No battery detected (desktop / running on AC only)")
    else:
        hp = battery["health_pct"]
        dc = battery["design_mwh"]
        fc = battery["current_mwh"]
        cc = battery["cycle_count"]

        if dc > 0 and fc > 0:
            R.ok_(f"Design Capacity: {dc:,} mWh")
            R.ok_(f"Current Max    : {fc:,} mWh")

        if hp >= 80:
            R.ok_(f"Battery Health : {hp}%  — Good")
        elif hp >= 60:
            R.warn_(f"Battery Health : {hp}%  — Moderate wear",
                    f"Battery at {hp}% — negotiate Rs.1,500–2,500 off or ask for new battery")
        elif hp >= 40:
            R.warn_(f"Battery Health : {hp}%  — Heavy wear (replacement soon)",
                    f"Battery at {hp}% — ask for Rs.2,500–4,000 discount (new battery cost)")
        elif hp > 0:
            R.fail_(f"Battery Health : {hp}%  — Very poor, needs immediate replacement",
                    f"Battery nearly dead — negotiate Rs.4,000+ off or have them replace it")
        else:
            R.warn_("Battery Health : Could not read capacity (WMI not supported on this system)")

        if cc > 0:
            if cc < 300:
                R.ok_(f"Cycle Count    : {cc} cycles  — Low use")
            elif cc < 500:
                R.warn_(f"Cycle Count    : {cc} cycles  — Moderate use")
            else:
                R.warn_(f"Cycle Count    : {cc} cycles  — Heavy use",
                        f"High cycle count ({cc}) — battery life will be short per charge")

        R.ok_(f"Battery Status : {battery['status']}")

    # — Graphics —
    _section("GRAPHICS (GPU)")
    for i, g in enumerate(gpus, 1):
        name   = g["name"]
        vram   = g["vram_mb"]
        driver = g["driver"]
        prefix = f"GPU {i}" if len(gpus) > 1 else "GPU"

        # Classify
        is_dedicated = any(x in name.upper() for x in
                           ("NVIDIA", "GEFORCE", "QUADRO", "RADEON", "AMD", "RX ", "GTX", "RTX"))
        is_intel_iris = "IRIS" in name.upper()
        is_intel_uhd  = "UHD" in name.upper() or "HD GRAPHICS" in name.upper()

        if is_dedicated:
            R.ok_(f"{prefix}          : {name}  (Dedicated GPU ✓)")
        elif is_intel_iris:
            R.ok_(f"{prefix}          : {name}  (Intel Iris — good integrated)")
        elif is_intel_uhd:
            R.ok_(f"{prefix}          : {name}  (Intel UHD — integrated, suitable for office)")
        else:
            R.ok_(f"{prefix}          : {name}")

        if vram > 0:
            R.info_(f"VRAM           : {vram:,} MB")
        if driver:
            R.info_(f"Driver         : {driver}")

    if not gpus:
        R.warn_("GPU            : Could not read GPU information")

    # — Display —
    _section("DISPLAY")
    for d in displays:
        w = d.get("width", 0)
        h = d.get("height", 0)
        diag = d.get("diagonal_inches", 0)

        if w and h:
            res = f"{w} x {h}"
            if h >= 1080:
                R.ok_(f"Resolution     : {res}  (Full HD ✓)")
            elif h >= 768:
                R.warn_(f"Resolution     : {res}  — HD only, not Full HD")
            else:
                R.warn_(f"Resolution     : {res}  — Low resolution")

        if diag > 0:
            R.info_(f"Est. Diagonal  : ~{diag}\"  (calculated from resolution + DPI)")

    if not displays:
        R.warn_("Display        : Could not read display information")

    # — Windows —
    _section("WINDOWS & ACTIVATION")
    R.ok_(f"Windows        : {win['product']}  (Build {win['build']})")
    if win["activated"]:
        R.ok_("Activation     : Activated  ✓")
    else:
        R.fail_("Activation     : NOT ACTIVATED",
                "Windows is not activated — you'll get nag screens and limited features. "
                "Ask seller to provide genuine activation or deduct Rs.1,000–2,000")

    if win["last_update"] and win["last_update"] != "unknown":
        R.ok_(f"Last Update    : {win['last_update']}")

    # — Thermals —
    if temps:
        _section("TEMPERATURES")
        max_temp = max(temps)
        avg_temp = round(sum(temps) / len(temps), 1)
        if max_temp < 65:
            R.ok_(f"CPU Temp       : {max_temp}°C  (normal)")
        elif max_temp < 80:
            R.warn_(f"CPU Temp       : {max_temp}°C  (warm — check thermal paste age)")
        else:
            R.warn_(f"CPU Temp       : {max_temp}°C  — Hot! Could be clogged fan/old paste",
                    "High temperatures suggest the laptop needs thermal servicing (~Rs.500-1000)")

    # ── VERDICT ───────────────────────────────────────────────────────────────
    elapsed = round(time.perf_counter() - t0, 1)

    _colour(_WHITE)
    print()
    print("  " + "═" * 56)
    print("  OVERALL VERDICT")
    print("  " + "═" * 56)
    _colour(_RESET)
    print()

    total = R.ok + R.warn + R.fail
    _colour(_GREEN);  print(f"  Passed  : {R.ok}")
    _colour(_YELLOW); print(f"  Warnings: {R.warn}")
    _colour(_RED);    print(f"  Failed  : {R.fail}")
    _colour(_RESET);  print()

    # Spec match
    spec_ok = R.fail == 0
    if spec_ok and R.warn == 0:
        _colour(_GREEN)
        print("  VERDICT: GOOD BUY — all checks passed")
        if promised_price:
            print(f"  Price Rs.{promised_price:,} looks fair for these specs")
        _colour(_RESET)
    elif spec_ok and R.warn > 0:
        _colour(_YELLOW)
        print("  VERDICT: ACCEPTABLE — with negotiation")
        if promised_price and R.negotiate:
            disc = sum(
                int(re.search(r"Rs\.\s*(\d[\d,]*)", n).group(1).replace(",",""))
                for n in R.negotiate
                if re.search(r"Rs\.\s*(\d[\d,]*)", n)
            )
            if disc:
                print(f"  Suggested price: Rs.{promised_price - disc:,}  (Rs.{disc:,} off for issues found)")
        _colour(_RESET)
    else:
        _colour(_RED)
        print("  VERDICT: ISSUES FOUND — negotiate or walk away")
        _colour(_RESET)

    if R.failures:
        print()
        _colour(_RED)
        print("  CRITICAL ISSUES:")
        for f in R.failures:
            print(f"    ✗ {f}")
        _colour(_RESET)

    if R.warnings:
        print()
        _colour(_YELLOW)
        print("  WARNINGS:")
        for w in R.warnings:
            print(f"    ! {w}")
        _colour(_RESET)

    if R.negotiate:
        print()
        _colour(_CYAN)
        print("  NEGOTIATION POINTS (show seller):")
        for n in R.negotiate:
            print(f"    → {n}")
        _colour(_RESET)

    print()
    print(f"  Scan completed in {elapsed}s")
    print()

    # Save report
    report_path = os.path.join(os.getcwd(), "laptop_check_report.txt")
    try:
        with open(report_path, "w", encoding="utf-8") as fh:
            fh.write(f"Laptop Health Check Report\n")
            fh.write(f"{'='*50}\n")
            fh.write(f"System  : {sys_info['manufacturer']} {sys_info['model']}\n")
            fh.write(f"CPU     : {cpu['name']}\n")
            total_ram = sum(s["size_gb"] for s in ram["sticks"])
            fh.write(f"RAM     : {total_ram:.0f} GB\n")
            fh.write(f"Windows : {win['product']}  Activated={win['activated']}\n\n")
            fh.write(f"Checks  : {R.ok} passed, {R.warn} warnings, {R.fail} failed\n\n")
            if R.failures:
                fh.write("CRITICAL ISSUES:\n")
                for f in R.failures:
                    fh.write(f"  - {f}\n")
                fh.write("\n")
            if R.warnings:
                fh.write("WARNINGS:\n")
                for w in R.warnings:
                    fh.write(f"  - {w}\n")
                fh.write("\n")
            if R.negotiate:
                fh.write("NEGOTIATION POINTS:\n")
                for n in R.negotiate:
                    fh.write(f"  - {n}\n")
        print(f"  Report saved: {report_path}")
    except Exception:
        pass

    print()


# ── Entry point ───────────────────────────────────────────────────────────────

def _parse_args():
    p = argparse.ArgumentParser(
        description="Second-hand laptop buyer's health check"
    )
    p.add_argument("--manufacturer", "-m", default="HP",
                   help="Expected manufacturer (default: HP)")
    p.add_argument("--gen",          "-g", type=int, default=8,
                   help="Expected CPU generation number (default: 8)")
    p.add_argument("--series",       "-s", default="i7",
                   help="Expected CPU series, e.g. i7, i5 (default: i7)")
    p.add_argument("--ram",          "-r", type=int, default=8,
                   help="Expected RAM in GB (default: 8)")
    p.add_argument("--ssd",          "-d", type=int, default=256,
                   help="Expected SSD size in GB (default: 256)")
    p.add_argument("--price",        "-p", type=int, default=25000,
                   help="Asking price in Rs (default: 25000)")
    return p.parse_args()


def main():
    args = _parse_args()
    promised = {
        "manufacturer": args.manufacturer,
        "gen":          args.gen,
        "series":       args.series,
        "ram_gb":       args.ram,
        "ssd_gb":       args.ssd,
        "price":        args.price,
    }
    run_checks(promised)
    input("  Press ENTER to exit...")


if __name__ == "__main__":
    main()
