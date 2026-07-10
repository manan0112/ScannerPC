"""
collectors/network.py — IP addresses, MAC addresses, mapped network drives, domain info.
"""
import os
import winreg

from collectors.util import as_list, ps_json, safe

try:
    import socket as _socket

    def _gethostname():
        return _socket.gethostname()

    def _getaddrinfo(host):
        return _socket.getaddrinfo(host, None, _socket.AF_INET)
except ImportError:          # broken _socket on damaged installs
    def _gethostname():
        return os.environ.get("COMPUTERNAME", "unknown")

    def _getaddrinfo(host):
        return []


def _wmi_adapters() -> list:
    """Active network adapters via WMI — works on Windows 7+."""
    raw = ps_json(
        "Get-WmiObject Win32_NetworkAdapterConfiguration "
        "| Where-Object {$_.IPEnabled} "
        "| Select-Object Description, MACAddress, IPAddress, DefaultIPGateway "
        "| ConvertTo-Json -Compress",
        timeout=15,
    )
    result = []
    for a in raw:
        ips = as_list(a.get("IPAddress"))
        ipv4 = [ip for ip in ips if "." in ip and not ip.startswith("169.254")]
        result.append({
            "description": a.get("Description", ""),
            "mac":         a.get("MACAddress", ""),
            "ipv4":        ipv4,
        })
    return result


def _fallback_ips():
    """Plain socket fallback when WMI is unavailable."""
    try:
        hostname = _gethostname()
        seen = set()
        ips = []
        for _, _, _, _, (ip, _) in _getaddrinfo(hostname):
            if ip not in seen and not ip.startswith("127."):
                seen.add(ip)
                ips.append({"description": "unknown", "mac": "", "ipv4": [ip]})
        return ips
    except Exception:
        return []


def _mapped_drives() -> list:
    drives = []
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Network")
        idx = 0
        while True:
            try:
                letter = winreg.EnumKey(key, idx)
                idx += 1
                try:
                    dk = winreg.OpenKey(key, letter)
                    path, _ = winreg.QueryValueEx(dk, "RemotePath")
                    drives.append({"drive": letter + ":\\", "remote_path": path})
                    winreg.CloseKey(dk)
                except OSError:
                    pass
            except OSError:
                break
        winreg.CloseKey(key)
    except OSError:
        pass
    return drives


def collect() -> dict:
    errors = []
    adapters = safe(_wmi_adapters, [], errors, "wmi_adapters") \
        or safe(_fallback_ips, [], errors, "fallback_ips")
    result = {
        "adapters":       adapters,
        "mapped_drives":  safe(_mapped_drives, [], errors, "mapped_drives"),
        "domain":         os.environ.get("USERDOMAIN", ""),
        "logged_in_user": os.environ.get("USERNAME", ""),
        "computer_name":  os.environ.get("COMPUTERNAME", "") or safe(_gethostname, "unknown", errors, "hostname"),
    }
    if errors:
        result["collection_errors"] = errors
    return result
