"""
collectors/security.py — AV products, Windows Update status, firewall, pending reboot.
"""
import winreg

from collectors.util import ps_json, safe


def _av_products() -> list:
    """Query SecurityCenter2 WMI namespace for installed AV products."""
    try:
        # Get-WmiObject (not Get-CimInstance) so PowerShell 2.0 on Windows 7 works too.
        raw = ps_json(
            "Get-WmiObject -Namespace root/SecurityCenter2 -Class AntiVirusProduct "
            "| Select-Object displayName, productState, pathToSignedProductExe "
            "| ConvertTo-Json -Compress",
            timeout=15,
        )
        result = []
        for p in raw:
            state = int(p.get("productState") or 0)
            # Middle byte of productState: 0x10 = definitions up-to-date
            # High byte: 0x10 = enabled
            enabled     = bool((state >> 16) & 0x10)
            definitions = bool((state >> 8)  & 0x10)
            result.append({
                "name":             p.get("displayName", ""),
                "real_time_on":     enabled,
                "definitions_ok":   definitions,
                "state_raw":        hex(state),
                "exe_path":         p.get("pathToSignedProductExe", ""),
            })
        return result
    except Exception:
        return []


def _last_windows_update() -> str:
    paths = [
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\Results\Install",
         "LastSuccessTime"),
    ]
    for hive, subkey, value in paths:
        try:
            key = winreg.OpenKey(hive, subkey)
            val, _ = winreg.QueryValueEx(key, value)
            winreg.CloseKey(key)
            return str(val)
        except OSError:
            continue
    return None


def _pending_reboot() -> bool:
    checks = [
        (winreg.HKEY_LOCAL_MACHINE,
         r"SYSTEM\CurrentControlSet\Control\Session Manager",
         "PendingFileRenameOperations"),
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired",
         None),
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending",
         None),
    ]
    for hive, subkey, value_name in checks:
        try:
            key = winreg.OpenKey(hive, subkey)
            if value_name:
                val, _ = winreg.QueryValueEx(key, value_name)
                winreg.CloseKey(key)
                if val:
                    return True
            else:
                winreg.CloseKey(key)
                return True
        except OSError:
            pass
    return False


def _firewall() -> dict:
    profiles = {
        "domain":  r"SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters\FirewallPolicy\DomainProfile",
        "private": r"SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters\FirewallPolicy\StandardProfile",
        "public":  r"SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters\FirewallPolicy\PublicProfile",
    }
    status = {}
    for name, subkey in profiles.items():
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, subkey)
            val, _ = winreg.QueryValueEx(key, "EnableFirewall")
            status[name] = bool(val)
            winreg.CloseKey(key)
        except OSError:
            status[name] = None
    return status


def collect() -> dict:
    errors = []
    result = {
        "antivirus_products":  safe(_av_products, [], errors, "antivirus_products"),
        "last_windows_update": safe(_last_windows_update, None, errors, "last_windows_update"),
        "pending_reboot":      safe(_pending_reboot, False, errors, "pending_reboot"),
        "firewall":            safe(_firewall, {}, errors, "firewall"),
    }
    if errors:
        result["collection_errors"] = errors
    return result
