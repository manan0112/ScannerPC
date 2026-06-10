"""
collectors/metadata.py — Enriches a list of file records with detailed
file-system metadata: timestamps, owner (via Windows security API), and
extension/MIME hint.
"""

import os
import datetime
import ctypes
import ctypes.wintypes
from config import METADATA_FIELDS

# ── Owner resolution via Win32 ────────────────────────────────────────────────

_advapi = ctypes.windll.advapi32

def _get_owner(path: str) -> str:
    """Return 'DOMAIN\\User' string for the file owner, or 'unknown'."""
    try:
        # GetFileSecurity flags: OWNER_SECURITY_INFORMATION = 0x1
        needed = ctypes.wintypes.DWORD(0)
        _advapi.GetFileSecurityW(path, 1, None, 0, ctypes.byref(needed))
        buf = ctypes.create_string_buffer(needed.value)
        if not _advapi.GetFileSecurityW(path, 1, buf, needed, ctypes.byref(needed)):
            return "unknown"

        psid = ctypes.c_void_p()
        defaulted = ctypes.wintypes.BOOL()
        if not _advapi.GetSecurityDescriptorOwner(
            buf, ctypes.byref(psid), ctypes.byref(defaulted)
        ):
            return "unknown"

        name = ctypes.create_unicode_buffer(256)
        name_size = ctypes.wintypes.DWORD(256)
        domain = ctypes.create_unicode_buffer(256)
        domain_size = ctypes.wintypes.DWORD(256)
        sid_type = ctypes.wintypes.DWORD()

        if _advapi.LookupAccountSidW(
            None, psid,
            name, ctypes.byref(name_size),
            domain, ctypes.byref(domain_size),
            ctypes.byref(sid_type)
        ):
            return f"{domain.value}\\{name.value}"
        return "unknown"
    except Exception:
        return "unknown"


# ── Timestamp helpers ─────────────────────────────────────────────────────────

def _ts(epoch: float) -> str:
    """Convert a POSIX timestamp to an ISO-8601 UTC string."""
    return datetime.datetime.utcfromtimestamp(epoch).isoformat() + "Z"


# ── Extension / MIME hint ─────────────────────────────────────────────────────

_EXT_HINTS = {
    ".exe": "application/x-msdownload",
    ".dll": "application/x-msdownload",
    ".msi": "application/x-msi",
    ".zip": "application/zip",
    ".7z":  "application/x-7z-compressed",
    ".rar": "application/x-rar-compressed",
    ".iso": "application/x-iso9660-image",
    ".mp4": "video/mp4",
    ".mkv": "video/x-matroska",
    ".avi": "video/x-msvideo",
    ".mov": "video/quicktime",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".vhd":  "application/x-virtualbox-vhd",
    ".vmdk": "application/x-vmdk",
    ".bak":  "application/octet-stream",
    ".log":  "text/plain",
}

def _mime_hint(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    return _EXT_HINTS.get(ext, "application/octet-stream")


# ── Main collector ────────────────────────────────────────────────────────────

def enrich(file_records: list) -> list:
    """
    Accept the output of collectors.files.collect() and return each record
    augmented with metadata fields configured in METADATA_FIELDS.
    """
    enriched = []
    for rec in file_records:
        path = rec.get("path", "")
        out = dict(rec)  # copy existing fields (path, size_bytes)

        try:
            st = os.stat(path)
        except OSError as exc:
            out["metadata_error"] = str(exc)
            enriched.append(out)
            continue

        if "size" in METADATA_FIELDS:
            out["size_bytes"] = st.st_size           # already present; refresh
        if "created" in METADATA_FIELDS:
            out["created_utc"] = _ts(st.st_ctime)
        if "modified" in METADATA_FIELDS:
            out["modified_utc"] = _ts(st.st_mtime)
        if "accessed" in METADATA_FIELDS:
            out["accessed_utc"] = _ts(st.st_atime)
        if "owner" in METADATA_FIELDS:
            out["owner"] = _get_owner(path)

        out["extension"] = os.path.splitext(path)[1].lower()
        out["mime_hint"] = _mime_hint(path)
        out["filename"] = os.path.basename(path)

        enriched.append(out)

    return enriched