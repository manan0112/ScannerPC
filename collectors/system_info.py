"""
collectors/system_info.py — Collects OS, CPU, RAM, disk, and network info.
Returns a flat dict suitable for JSON serialisation.
"""

import os
import platform
import ctypes
import datetime

# socket may fail on broken/old Windows installs — import defensively
try:
    import socket as _socket
    def _hostname():
        return _socket.gethostname()
    def _fqdn():
        return _socket.getfqdn()
except ImportError:
    def _hostname():
        return os.environ.get("COMPUTERNAME", "unknown")
    def _fqdn():
        return os.environ.get("COMPUTERNAME", "unknown")


def _uptime_seconds():
    """Return system uptime in seconds using GetTickCount64 (Windows only)."""
    try:
        return ctypes.windll.kernel32.GetTickCount64() // 1000
    except Exception:
        return -1


def _format_uptime(seconds):
    if seconds < 0:
        return "unavailable"
    td = datetime.timedelta(seconds=seconds)
    days = td.days
    hours, rem = divmod(td.seconds, 3600)
    minutes = rem // 60
    return "%dd %dh %dm" % (days, hours, minutes)


def _disk_partitions():
    partitions = []
    try:
        drives_mask = ctypes.windll.kernel32.GetLogicalDrives()
        for i in range(26):
            if drives_mask & (1 << i):
                letter = chr(ord('A') + i) + ":\\"
                drive_type = ctypes.windll.kernel32.GetDriveTypeW(letter)
                type_map = {2: "removable", 3: "fixed", 4: "network",
                            5: "cdrom", 6: "ramdisk"}
                drive_type_str = type_map.get(drive_type, "unknown")

                free_bytes = ctypes.c_ulonglong(0)
                total_bytes = ctypes.c_ulonglong(0)
                ctypes.windll.kernel32.GetDiskFreeSpaceExW(
                    letter, None,
                    ctypes.byref(total_bytes),
                    ctypes.byref(free_bytes)
                )
                partitions.append({
                    "drive": letter,
                    "type": drive_type_str,
                    "total_bytes": total_bytes.value,
                    "free_bytes": free_bytes.value,
                    "used_bytes": total_bytes.value - free_bytes.value,
                })
    except Exception as exc:
        partitions.append({"error": str(exc)})
    return partitions


def _memory_info():
    try:
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
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        return {
            "total_bytes": stat.ullTotalPhys,
            "available_bytes": stat.ullAvailPhys,
            "used_bytes": stat.ullTotalPhys - stat.ullAvailPhys,
            "load_percent": stat.dwMemoryLoad,
        }
    except Exception as exc:
        return {"error": str(exc)}


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
    uptime_s = _uptime_seconds()
    # win32_edition() added in Python 3.8 — guard for 3.7
    try:
        edition = platform.win32_edition() if hasattr(platform, "win32_edition") else "unknown"
    except Exception:
        edition = "unknown"

    return {
        "hostname": _hostname(),
        "fqdn": _fqdn(),
        "os": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "edition": edition,
            "architecture": platform.architecture()[0],
        },
        "cpu": _cpu_info(),
        "memory": _memory_info(),
        "disks": _disk_partitions(),
        "uptime_seconds": uptime_s,
        "uptime_human": _format_uptime(uptime_s),
        "scan_time_utc": datetime.datetime.utcnow().isoformat() + "Z",
    }
