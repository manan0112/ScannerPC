"""
collectors/user_folders.py — Profiles personal folders with file-type and age breakdown.
Scans Desktop, Downloads, Documents, Pictures, Videos and the local OneDrive folder.
"""
import os
import time

# File type buckets keyed by extension
_TYPES: dict = {
    "office_docs": {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
                    ".pdf", ".csv", ".txt", ".rtf", ".odt", ".ods"},
    "tally_data":  {".tdb", ".900", ".tdl"},
    "images":      {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp"},
    "videos":      {".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm", ".3gp"},
    "audio":       {".mp3", ".wav", ".aac", ".flac", ".wma", ".ogg"},
    "archives":    {".zip", ".rar", ".7z", ".tar", ".gz"},
    "executables": {".exe", ".msi", ".bat", ".cmd", ".ps1"},
    "installers":  {".iso", ".img"},
}


def _type_bucket(ext: str) -> str:
    ext = ext.lower()
    for bucket, exts in _TYPES.items():
        if ext in exts:
            return bucket
    return "other"


def _age_bucket(mtime: float) -> str:
    age_days = (time.time() - mtime) / 86400
    if age_days < 30:
        return "last_30_days"
    if age_days < 90:
        return "last_90_days"
    if age_days < 365:
        return "last_year"
    if age_days < 1095:
        return "1_to_3_years"
    return "over_3_years"


def _analyse(path: str, cap: int = 8000) -> dict:
    if not os.path.isdir(path):
        return {"exists": False, "size_bytes": 0}

    total_bytes = 0
    file_count  = 0
    type_bytes: dict  = {}
    age_bytes: dict   = {}
    scanned = 0

    try:
        for root, _dirs, files in os.walk(path, followlinks=False):
            for fname in files:
                if scanned >= cap:
                    break
                try:
                    st = os.stat(os.path.join(root, fname))
                except OSError:
                    continue
                sz = st.st_size
                total_bytes += sz
                file_count  += 1
                scanned     += 1
                ext    = os.path.splitext(fname)[1]
                tbuck  = _type_bucket(ext)
                abuck  = _age_bucket(st.st_mtime)
                type_bytes[tbuck] = type_bytes.get(tbuck, 0) + sz
                age_bytes[abuck]  = age_bytes.get(abuck, 0)  + sz
    except OSError:
        pass

    return {
        "exists":        True,
        "path":          path,
        "size_bytes":    total_bytes,
        "file_count":    file_count,
        "by_type_bytes": type_bytes,
        "by_age_bytes":  age_bytes,
    }


def collect() -> dict:
    up = os.environ.get("USERPROFILE", r"C:\Users\Default")

    folders = {
        "desktop":   os.path.join(up, "Desktop"),
        "downloads": os.path.join(up, "Downloads"),
        "documents": os.path.join(up, "Documents"),
        "pictures":  os.path.join(up, "Pictures"),
        "videos":    os.path.join(up, "Videos"),
        "music":     os.path.join(up, "Music"),
    }

    result = {name: _analyse(path) for name, path in folders.items()}

    # OneDrive local folder (env var set by OneDrive client)
    od_path = os.environ.get("OneDrive", os.path.join(up, "OneDrive"))
    result["onedrive_local"] = _analyse(od_path)

    return result
