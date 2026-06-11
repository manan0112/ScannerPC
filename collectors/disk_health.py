"""
collectors/disk_health.py — Physical disk inventory and SMART health prediction.
Catches failing HDDs on older machines before they take data with them.
"""
import json
import subprocess


def _physical_disks() -> list:
    """Win32_DiskDrive — works on Windows 7 and later."""
    try:
        cmd = (
            "Get-WmiObject Win32_DiskDrive "
            "| Select-Object Model, SerialNumber, Size, MediaType, "
            "InterfaceType, Status, Index "
            "| ConvertTo-Json -Compress"
        )
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
            capture_output=True, timeout=30,
        )
        if out.returncode != 0 or not out.stdout:
            return []
        raw = json.loads(out.stdout)
        if isinstance(raw, dict):
            raw = [raw]
        disks = []
        for d in raw:
            disks.append({
                "index":          d.get("Index"),
                "model":          (d.get("Model") or "").strip(),
                "serial":         (d.get("SerialNumber") or "").strip(),
                "size_bytes":     int(d.get("Size") or 0),
                "media_type":     d.get("MediaType") or "",
                "interface":      d.get("InterfaceType") or "",
                "wmi_status":     d.get("Status") or "",
            })
        return disks
    except Exception:
        return []


def _storage_health() -> list:
    """Get-PhysicalDisk (Windows 8+) — HealthStatus and SSD/HDD media type."""
    try:
        cmd = (
            "Get-PhysicalDisk "
            "| Select-Object FriendlyName, SerialNumber, MediaType, HealthStatus, "
            "@{N='SizeBytes';E={$_.Size}} "
            "| ConvertTo-Json -Compress"
        )
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
            capture_output=True, timeout=30,
        )
        if out.returncode != 0 or not out.stdout:
            return []
        raw = json.loads(out.stdout)
        if isinstance(raw, dict):
            raw = [raw]
        result = []
        for d in raw:
            mt = d.get("MediaType")
            # MediaType may come back as int enum (3=HDD, 4=SSD) or string
            if isinstance(mt, int):
                mt = {3: "HDD", 4: "SSD", 5: "SCM"}.get(mt, str(mt))
            result.append({
                "name":          d.get("FriendlyName") or "",
                "serial":        (str(d.get("SerialNumber") or "")).strip(),
                "media_type":    mt or "Unspecified",
                "health_status": d.get("HealthStatus") or "",
                "size_bytes":    int(d.get("SizeBytes") or 0),
            })
        return result
    except Exception:
        return []


def _smart_predict_failure() -> list:
    """MSStorageDriver_FailurePredictStatus — SMART 'predict failure' bit per drive."""
    try:
        cmd = (
            "Get-WmiObject -Namespace root\\wmi MSStorageDriver_FailurePredictStatus "
            "| Select-Object InstanceName, PredictFailure, Reason "
            "| ConvertTo-Json -Compress"
        )
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
            capture_output=True, timeout=30,
        )
        if out.returncode != 0 or not out.stdout:
            return []
        raw = json.loads(out.stdout)
        if isinstance(raw, dict):
            raw = [raw]
        return [
            {
                "instance":        s.get("InstanceName") or "",
                "predict_failure": bool(s.get("PredictFailure")),
                "reason":          s.get("Reason"),
            }
            for s in raw
        ]
    except Exception:
        return []


def collect() -> dict:
    disks  = _physical_disks()
    health = _storage_health()
    smart  = _smart_predict_failure()

    # Merge HealthStatus / media type into the disk list by serial where possible
    by_serial = {h["serial"]: h for h in health if h.get("serial")}
    for d in disks:
        h = by_serial.get(d.get("serial", ""))
        if h:
            d["health_status"] = h["health_status"]
            if h["media_type"] in ("SSD", "HDD"):
                d["media_type"] = h["media_type"]

    failing = [s for s in smart if s["predict_failure"]]
    warnings = []
    for d in disks:
        if d.get("wmi_status") not in ("", "OK"):
            warnings.append(f"{d['model']}: WMI status '{d['wmi_status']}'")
        if d.get("health_status") not in ("", "Healthy", None):
            warnings.append(f"{d['model']}: health '{d['health_status']}'")
    for s in failing:
        warnings.append(f"SMART predicts failure: {s['instance']}")

    return {
        "physical_disks":   disks,
        "smart_status":     smart,
        "any_failure_predicted": bool(failing) or bool(warnings),
        "warnings":         warnings,
    }
