"""
collectors/win11_readiness.py — Captures the data that actually gates a
Windows 11 upgrade and computes a per-machine verdict.

Collected:
  - TPM version + enabled/activated state   (root\\cimv2\\Security\\MicrosoftTpm → Win32_Tpm)
  - Secure Boot state                        (Confirm-SecureBootUEFI)
  - Firmware mode UEFI vs Legacy             ($env:firmware_type, ctypes fallback)
  - Boot-disk media type SSD vs HDD          (Get-Partition C → Get-PhysicalDisk MediaType)
  - GPU inventory                            (Win32_VideoController)
  - CPU support, RAM >= 4 GB, system disk >= 64 GB, 64-bit OS

Verdict:
  READY      — meets Windows 11 requirements as-is
  UPGRADE_HW — fixable gaps (enable TPM/Secure Boot in firmware, add RAM,
               swap HDD boot disk for SSD)
  REPLACE    — hard blockers that money is better not thrown at
               (no TPM 2.0, Legacy-only BIOS, unsupported CPU)

TPM and Secure Boot queries need elevation — main.py guarantees the scanner
runs as Administrator.
"""
import platform
import re

from collectors.util import ps_json, run_powershell, safe

try:
    import ctypes
except ImportError:          # broken _ctypes on damaged installs
    ctypes = None

_MIN_RAM_BYTES  = 4 * 1024 ** 3
_MIN_DISK_BYTES = 64 * 1024 ** 3

# Windows 11 CPU support floor: Intel 8th gen / AMD Ryzen 2000 (Zen+)
_INTEL_CORE_RE = re.compile(r"i[3579]-(\d{4,5})", re.IGNORECASE)
_INTEL_ULTRA_RE = re.compile(r"Core\s*\(?TM\)?\s*Ultra", re.IGNORECASE)
_RYZEN_RE = re.compile(r"Ryzen\s+[3579]\s+(?:PRO\s+)?(\d{4})", re.IGNORECASE)


def _tpm() -> dict:
    # Emit a marker string in the no-TPM and query-failed cases so a broken
    # query is never mistaken for "no TPM chip" (which would force REPLACE).
    rows = ps_json(
        "try { "
        "$t = Get-WmiObject -Namespace root\\cimv2\\Security\\MicrosoftTpm "
        "-Class Win32_Tpm -ErrorAction Stop; "
        "if ($t) { $t | Select-Object SpecVersion, IsEnabled_InitialValue, "
        "IsActivated_InitialValue, ManufacturerIdTxt, ManufacturerVersion "
        "| ConvertTo-Json -Compress } else { '\"NO_TPM\"' } "
        "} catch { '\"TPM_QUERY_FAILED\"' }"
    )
    if not rows or rows[0] == "TPM_QUERY_FAILED":
        return {"present": None, "spec_version": None, "enabled": None, "activated": None}
    if rows[0] == "NO_TPM":
        return {"present": False, "spec_version": None, "enabled": None, "activated": None}
    t = rows[0]
    if not isinstance(t, dict):
        return {"present": None, "spec_version": None, "enabled": None, "activated": None}
    # SpecVersion looks like "2.0, 0, 1.38" — first token is the TPM version
    spec_raw = str(t.get("SpecVersion") or "")
    spec = spec_raw.split(",")[0].strip() if spec_raw else None
    return {
        "present":      True,
        "spec_version": spec,
        "spec_raw":     spec_raw,
        "enabled":      t.get("IsEnabled_InitialValue"),
        "activated":    t.get("IsActivated_InitialValue"),
        "manufacturer": t.get("ManufacturerIdTxt") or "",
    }


def _secure_boot() -> str:
    """'enabled' | 'disabled' | 'unsupported' (Legacy BIOS or pre-Win8) | 'unknown'."""
    out = run_powershell(
        "try { if (Confirm-SecureBootUEFI) { 'enabled' } else { 'disabled' } } "
        "catch { 'unsupported' }"
    ).strip().lower()
    return out if out in ("enabled", "disabled", "unsupported") else "unknown"


