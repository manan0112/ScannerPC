"""
collectors/onedrive.py — OneDrive client status, sync folders, Teams installation.
"""
import os
import winreg


def _read_account(subkey: str) -> dict:
    info = {}
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, subkey)
        for field in ("UserEmail", "DisplayName", "ServiceEndpointUri", "cid"):
            try:
                val, _ = winreg.QueryValueEx(key, field)
                info[field] = val
            except OSError:
                pass
        winreg.CloseKey(key)
    except OSError:
        pass
    return info


def _onedrive_exe_exists() -> bool:
    localappdata = os.environ.get("LOCALAPPDATA", "")
    return os.path.exists(os.path.join(localappdata, "Microsoft", "OneDrive", "OneDrive.exe"))


def _sync_folders() -> list:
    """Return local OneDrive sync root paths from environment variables."""
    paths = []
    for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        p = os.environ.get(var, "")
        if p and os.path.isdir(p) and p not in paths:
            paths.append(p)
    return paths


def _quick_size(path: str, cap: int = 5000) -> int:
    total, n = 0, 0
    try:
        for root, _dirs, files in os.walk(path, followlinks=False):
            for f in files:
                if n >= cap:
                    return total
                try:
                    total += os.path.getsize(os.path.join(root, f))
                    n += 1
                except OSError:
                    pass
    except OSError:
        pass
    return total


def _teams_installed() -> bool:
    localappdata = os.environ.get("LOCALAPPDATA", "")
    paths = [
        os.path.join(localappdata, "Microsoft", "Teams", "current", "Teams.exe"),
        r"C:\Program Files\Microsoft\Teams\current\Teams.exe",
        r"C:\Program Files (x86)\Microsoft\Teams\current\Teams.exe",
        # Newer Teams (work or school)
        os.path.join(localappdata, "Microsoft", "WindowsApps", "msteams.exe"),
    ]
    return any(os.path.exists(p) for p in paths)


def collect() -> dict:
    sync_paths = _sync_folders()
    return {
        "client_installed":       _onedrive_exe_exists() or bool(sync_paths),
        "sync_folders":           sync_paths,
        "total_local_sync_bytes": sum(_quick_size(p) for p in sync_paths),
        "business_account":       _read_account(r"SOFTWARE\Microsoft\OneDrive\Accounts\Business1"),
        "personal_account":       _read_account(r"SOFTWARE\Microsoft\OneDrive\Accounts\Personal"),
        "teams_installed":        _teams_installed(),
    }
