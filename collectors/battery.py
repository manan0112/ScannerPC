"""
collectors/battery.py — Battery health via WMI BatteryFullChargedCapacity.
Returns design capacity, current full-charge capacity, and health %.
"""

import subprocess
import re


def _wmi_battery() -> dict:
    """Query WMI for battery static data (design vs full-charge capacity)."""
    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command",
             "Get-WmiObject -Namespace root/WMI -Class BatteryStaticData | "
             "Select-Object DesignedCapacity | ConvertTo-Json"],
            stderr=subprocess.DEVNULL, timeout=15
        ).decode(errors="replace")
        import json
        data = json.loads(out)
        if isinstance(data, list):
            data = data[0]
        design = int(data.get("DesignedCapacity", 0))
    except Exception:
        design = 0

    try:
        out2 = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command",
             "Get-WmiObject -Namespace root/WMI -Class BatteryFullChargedCapacity | "
             "Select-Object FullChargedCapacity | ConvertTo-Json"],
            stderr=subprocess.DEVNULL, timeout=15
        ).decode(errors="replace")
        import json
        data2 = json.loads(out2)
        if isinstance(data2, list):
            data2 = data2[0]
        full = int(data2.get("FullChargedCapacity", 0))
    except Exception:
        full = 0

    return design, full


def _powercfg_battery() -> dict:
    """
    Fallback: run powercfg /batteryreport and parse the HTML for capacity values.
    Returns (design_mwh, full_mwh) or (0, 0) on failure.
    """
    try:
        import tempfile, os
        tmp = tempfile.mktemp(suffix=".html")
        subprocess.run(
            ["powercfg", "/batteryreport", "/output", tmp, "/duration", "1"],
            capture_output=True, timeout=30
        )
        if not os.path.exists(tmp):
            return 0, 0
        with open(tmp, encoding="utf-8", errors="replace") as f:
            html = f.read()
        os.unlink(tmp)

        design_match = re.search(
            r'DESIGN CAPACITY.*?(\d[\d,]+)\s*m[Ww][Hh]', html, re.DOTALL)
        full_match = re.search(
            r'FULL CHARGE CAPACITY.*?(\d[\d,]+)\s*m[Ww][Hh]', html, re.DOTALL)

        design = int(design_match.group(1).replace(",", "")) if design_match else 0
        full = int(full_match.group(1).replace(",", "")) if full_match else 0
        return design, full
    except Exception:
        return 0, 0


def collect() -> dict:
    design, full = _wmi_battery()

    if design == 0 or full == 0:
        design, full = _powercfg_battery()

    if design > 0 and full > 0:
        health_pct = round(full / design * 100, 1)
    else:
        health_pct = None

    present = design > 0 or full > 0

    result = {
        "battery_present": present,
        "design_capacity_mwh": design if design > 0 else None,
        "full_charge_capacity_mwh": full if full > 0 else None,
        "health_percent": health_pct,
    }

    if health_pct is not None:
        if health_pct >= 80:
            result["health_status"] = "GOOD"
        elif health_pct >= 50:
            result["health_status"] = "FAIR"
        else:
            result["health_status"] = "POOR"
    else:
        result["health_status"] = "UNKNOWN (no battery or desktop)"

    return result
