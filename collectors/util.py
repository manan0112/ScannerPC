"""
collectors/util.py — Shared helpers used by every collector.

Field constraints this module encodes:
- Target machines are old (Windows 7+) and sometimes broken: compiled
  extension modules (_socket.pyd, _ctypes.pyd) have failed to load in the
  field, so nothing here may hard-depend on them. Pure stdlib only.
- PowerShell's ConvertTo-Json collapses a single-element array to a bare
  scalar/object — every list-shaped field must pass through as_list().
"""
import json
import subprocess


def as_list(value):
    """Normalise a maybe-collapsed JSON value: None -> [], list -> list, x -> [x]."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def run_powershell(command, timeout=30):
    """Run a PowerShell command and return decoded stdout, or '' on any failure."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
        )
        if out.returncode != 0 or not out.stdout:
            return ""
        return out.stdout.decode("utf-8", errors="replace")
    except Exception:
        return ""


def ps_json(command, timeout=30):
    """
    Run a PowerShell command whose output is ConvertTo-Json.
    Always returns a list of items (single results are wrapped).
    """
    raw = run_powershell(command, timeout=timeout)
    if not raw.strip():
        return []
    try:
        return as_list(json.loads(raw))
    except ValueError:
        return []


def safe(fn, default, errors=None, label=""):
    """
    Call fn() and return its result; on ANY exception return *default* and
    record the failure in *errors* (list) so one broken sub-part never blanks
    the rest of a collector's section.
    """
    try:
        return fn()
    except Exception as exc:
        if errors is not None:
            name = label or getattr(fn, "__name__", "unknown")
            errors.append("%s: %s: %s" % (name, type(exc).__name__, exc))
        return default
