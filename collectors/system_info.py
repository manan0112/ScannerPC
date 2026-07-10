"""
collectors/system_info.py — Collects OS, CPU, RAM, disk, and uptime info.
Returns a flat dict suitable for JSON serialisation.

Field machines have shipped with broken compiled extensions (_socket.pyd,
_ctypes.pyd failed to load on 7 of 18 PCs), so BOTH are imported defensively
and every value has a stdlib or PowerShell/WMI fallback. Each sub-part is
isolated so one failure never blanks the whole section.
"""
import os
import platform
import datetime

from collectors.util import ps_json, run_powershell, safe

try:
    import ctypes
except ImportError:          # broken _ctypes on damaged installs
    ctypes = None

try:
    import socket as _socket

    def _hostname():
        return _socket.gethostname()

    def _fqdn():
        return _socket.getfqdn()
except ImportError:          # broken _socket on damaged installs
    def _hostname():
        return os.environ.get("COMPUTERNAME", "unknown")

    def _fqdn():
        return os.environ.get("COMPUTERNAME", "unknown")


def _uptime_seconds():
    """System uptime in seconds — GetTickCount64, PowerShell/WMI fallback."""
    if ctypes is not None:
        try:
            return ctypes.windll.kernel32.GetTickCount64() // 1000
        except Exception:
            pass
    # Get-WmiObject works from PowerShell 2.0 (Windows 7) upward.
    out = run_powershell(
        "$os = Get-WmiObject Win32_OperatingSystem; "
        "$boot = $os.ConvertToDateTime($os.LastBootUpTime); "
        "[math]::Round(((Get-Date) - $boot).TotalSeconds)"
    )
    try:
        return int(float(out.strip()))
    except ValueError:
        return -1


def _format_uptime(seconds):
    if seconds < 0:
        return "unavailable"
    td = datetime.timedelta(seconds=seconds)
    days = td.days
    hours, rem = divmod(td.seconds, 3600)
    minutes = rem // 60
    return "%dd %dh %dm" % (days, hours, minutes)


def _disk_partitions_ctypes():
    partitions = []
    drives_mask = ctypes.windll.kernel32.GetLogicalDrives()
    type_map = {2: "removable", 3: "fixed", 4: "network", 5: "cdrom", 6: "ramdisk"}
    for i in range(26):
        if not drives_mask & (1 << i):
            continue
        letter = chr(ord('A') + i) + ":\\"
        drive_type = ctypes.windll.kernel32.GetDriveTypeW(letter)
        free_bytes = ctypes.c_ulonglong(0)
        total_bytes = ctypes.c_ulonglong(0)
        ctypes.windll.kernel32.GetDiskFreeSpaceExW(
            letter, None, ctypes.byref(total_bytes), ctypes.byref(free_bytes)
        )
        partitions.append({
            "drive": letter,
            "type": type_map.get(drive_type, "unknown"),
            "total_bytes": total_bytes.value,
            "free_bytes": free_bytes.value,
            "used_bytes": total_bytes.value - free_bytes.value,
        })
    return partitions


def _disk_partitions_wmi():
    # DriveType: 2=removable, 3=fixed, 4=network, 5=cdrom, 6=ramdisk
    type_map = {2: "removable", 3: "fixed", 4: "network", 5: "cdrom", 6: "ramdisk"}
    partitions = []
    for d in ps_json(
        "Get-WmiObject Win32_LogicalDisk "
        "| Select-Object DeviceID, DriveType, Size, FreeSpace "
        "| ConvertTo-Json -Compress"
    ):
        total = int(d.get("Size") or 0)
        free = int(d.get("FreeSpace") or 0)
        partitions.append({
            "drive": (d.get("DeviceID") or "?") + "\\",
            "type": type_map.get(int(d.get("DriveType") or 0), "unknown"),
            "total_bytes": total,
            "free_bytes": free,
            "used_bytes": total - free,
        })
    return partitions


def _disk_partitions():
    if ctypes is not None:
        try:
            parts = _disk_partitions_ctypes()
            if parts:
                return parts
        except Exception:
            pass
    return _disk_partitions_wmi()


def _memory_info_ctypes():
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    stat = MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(stat)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
        raise OSError("GlobalMemoryStatusEx failed")
    return {
        "total_bytes": stat.ullTotalPhys,
        "available_bytes": stat.ullAvailPhys,
        "used_bytes": stat.ullTotalPhys - stat.ullAvailPhys,
        "load_percent": stat.dwMemoryLoad,
    }


def _memory_info_wmi():
    rows = ps_json(
        "Get-WmiObject Win32_OperatingSystem "
        "| Select-Object TotalVisibleMemorySize, FreePhysicalMemory "
        "| ConvertTo-Json -Compress"
    )
    if not rows:
        return {"error": "memory query failed"}
    row = rows[0]
    total = int(row.get("TotalVisibleMemorySize") or 0) * 1024
    avail = int(row.get("FreePhysicalMemory") or 0) * 1024
    return {
        "total_bytes": total,
        "available_bytes": avail,
        "used_bytes": total - avail,
        "load_percent": round((total - avail) * 100 / total) if total else 0,
    }


def _memory_info():
    if ctypes is not None:
        try:
            return _memory_info_ctypes()
        except Exception:
            pass
    return _memory_info_wmi()


def _cpu_info():
    info = {
        "processor": platform.processor() or "unknown",
        "machine": platform.machine(),
        "physical_cores": os.cpu_count() or -1,
    }
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
        )
        name = winreg.QueryValueEx(key, "ProcessorNameString")[0]
        info["name"] = str(name).strip()
        info["mhz"] = winreg.QueryValueEx(key, "~MHz")[0]
        winreg.CloseKey(key)
    except Exception:
        pass
    return info


def collect():
    errors = []
    uptime_s = safe(_uptime_seconds, -1, errors, "uptime")

    # win32_edition() added in Python 3.8 — guard for 3.7
    try:
        edition = platform.win32_edition() if hasattr(platform, "win32_edition") else "unknown"
    except Exception:
        edition = "unknown"

    result = {
        "hostname": safe(_hostname, os.environ.get("COMPUTERNAME", "unknown"), errors, "hostname"),
        "fqdn": safe(_fqdn, os.environ.get("COMPUTERNAME", "unknown"), errors, "fqdn"),
        "os": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "edition": edition,
            "architecture": platform.architecture()[0],
        },
        "cpu": safe(_cpu_info, {}, errors, "cpu"),
        "memory": safe(_memory_info, {}, errors, "memory"),
        "disks": safe(_disk_partitions, [], errors, "disks"),
        "uptime_seconds": uptime_s,
        "uptime_human": _format_uptime(uptime_s),
        "scan_time_utc": datetime.datetime.utcnow().isoformat() + "Z",
    }
    if errors:
        result["collection_errors"] = errors
    return result
