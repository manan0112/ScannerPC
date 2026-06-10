"""
collectors/network.py — IP addresses, MAC addresses, mapped network drives, domain info.
"""
import json
import os
import socket
import subprocess
import winreg


def _wmi_adapters() -> list:
    """Active network adapters via WMI — works on Windows 7+."""
    try:
        cmd = (
            "Get-WmiObject Win32_NetworkAdapterConfiguration "
            "| Where-Object {$_.IPEnabled} "
            "| Select-Object Description, MACAddress, IPAddress, DefaultIPGateway "
            "| ConvertTo-Json -Compress"
        )
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
            capture_output=True, timeout=15,
        )
        if out.returncode != 0 or not out.stdout:
            return []
        raw = json.loads(out.stdout)
        if isinstance(raw, dict):
            raw = [raw]
        result = []
        for a in raw:
            ips = a.get("IPAddress") or []
            if isinstance(ips, str):
                ips = [ips]
            ipv4 = [ip for ip in ips if "." in ip and not ip.startswith("169.254")]
            result.append({
                "description": a.get("Description", ""),
                "mac":         a.get("MACAddress", ""),
                "ipv4":        ipv4,
            })
        return result
    except Exception:
        return []


def _fallback_ips() -> list:
    """Plain socket fallback when WMI is unavailable."""
    try:
        hostname = socket.gethostname()
        seen: set = set()
        ips = []
        for _, _, _, _, (ip, _) in socket.getaddrinfo(hostname, None, socket.AF_INET):
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
    adapters = _wmi_adapters() or _fallback_ips()
    return {
        "adapters":       adapters,
        "mapped_drives":  _mapped_drives(),
        "domain":         os.environ.get("USERDOMAIN", ""),
        "logged_in_user": os.environ.get("USERNAME", ""),
        "computer_name":  os.environ.get("COMPUTERNAME", socket.gethostname()),
    }
