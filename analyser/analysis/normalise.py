"""
analysis/normalise.py — Shapes raw scan JSON into what the analysers expect.

Two field realities are handled here:
1. PowerShell's ConvertTo-Json collapses single-element arrays to a scalar,
   so every list-shaped field must pass through as_list().
2. A failed collector leaves {"error": "<traceback>"} where a list or dict
   was expected; those are downgraded to empty defaults and the error text
   is preserved under scan["_collector_errors"][section].
"""


def as_list(value):
    """Normalise a maybe-collapsed JSON value: None -> [], list -> list, x -> [x]."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


# Sections whose top-level value must be a list.
_LIST_SECTIONS = ("software", "startup", "folders", "large_files")

# Sections whose top-level value must be a dict.
_DICT_SECTIONS = (
    "system_info", "win11_readiness", "processes", "disk_health",
    "security", "network", "onedrive", "junk", "user_folders",
)

# (section, key) pairs whose nested value must be a list.
_NESTED_LISTS = (
    ("system_info",     "disks"),
    ("disk_health",     "physical_disks"),
    ("disk_health",     "smart_status"),
    ("disk_health",     "warnings"),
    ("network",         "adapters"),
    ("network",         "mapped_drives"),
    ("processes",       "top_by_memory"),
    ("security",        "antivirus_products"),
    ("onedrive",        "sync_folders"),
    ("win11_readiness", "gpus"),
    ("win11_readiness", "verdict_reasons"),
    ("win11_readiness", "unknowns"),
)


def _is_error(value):
    return isinstance(value, dict) and "error" in value and len(value) == 1


def normalise_scan(scan: dict) -> dict:
    """Normalise one scan in place (and return it)."""
    errors = scan.setdefault("_collector_errors", {})

    for section in _LIST_SECTIONS:
        value = scan.get(section)
        if _is_error(value):
            errors[section] = value["error"]
            scan[section] = []
        elif section in scan:
            scan[section] = as_list(value)

    for section in _DICT_SECTIONS:
        value = scan.get(section)
        if _is_error(value):
            errors[section] = value["error"]
            scan[section] = {}

    for section, key in _NESTED_LISTS:
        sec = scan.get(section)
        if isinstance(sec, dict) and key in sec:
            sec[key] = as_list(sec[key])

    # Per-adapter IP lists collapse too.
    net = scan.get("network")
    if isinstance(net, dict):
        for adapter in net.get("adapters", []):
            if isinstance(adapter, dict):
                adapter["ipv4"] = as_list(adapter.get("ipv4"))

    return scan
