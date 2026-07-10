"""
analyser/main.py — Fleet analysis entry point.

Usage:
  python main.py --scans ../scans/          # folder of JSON files
  python main.py --scans ../scans/ --ai     # include Claude AI narrative
  python main.py --scans ../scans/ --output reports/

Reads all scan_report*.json files, runs all analysis modules,
and writes an Excel report + optional AI summary.
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Ensure local analysis + reports packages are importable
sys.path.insert(0, os.path.dirname(__file__))

from analysis.normalise      import normalise_scan
from analysis.hardware_score import rank_fleet
from analysis.cleanup_plan   import build_plan
from analysis.software_audit import fleet_software_summary
from analysis.onedrive_plan  import fleet_migration_summary
from reports.excel_report    import write_report


def _load_scans(scans_dir: str) -> list[dict]:
    """Load all JSON scan files from a directory."""
    p = Path(scans_dir)
    files = list(p.glob("*.json"))
    if not files:
        print(f"[ERROR] No JSON files found in: {scans_dir}")
        sys.exit(1)

    scans = []
    for f in files:
        try:
            with open(f, encoding="utf-8") as fh:
                scans.append(normalise_scan(json.load(fh)))
            print(f"  Loaded: {f.name}")
        except Exception as e:
            print(f"  [WARN] Could not load {f.name}: {e}")
    print(f"\n  {len(scans)} scan(s) loaded.\n")
    return scans


def _ai_narrative(fleet_summary: dict) -> str:
    """Call Claude API to generate an executive summary and action plan."""
    try:
        import anthropic
    except ImportError:
        return "[AI narrative skipped — install anthropic: pip install anthropic]"

    compact = {
        "machine_count":       fleet_summary["machine_count"],
        "hardware_top5":       fleet_summary["hardware_ranking"][:5],
        "total_junk_gb":       fleet_summary["total_junk_gb"],
        "onedrive_ready":      fleet_summary["onedrive"]["ready_for_onedrive"],
        "onedrive_total":      fleet_summary["onedrive"]["total_machines"],
        "high_sw_flags":       fleet_summary["total_high_sw_flags"],
    }

    client = anthropic.Anthropic()
    msg = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=1500,
        messages=[{
            "role": "user",
            "content": (
                "You are an IT consultant advising an Indian SME manufacturer of hydraulic gear pumps "
                "(25-30 PCs, 3 production units, departments: accounts, purchase, sales, production, store). "
                "The company is migrating to Microsoft Teams + OneDrive. "
                "Based on the fleet scan summary below, provide:\n"
                "1. Executive Summary (3 sentences)\n"
                "2. Top 5 Immediate Actions (this week)\n"
                "3. Hardware Upgrade Priority (top 5 machines with justification)\n"
                "4. OneDrive Migration Readiness + blockers\n"
                "5. Estimated productivity gain from cleanup\n\n"
                f"Fleet summary:\n{json.dumps(compact, indent=2)}"
            )
        }]
    )
    return msg.content[0].text


def main() -> None:
    parser = argparse.ArgumentParser(description="ScannerPC Fleet Analyser")
    parser.add_argument("--scans",  required=True, help="Directory containing scan JSON files")
    parser.add_argument("--output", default="reports", help="Output directory for reports")
    parser.add_argument("--ai",     action="store_true", help="Generate AI narrative via Claude API")
    args = parser.parse_args()

    os.makedirs(args.output, exist_ok=True)

    print("=" * 56)
    print("  ScannerPC Fleet Analyser")
    print("=" * 56)

    # ── Load scans ───────────────────────────────────────────────
    scans = _load_scans(args.scans)

    # ── Run analysis modules ─────────────────────────────────────
    print("Running hardware scoring...")
    hw_ranking = rank_fleet(scans)

    print("Building cleanup plans...")
    cleanup_plans = [build_plan(s) for s in scans]

    print("Running software audit...")
    sw_summary = fleet_software_summary(scans)

    print("Generating OneDrive migration plan...")
    od_summary = fleet_migration_summary(scans)

    # ── Build fleet summary ──────────────────────────────────────
    total_junk = sum(p["immediate_savings"] for p in cleanup_plans)
    fleet_summary = {
        "machine_count":        len(scans),
        "hardware_ranking":     hw_ranking,
        "total_junk_gb":        round(total_junk / (1024 ** 3), 2),
        "total_high_sw_flags":  sum(
            m["flag_counts"]["high"] for m in sw_summary["per_machine"]
        ),
        "onedrive":             od_summary,
        "generated_at":         datetime.utcnow().isoformat() + "Z",
    }

    # ── AI narrative (optional) ───────────────────────────────────
    if args.ai:
        print("Generating AI narrative (Claude API)...")
        narrative = _ai_narrative(fleet_summary)
        narrative_path = os.path.join(args.output, "ai_summary.txt")
        with open(narrative_path, "w", encoding="utf-8") as f:
            f.write(narrative)
        print(f"  AI summary written: {narrative_path}")

    # ── Write Excel report ────────────────────────────────────────
    date_str = datetime.now().strftime("%Y-%m-%d")
    excel_path = os.path.join(args.output, f"fleet_report_{date_str}.xlsx")
    write_report(hw_ranking, cleanup_plans, sw_summary, od_summary, excel_path)

    # ── Write full JSON summary ───────────────────────────────────
    json_path = os.path.join(args.output, f"fleet_summary_{date_str}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(fleet_summary, f, indent=2, default=str)
    print(f"Fleet JSON summary: {json_path}")

    # ── Console summary ───────────────────────────────────────────
    print("\n" + "=" * 56)
    print(f"  Machines scanned      : {len(scans)}")
    print(f"  Total junk removable  : {fleet_summary['total_junk_gb']} GB")
    print(f"  High software flags   : {fleet_summary['total_high_sw_flags']}")
    print(f"  OneDrive ready        : {od_summary['ready_for_onedrive']}/{od_summary['total_machines']}")
    print(f"\n  Upgrade priority (worst first):")
    for r in hw_ranking[:5]:
        print(f"    #{r['rank']:2}  {r['hostname']:<25}  score={r['score']}  {r['label']}")
    print("=" * 56)


if __name__ == "__main__":
    main()
