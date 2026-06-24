"""
collectors/gpu.py — GPU / display adapter info via WMI Win32_VideoController.
Also attempts to read screen diagonal from WMI Win32_DesktopMonitor / EDID.
"""

import subprocess
import json


def _wmi_query(wmi_class: str, fields: list) -> list:
    """Run a PowerShell WMI query and return a list of dicts."""
    select = ", ".join(fields)
    cmd = (
        f"Get-WmiObject -Class {wmi_class} | "
        f"Select-Object {select} | ConvertTo-Json -Depth 2"
    )
    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", cmd],
            stderr=subprocess.DEVNULL, timeout=20
        ).decode(errors="replace").strip()
        if not out:
            return []
        data = json.loads(out)
        if isinstance(data, dict):
            data = [data]
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _gpu_info() -> list:
    fields = [
        "Name", "AdapterRAM", "DriverVersion",
        "VideoProcessor", "CurrentHorizontalResolution",
        "CurrentVerticalResolution", "CurrentRefreshRate",
        "VideoModeDescription",
    ]
    rows = _wmi_query("Win32_VideoController", fields)
    gpus = []
    for r in rows:
        name = (r.get("Name") or "").strip()
        if not name:
            continue
        ram_bytes = r.get("AdapterRAM") or 0
        try:
            ram_bytes = int(ram_bytes)
        except Exception:
            ram_bytes = 0
        gpus.append({
            "name": name,
            "vram_bytes": ram_bytes,
            "vram_gb": round(ram_bytes / (1024 ** 3), 1) if ram_bytes > 0 else None,
            "driver_version": (r.get("DriverVersion") or "").strip() or None,
            "resolution": (
                f"{r.get('CurrentHorizontalResolution')}x{r.get('CurrentVerticalResolution')}"
                if r.get("CurrentHorizontalResolution") and r.get("CurrentVerticalResolution")
                else None
            ),
            "refresh_hz": r.get("CurrentRefreshRate") or None,
        })
    return gpus


def _monitor_info() -> list:
    """Try to get monitor size from Win32_DesktopMonitor."""
    fields = ["Name", "ScreenHeight", "ScreenWidth", "MonitorManufacturer", "DeviceID"]
    rows = _wmi_query("Win32_DesktopMonitor", fields)
    monitors = []
    for r in rows:
        name = (r.get("Name") or "").strip()
        monitors.append({
            "name": name or "Unknown Monitor",
            "manufacturer": (r.get("MonitorManufacturer") or "").strip() or None,
            "screen_height_px": r.get("ScreenHeight") or None,
            "screen_width_px": r.get("ScreenWidth") or None,
        })
    return monitors


def _diagonal_from_edid() -> float | None:
    """
    Try to compute diagonal from EDID data stored in registry.
    EDID bytes 21-22 contain physical width/height in mm.
    """
    try:
        import winreg, math
        key_path = (
            r"SYSTEM\CurrentControlSet\Enum\DISPLAY"
        )
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path)
        for i in range(winreg.QueryInfoKey(root)[0]):
            monitor_key_name = winreg.EnumKey(root, i)
            monitor_key = winreg.OpenKey(root, monitor_key_name)
            for j in range(winreg.QueryInfoKey(monitor_key)[0]):
                sub_name = winreg.EnumKey(monitor_key, j)
                sub = winreg.OpenKey(monitor_key, sub_name)
                try:
                    param_key = winreg.OpenKey(sub, "Device Parameters")
                    edid, _ = winreg.QueryValueEx(param_key, "EDID")
                    if edid and len(edid) >= 22:
                        w_mm = edid[21]
                        h_mm = edid[22]
                        if w_mm > 0 and h_mm > 0:
                            diag_mm = math.sqrt(w_mm**2 + h_mm**2)
                            diag_in = round(diag_mm / 25.4, 1)
                            winreg.CloseKey(param_key)
                            winreg.CloseKey(sub)
                            winreg.CloseKey(monitor_key)
                            winreg.CloseKey(root)
                            return diag_in
                    winreg.CloseKey(param_key)
                except Exception:
                    pass
                winreg.CloseKey(sub)
            winreg.CloseKey(monitor_key)
        winreg.CloseKey(root)
    except Exception:
        pass
    return None


def collect() -> dict:
    gpus = _gpu_info()
    monitors = _monitor_info()
    diagonal = _diagonal_from_edid()

    return {
        "gpus": gpus,
        "monitors": monitors,
        "screen_diagonal_inches": diagonal,
    }