def _firmware_mode(secure_boot: str) -> str:
    """'UEFI' | 'Legacy' | 'unknown'."""
    out = run_powershell("$env:firmware_type").strip().lower()
    if out.startswith("uefi"):
        return "UEFI"
    if out.startswith("legacy"):
        return "Legacy"
    # Secure Boot answering enabled/disabled proves UEFI boot.
    if secure_boot in ("enabled", "disabled"):
        return "UEFI"
    if ctypes is not None:
        try:
            # Dummy GUID probe: Legacy BIOS fails with ERROR_INVALID_FUNCTION (1);
            # UEFI fails with a different error (privilege/not-found).
            ctypes.windll.kernel32.SetLastError(0)
            ctypes.windll.kernel32.GetFirmwareEnvironmentVariableW(
                "", "{00000000-0000-0000-0000-000000000000}", None, 0
            )
            err = ctypes.windll.kernel32.GetLastError()
            return "Legacy" if err == 1 else "UEFI"
        except Exception:
            pass
    return "unknown"


def _boot_disk() -> dict:
    """Physical disk backing C: — media type decides the SSD-vs-HDD check."""
    rows = ps_json(
        "try { "
        "$part = Get-Partition -DriveLetter C -ErrorAction Stop; "
        "Get-PhysicalDisk -DeviceNumber $part.DiskNumber -ErrorAction Stop "
        "| Select-Object FriendlyName, MediaType, BusType, @{N='SizeBytes';E={$_.Size}} "
        "| ConvertTo-Json -Compress } catch {}"
    )
    if not rows:
        return {"media_type": "unknown"}
    d = rows[0]
    mt = d.get("MediaType")
    if isinstance(mt, int):
        mt = {3: "HDD", 4: "SSD", 5: "SCM"}.get(mt, str(mt))
    bt = d.get("BusType")
    if isinstance(bt, int):
        bt = {1: "SCSI", 3: "ATA", 7: "USB", 8: "RAID", 11: "SATA", 17: "NVMe"}.get(bt, str(bt))
    return {
        "model":      d.get("FriendlyName") or "",
        "media_type": mt or "unknown",
        "bus_type":   bt or "",
        "size_bytes": int(d.get("SizeBytes") or 0),
    }


def _gpus() -> list:
    rows = ps_json(
        "Get-WmiObject Win32_VideoController "
        "| Select-Object Name, AdapterRAM, DriverVersion, VideoModeDescription "
        "| ConvertTo-Json -Compress"
    )
    return [
        {
            "name":           g.get("Name") or "",
            "adapter_ram":    int(g.get("AdapterRAM") or 0),
            "driver_version": g.get("DriverVersion") or "",
            "video_mode":     g.get("VideoModeDescription") or "",
        }
        for g in rows
    ]


def _cpu_supported(cpu_name: str):
    """True / False / None (unknown) against the Windows 11 CPU floor."""
    if not cpu_name:
        return None
    if _INTEL_ULTRA_RE.search(cpu_name):
        return True
    m = _INTEL_CORE_RE.search(cpu_name)
    if m:
        model = int(m.group(1))
        if model < 2000:
            gen = 10           # 4-digit 1xxx = 10th-gen Ice Lake mobile
        elif model < 10000:
            gen = model // 1000  # 2400 → 2, 8400 → 8
        else:
            gen = int(str(model)[:2])
        return gen >= 8
    m = _RYZEN_RE.search(cpu_name)
    if m:
        return int(m.group(1)) >= 2000
    return None


def _system_memory_bytes() -> int:
    from collectors.system_info import _memory_info
    return int(_memory_info().get("total_bytes") or 0)


def _system_drive_bytes() -> int:
    from collectors.system_info import _disk_partitions
    for d in _disk_partitions():
        if str(d.get("drive", "")).upper().startswith("C"):
            return int(d.get("total_bytes") or 0)
    return 0


