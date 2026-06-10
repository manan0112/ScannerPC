"""
collectors/junk.py — Measures well-known recoverable disk space.
Each category has: path(s), size_bytes, safe_to_delete flag, description.
"""
import ctypes
import glob as _glob
import os


def _dir_size(path: str) -> int:
    total = 0
    try:
        for root, _dirs, files in os.walk(path, followlinks=False):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
    except OSError:
        pass
    return total


def _file_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _glob_size(pattern: str) -> tuple:
    paths = _glob.glob(pattern)
    return paths, sum(_dir_size(p) for p in paths)


def collect() -> dict:
    userprofile  = os.environ.get("USERPROFILE",  r"C:\Users\Default")
    localappdata = os.environ.get("LOCALAPPDATA", os.path.join(userprofile, "AppData", "Local"))
    appdata      = os.environ.get("APPDATA",      os.path.join(userprofile, "AppData", "Roaming"))
    user_temp    = os.environ.get("TEMP",         os.path.join(localappdata, "Temp"))

    cats: dict = {}

    # ── Temp folders ──────────────────────────────────────────────────────────
    cats["user_temp"] = {
        "path": user_temp,
        "size_bytes": _dir_size(user_temp),
        "safe_to_delete": True,
        "description": "User temporary files (%TEMP%)",
    }
    cats["windows_temp"] = {
        "path": r"C:\Windows\Temp",
        "size_bytes": _dir_size(r"C:\Windows\Temp"),
        "safe_to_delete": True,
        "description": "Windows system temporary files",
    }

    # ── Windows Update download cache ────────────────────────────────────────
    wu = r"C:\Windows\SoftwareDistribution\Download"
    cats["windows_update_cache"] = {
        "path": wu,
        "size_bytes": _dir_size(wu),
        "safe_to_delete": True,
        "description": "Downloaded Windows update packages (re-downloadable)",
    }

    # ── Prefetch ─────────────────────────────────────────────────────────────
    cats["prefetch"] = {
        "path": r"C:\Windows\Prefetch",
        "size_bytes": _dir_size(r"C:\Windows\Prefetch"),
        "safe_to_delete": True,
        "description": "Windows prefetch / superfetch cache",
    }

    # ── Recycle Bin (all drives) ──────────────────────────────────────────────
    rb_paths, rb_total = [], 0
    try:
        mask = ctypes.windll.kernel32.GetLogicalDrives()
        for i in range(26):
            if mask & (1 << i):
                rb = chr(ord("A") + i) + r":\$Recycle.Bin"
                sz = _dir_size(rb)
                if sz > 0:
                    rb_paths.append(rb)
                    rb_total += sz
    except Exception:
        pass
    cats["recycle_bin"] = {
        "paths": rb_paths,
        "size_bytes": rb_total,
        "safe_to_delete": True,
        "description": "Items waiting in Recycle Bin",
    }

    # ── Downloads folder ─────────────────────────────────────────────────────
    dl = os.path.join(userprofile, "Downloads")
    cats["downloads"] = {
        "path": dl,
        "size_bytes": _dir_size(dl),
        "safe_to_delete": False,
        "description": "User downloads — review individually before deleting",
    }

    # ── Browser caches ───────────────────────────────────────────────────────
    chrome_cache = os.path.join(localappdata, r"Google\Chrome\User Data\Default\Cache")
    cats["chrome_cache"] = {
        "path": chrome_cache,
        "size_bytes": _dir_size(chrome_cache),
        "safe_to_delete": True,
        "description": "Google Chrome browser cache",
    }
    edge_cache = os.path.join(localappdata, r"Microsoft\Edge\User Data\Default\Cache")
    cats["edge_cache"] = {
        "path": edge_cache,
        "size_bytes": _dir_size(edge_cache),
        "safe_to_delete": True,
        "description": "Microsoft Edge browser cache",
    }
    ff_paths, ff_size = _glob_size(
        os.path.join(appdata, r"Mozilla\Firefox\Profiles\*\cache2")
    )
    cats["firefox_cache"] = {
        "paths": ff_paths,
        "size_bytes": ff_size,
        "safe_to_delete": True,
        "description": "Mozilla Firefox browser cache",
    }

    # ── WhatsApp media cache ─────────────────────────────────────────────────
    wa_path = os.path.join(localappdata, "WhatsApp")
    cats["whatsapp_data"] = {
        "path": wa_path,
        "size_bytes": _dir_size(wa_path),
        "safe_to_delete": False,
        "description": "WhatsApp Desktop data and media",
    }

    # ── System files ─────────────────────────────────────────────────────────
    cats["hibernation_file"] = {
        "path": r"C:\hiberfil.sys",
        "size_bytes": _file_size(r"C:\hiberfil.sys"),
        "safe_to_delete": False,
        "description": "Hibernation file — run 'powercfg /h off' to remove if unused",
    }
    cats["page_file"] = {
        "path": r"C:\pagefile.sys",
        "size_bytes": _file_size(r"C:\pagefile.sys"),
        "safe_to_delete": False,
        "description": "Virtual memory page file — system managed",
    }

    # ── Windows Installer patch cache ────────────────────────────────────────
    patch_cache = r"C:\Windows\Installer\$PatchCache$"
    cats["installer_patch_cache"] = {
        "path": patch_cache,
        "size_bytes": _dir_size(patch_cache),
        "safe_to_delete": False,
        "description": "MSI patch cache — use PatchCleaner tool to safely remove",
    }

    safe_total = sum(
        v["size_bytes"] for v in cats.values() if v.get("safe_to_delete")
    )
    return {
        "categories": cats,
        "safe_to_delete_bytes": safe_total,
        "total_measured_bytes": sum(v.get("size_bytes", 0) for v in cats.values()),
    }
