"""
collectors/processes.py — Snapshot of running processes, sorted by memory usage.
Answers: "what is eating the RAM on this machine right now?"
"""
import subprocess

from collectors.util import ps_json

# Cap the list so the report stays small — top consumers are what matter.
_TOP_N = 30


def _powershell_processes() -> list:
    try:
        raw = ps_json(
            "Get-Process | Sort-Object WorkingSet64 -Descending "
            f"| Select-Object -First {_TOP_N} "
            "Name, Id, WorkingSet64, "
            "@{N='CPUSeconds';E={[math]::Round($_.CPU,1)}}, "
            "@{N='Path';E={$_.Path}}, "
            "@{N='StartTime';E={if($_.StartTime){$_.StartTime.ToUniversalTime().ToString('o')}}} "
            "| ConvertTo-Json -Compress"
        )
        procs = []
        for p in raw:
            procs.append({
                "name":            p.get("Name", ""),
                "pid":             p.get("Id"),
                "memory_bytes":    p.get("WorkingSet64", 0),
                "cpu_seconds":     p.get("CPUSeconds"),
                "exe_path":        p.get("Path") or "",
                "start_time_utc":  p.get("StartTime") or "",
            })
        return procs
    except Exception:
        return []


def _tasklist_fallback() -> list:
    """Plain tasklist CSV — works even where PowerShell is restricted."""
    try:
        out = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True, timeout=30, text=True,
        )
        if out.returncode != 0:
            return []
        procs = []
        for line in out.stdout.splitlines():
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) < 5:
                continue
            # Mem Usage like "12,345 K"
            mem_str = parts[4].replace(",", "").replace("K", "").strip()
            try:
                mem_bytes = int(mem_str) * 1024
            except ValueError:
                mem_bytes = 0
            procs.append({
                "name":         parts[0],
                "pid":          int(parts[1]) if parts[1].isdigit() else None,
                "memory_bytes": mem_bytes,
                "cpu_seconds":  None,
                "exe_path":     "",
                "start_time_utc": "",
            })
        procs.sort(key=lambda x: x["memory_bytes"], reverse=True)
        return procs[:_TOP_N]
    except Exception:
        return []


def collect() -> dict:
    procs = _powershell_processes() or _tasklist_fallback()
    return {
        "top_by_memory": procs,
        "process_count": len(procs),
        "total_top_memory_bytes": sum(p["memory_bytes"] for p in procs),
    }
