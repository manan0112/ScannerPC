"""
main.py — Windows Scanner Agent entry point.
Orchestrates all collectors and writes a single JSON report.

Usage:
    python main.py
    python main.py --output custom_report.json
    python main.py --skip software folders
"""

import argparse
import json
import os
import subprocess
import sys
import time
import traceback

from config import OUTPUT_FILE

# Exit codes — a JSON report on disk means the scan ran elevated and complete.
EXIT_OK             = 0
EXIT_WRITE_FAILED   = 1
EXIT_UAC_DENIED     = 2
EXIT_STILL_NO_ADMIN = 3

# ── Collector registry ────────────────────────────────────────────────────────
# Each entry: (section_key, module_path, callable_name)
# Lazy imports keep startup fast and allow selective skipping.
COLLECTORS = [
    ("system_info",      "collectors.system_info",      "collect"),
    ("win11_readiness",  "collectors.win11_readiness",  "collect"),
    ("software",         "collectors.software",         "collect"),
    ("processes",    "collectors.processes",    "collect"),
    ("disk_health",  "collectors.disk_health",  "collect"),
    ("startup",      "collectors.startup",      "collect"),
    ("security",     "collectors.security",     "collect"),
    ("network",      "collectors.network",      "collect"),
    ("onedrive",     "collectors.onedrive",     "collect"),
    ("junk",         "collectors.junk",         "collect"),
    ("user_folders", "collectors.user_folders", "collect"),
    ("folders",      "collectors.folders",      "collect"),
    ("large_files",  "collectors.files",        "collect"),
]


def _import_collector(module_path: str, fn_name: str):
    """Dynamically import a collector module and return its callable."""
    import importlib
    mod = importlib.import_module(module_path)
    return getattr(mod, fn_name)


def _run_collector(key: str, module_path: str, fn_name: str) -> tuple:
    """
    Run a single collector.
    Returns (key, result_or_error_dict, elapsed_seconds).
    """
    t0 = time.perf_counter()
    try:
        fn = _import_collector(module_path, fn_name)
        result = fn()
        elapsed = round(time.perf_counter() - t0, 3)
        print(f"  [OK]  {key:<14}  {elapsed:>6.3f}s")
        return key, result, elapsed
    except Exception:
        elapsed = round(time.perf_counter() - t0, 3)
        err = traceback.format_exc()
        print(f"  [ERR] {key:<14}  {elapsed:>6.3f}s\n{err}", file=sys.stderr)
        return key, {"error": err}, elapsed


def _enrich_large_files(report: dict) -> None:
    """Post-process: run metadata enrichment on large_files section."""
    raw = report.get("large_files")
    if not raw or isinstance(raw, dict) and "error" in raw:
        return
    try:
        from collectors.metadata import enrich
        report["large_files"] = enrich(raw)
    except Exception:
        print("[WARN] metadata enrichment failed:\n" +
              traceback.format_exc(), file=sys.stderr)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Windows Scanner Agent — produces a JSON inventory report."
    )
    p.add_argument(
        "--output", "-o",
        default=OUTPUT_FILE,
        help=f"Output JSON file path (default: {OUTPUT_FILE})"
    )
    p.add_argument(
        "--skip", "-s",
        nargs="*",
        default=[],
        metavar="SECTION",
        help="Collector sections to skip, e.g. --skip software folders"
    )
    p.add_argument(
        "--elevated-retry",
        action="store_true",
        help=argparse.SUPPRESS,  # internal: set on the UAC-relaunched child
    )
    return p.parse_args()


# ── Elevation (UAC) ───────────────────────────────────────────────────────────
# Scans from mixed admin/non-admin logins produced incomplete data (TPM,
# SMART, other-user profiles need admin). Policy: auto-elevate, and if that
# is denied write NOTHING and exit non-zero — a JSON on disk is trustworthy.

