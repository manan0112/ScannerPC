"""
collectors/startup.py — Auto-start entries from registry Run keys and startup folders.
"""
import os
import winreg

_RUN_KEYS = [
    (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run",            "HKCU_Run"),
    (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce",        "HKCU_RunOnce"),
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run",            "HKLM_Run"),
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Run","HKLM_Run_wow"),
]

_STARTUP_FOLDERS = [
    os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup"),
    r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs\Startup",
]


def _read_run_key(hive, subkey: str, label: str) -> list:
    items = []
    try:
        key = winreg.OpenKey(hive, subkey, access=winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
    except OSError:
        return items
    idx = 0
    while True:
        try:
            name, value, _ = winreg.EnumValue(key, idx)
            items.append({"name": name, "command": value, "source": label})
        except OSError:
            break
        idx += 1
    winreg.CloseKey(key)
    return items


def _read_startup_folder(folder_path: str) -> list:
    items = []
    if not os.path.isdir(folder_path):
        return items
    try:
        for entry in os.scandir(folder_path):
            if entry.name.lower() == "desktop.ini":
                continue
            items.append({
                "name": os.path.splitext(entry.name)[0],
                "command": entry.path,
                "source": "startup_folder",
            })
    except OSError:
        pass
    return items


def collect() -> list:
    items = []
    for hive, subkey, label in _RUN_KEYS:
        items.extend(_read_run_key(hive, subkey, label))
    for folder in _STARTUP_FOLDERS:
        items.extend(_read_startup_folder(folder))
    return items
