"""
collectors/storage_detail.py — SSD vs HDD detection and drive health via WMI.
Uses Win32_DiskDrive + Get-PhysicalDisk (Storage module) for media type.
"""

import subprocess
import json


def _physical_disks_ps() -> list:
    """Use Get-PhysicalDisk to get MediaType (SSD/HDD/SCM) and size."""
    cmd = (
        "Get-PhysicalDisk | "
        "Select-Object FriendlyName, MediaType, Size, HealthStatus, OperationalStatus | "
        "ConvertTo-Json -Depth 2"
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


def _wmi_disk_drives() -> list:
    """Fallback: Win32_DiskDrive for model, size, interface."""
    cmd = (
        "Get-WmiObject Win32_DiskDrive | "
        "Select-Object Model, Size, InterfaceType, MediaType, Status | "
        "ConvertTo-Json -Depth 2"
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


def collect() -> dict:
    physical = _physical_disks_ps()
    wmi_drives = _wmi_disk_drives()

    disks = []
    for d in physical:
        name = (d.get("FriendlyName") or "").strip()
        media = (d.get("MediaType") or "").strip()
        size_bytes = d.get("Size") or 0
        try:
            size_bytes = int(size_bytes)
        except Exception:
            size_bytes = 0
        disks.append({
            "name": name or "Unknown",
            "media_type": media or "Unknown",
            "is_ssd": "SSD" in media.upper() or "SOLID" in media.upper(),
            "size_bytes": size_bytes,
            "size_gb": round(size_bytes / (1024 ** 3), 1) if size_bytes > 0 else None,
            "health_status": (d.get("HealthStatus") or "").strip() or None,
            "operational_status": (d.get("OperationalStatus") or "").strip() or None,
        })

    # Merge with WMI data if physical was empty
    if not disks:
        for d in wmi_drives:
            model = (d.get("Model") or "").strip()
            size_bytes = d.get("Size") or 0
            try:
                size_bytes = int(size_bytes)
            except Exception:
                size_bytes = 0
            iface = (d.get("InterfaceType") or "").strip()
            media = (d.get("MediaType") or "").strip()
            disks.append({
                "name": model or "Unknown",
                "media_type": media or iface or "Unknown",
                "is_ssd": any(kw in (model + media).upper()
                              for kw in ["SSD", "SOLID", "NVME", "NVM"]),
                "size_bytes": size_bytes,
                "size_gb": round(size_bytes / (1024 ** 3), 1) if size_bytes > 0 else None,
                "health_status": (d.get("Status") or "").strip() or None,
                "operational_status": None,
            })

    return {"physical_disks": disks}