def _is_admin() -> bool:
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        pass
    try:
        # 'net session' succeeds only in an elevated console.
        r = subprocess.run(["net", "session"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=10)
        return r.returncode == 0
    except Exception:
        return False


def _relaunch_elevated(child_args: list):
    """
    Relaunch this program elevated via UAC, wait for it, and return its exit
    code. Returns None if the launch itself was denied/cancelled.
    """
    if getattr(sys, "frozen", False):
        exe = sys.executable
        params = subprocess.list2cmdline(child_args)
    else:
        exe = sys.executable
        params = subprocess.list2cmdline([os.path.abspath(sys.argv[0])] + child_args)

    try:
        import ctypes
        import ctypes.wintypes as wt

        class SHELLEXECUTEINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wt.DWORD),
                ("fMask", ctypes.c_ulong),
                ("hwnd", wt.HWND),
                ("lpVerb", wt.LPCWSTR),
                ("lpFile", wt.LPCWSTR),
                ("lpParameters", wt.LPCWSTR),
                ("lpDirectory", wt.LPCWSTR),
                ("nShow", ctypes.c_int),
                ("hInstApp", wt.HINSTANCE),
                ("lpIDList", ctypes.c_void_p),
                ("lpClass", wt.LPCWSTR),
                ("hkeyClass", wt.HKEY),
                ("dwHotKey", wt.DWORD),
                ("hIcon", wt.HANDLE),
                ("hProcess", wt.HANDLE),
            ]

        SEE_MASK_NOCLOSEPROCESS = 0x00000040
        info = SHELLEXECUTEINFO()
        info.cbSize = ctypes.sizeof(info)
        info.fMask = SEE_MASK_NOCLOSEPROCESS
        info.lpVerb = "runas"
        info.lpFile = exe
        info.lpParameters = params
        info.lpDirectory = os.getcwd()
        info.nShow = 1  # SW_SHOWNORMAL

        if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
            return None  # UAC cancelled or launch refused
        if not info.hProcess:
            return None
        ctypes.windll.kernel32.WaitForSingleObject(info.hProcess, 0xFFFFFFFF)
        code = wt.DWORD()
        ctypes.windll.kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(info.hProcess)
        return int(code.value)
    except Exception:
        pass

    # ctypes broken on this machine — elevate through PowerShell instead.
    try:
        ps = (
            "$p = Start-Process -FilePath '%s' -ArgumentList '%s' "
            "-Verb RunAs -Wait -PassThru; exit $p.ExitCode"
            % (exe.replace("'", "''"), params.replace("'", "''"))
        )
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            timeout=3600,
        )
        # Start-Process throws (exit 1 with no child) when UAC is refused;
        # we cannot tell that apart from a child exiting 1, so treat any
        # non-zero here as a failed scan either way.
        return r.returncode
    except Exception:
        return None


def _ensure_admin(args: argparse.Namespace, out_abs: str) -> None:
    """Guarantee we run elevated, or exit non-zero having written nothing."""
    if os.name != "nt" or _is_admin():
        return

    if args.elevated_retry:
        print("[FATAL] Relaunched process still lacks administrator rights. "
              "No report was written.", file=sys.stderr)
        sys.exit(EXIT_STILL_NO_ADMIN)

    child_args = ["--output", out_abs]
    if args.skip:
        child_args += ["--skip"] + list(args.skip)
    child_args.append("--elevated-retry")

    print("  Administrator rights required — requesting elevation (UAC)...")
    code = _relaunch_elevated(child_args)
    if code is None:
        print("[FATAL] Elevation was denied. No report was written.",
              file=sys.stderr)
        sys.exit(EXIT_UAC_DENIED)
    if code == EXIT_OK:
        print(f"  Elevated scan finished — report: {out_abs}")
    else:
        print(f"[FATAL] Elevated scan failed with exit code {code}.",
              file=sys.stderr)
    sys.exit(code)


def main() -> None:
    args = _parse_args()
    skip = {s.lower() for s in (args.skip or [])}

    # Resolve the output path against the exe/script directory, not the cwd —
    # a UAC-relaunched process starts in System32 and a relative path would
    # scatter reports there.
    out_abs = args.output
    if not os.path.isabs(out_abs):
        if getattr(sys, "frozen", False):
            base = os.path.dirname(sys.executable)
        else:
            base = os.path.dirname(os.path.abspath(__file__))
        out_abs = os.path.join(base, out_abs)

    print("=" * 52)
    print("  Windows Scanner Agent")
    print("=" * 52)

    _ensure_admin(args, out_abs)

    report: dict = {"_meta": {}}
    timings: dict = {}
    t_total = time.perf_counter()

    for key, module_path, fn_name in COLLECTORS:
        if key in skip:
            print(f"  [--]  {key:<14}  skipped")
            continue
        sec_key, result, elapsed = _run_collector(key, module_path, fn_name)
        report[sec_key] = result
        timings[sec_key] = elapsed

    if "large_files" not in skip:
        _enrich_large_files(report)

    total_elapsed = round(time.perf_counter() - t_total, 3)
    report["_meta"] = {
        "output_file": out_abs,
        "ran_as_admin": _is_admin() if os.name == "nt" else None,
        "total_elapsed_seconds": total_elapsed,
        "collector_timings": timings,
        "skipped_sections": list(skip),
    }

    # ── Write JSON ────────────────────────────────────────────────────────────
    out_path = out_abs
    try:
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, default=str, ensure_ascii=False)
        size_kb = round(os.path.getsize(out_path) / 1024, 1)
        print("=" * 52)
        print(f"  Report written : {out_path}")
        print(f"  File size      : {size_kb} KB")
        print(f"  Total time     : {total_elapsed}s")
        print("=" * 52)
    except OSError as exc:
        print(f"[FATAL] Could not write report: {exc}", file=sys.stderr)
        sys.exit(EXIT_WRITE_FAILED)


if __name__ == "__main__":
    main()