def collect() -> dict:
    errors = []

    tpm         = safe(_tpm, {"present": None}, errors, "tpm")
    secure_boot = safe(_secure_boot, "unknown", errors, "secure_boot")
    firmware    = safe(lambda: _firmware_mode(secure_boot), "unknown", errors, "firmware_mode")
    boot_disk   = safe(_boot_disk, {"media_type": "unknown"}, errors, "boot_disk")
    gpus        = safe(_gpus, [], errors, "gpus")
    ram_bytes   = safe(_system_memory_bytes, 0, errors, "memory")
    disk_bytes  = safe(_system_drive_bytes, 0, errors, "system_drive")

    cpu_name = ""
    try:
        from collectors.system_info import _cpu_info
        cpu_name = _cpu_info().get("name", "") or _cpu_info().get("processor", "")
    except Exception as exc:
        errors.append("cpu: %s" % exc)
    cpu_ok = _cpu_supported(cpu_name)

    os_release = platform.release()
    is_64bit = platform.machine().upper() in ("AMD64", "X86_64", "ARM64")
    already_11 = os_release == "11"

    # ── Verdict ───────────────────────────────────────────────────────────────
    replace, upgrade, unknowns = [], [], []

    if tpm.get("present") is False:
        replace.append("No TPM chip — motherboard cannot run Windows 11")
    elif tpm.get("present") and tpm.get("spec_version") not in (None, "2.0"):
        try:
            if float(tpm["spec_version"]) < 2.0:
                replace.append("TPM %s only — Windows 11 needs TPM 2.0" % tpm["spec_version"])
        except ValueError:
            unknowns.append("TPM spec version unreadable: %r" % tpm.get("spec_raw"))
    elif tpm.get("present") is None:
        unknowns.append("TPM state could not be read")
    elif tpm.get("enabled") is False:
        upgrade.append("TPM 2.0 present but disabled — enable it in firmware setup")

    if firmware == "Legacy":
        replace.append("Legacy BIOS boot — Windows 11 requires UEFI")
    elif firmware == "unknown":
        unknowns.append("Firmware mode could not be determined")

    if secure_boot == "disabled":
        upgrade.append("Secure Boot disabled — enable it in firmware setup")
    elif secure_boot == "unsupported" and firmware != "Legacy":
        unknowns.append("Secure Boot unsupported/unreadable")

    if cpu_ok is False:
        replace.append("CPU not on Windows 11 supported list: %s" % cpu_name)
    elif cpu_ok is None:
        unknowns.append("CPU support unknown: %s" % (cpu_name or "unreadable"))

    if not is_64bit:
        replace.append("Not a 64-bit system")

    if 0 < ram_bytes < _MIN_RAM_BYTES:
        upgrade.append("RAM %.1f GB < 4 GB minimum — add RAM" % (ram_bytes / 1024 ** 3))
    elif ram_bytes == 0:
        unknowns.append("RAM size could not be read")

    if 0 < disk_bytes < _MIN_DISK_BYTES:
        upgrade.append("System disk %.0f GB < 64 GB minimum" % (disk_bytes / 1024 ** 3))

    if boot_disk.get("media_type") == "HDD":
        upgrade.append("Boot disk is an HDD — swap to SSD (not gating, strongly recommended)")

    if already_11:
        verdict, reasons = "READY", ["Already running Windows 11"]
    elif replace:
        verdict, reasons = "REPLACE", replace + upgrade
    elif upgrade:
        verdict, reasons = "UPGRADE_HW", upgrade
    elif unknowns:
        # Nothing failed outright but gating facts are missing — do not claim READY.
        verdict, reasons = "UPGRADE_HW", ["Verify manually: " + "; ".join(unknowns)]
    else:
        verdict, reasons = "READY", ["All Windows 11 hardware requirements met"]

    result = {
        "tpm":                      tpm,
        "secure_boot":              secure_boot,
        "firmware_mode":            firmware,
        "boot_disk":                boot_disk,
        "gpus":                     gpus,
        "cpu_name":                 cpu_name,
        "cpu_supported":            cpu_ok,
        "os_64bit":                 is_64bit,
        "memory_total_bytes":       ram_bytes,
        "system_drive_total_bytes": disk_bytes,
        "already_windows_11":       already_11,
        "verdict":                  verdict,
        "verdict_reasons":          reasons,
        "unknowns":                 unknowns,
    }
    if errors:
        result["collection_errors"] = errors
    return result
