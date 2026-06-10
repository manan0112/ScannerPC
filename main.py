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
import sys
import time
import traceback

from config import OUTPUT_FILE

# ── Collector registry ────────────────────────────────────────────────────────
# Each entry: (section_key, module_path, callable_name)
# Lazy imports keep startup fast and allow selective skipping.
COLLECTORS = [
    ("system_info",  "collectors.system_info",  "collect"),
    ("software",     "collectors.software",     "collect"),
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
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    skip = {s.lower() for s in (args.skip or [])}

    print("=" * 52)
    print("  Windows Scanner Agent")
    print("=" * 52)

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
        "output_file": os.path.abspath(args.output),
        "total_elapsed_seconds": total_elapsed,
        "collector_timings": timings,
        "skipped_sections": list(skip),
    }

    # ── Write JSON ────────────────────────────────────────────────────────────
    out_path = args.output
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
        sys.exit(1)


if __name__ == "__main__":
    main()