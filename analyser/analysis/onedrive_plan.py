"""
analysis/onedrive_plan.py — OneDrive migration plan and recommended folder structure.

Produces:
  1. Per-machine migration readiness assessment
  2. Recommended OneDrive folder structure for the organisation
  3. File routing rules (what goes where)
"""

_GB = 1024 ** 3
_MB = 1024 ** 2


# ── Recommended OneDrive folder structure ────────────────────────────────────
# Tailored for an Indian hydraulic gear pump manufacturer with 3 units
ONEDRIVE_STRUCTURE = {
    "01_Accounts": {
        "description": "Finance and accounting documents",
        "sub": [
            "Sales_Invoices/YYYY-MM",
            "Purchase_Invoices/YYYY-MM",
            "GST_Returns/YYYY-MM",
            "Bank_Statements/YYYY-MM",
            "Audit_Reports",
            "Tally_Backups",          # .900 backup exports from Tally
        ]
    },
    "02_Purchase": {
        "description": "Procurement documents",
        "sub": [
            "Purchase_Orders",
            "Vendor_Quotations",
            "Vendor_Master",
            "GRN_Records",
        ]
    },
    "03_Sales": {
        "description": "Sales and customer documents",
        "sub": [
            "Quotations",
            "Sales_Orders",
            "Dispatch_Records",
            "Customer_Master",
        ]
    },
    "04_Production": {
        "description": "Manufacturing — all 3 units",
        "sub": [
            "Unit_1_JobCards",
            "Unit_2_JobCards",
            "Unit_3_JobCards",
            "Drawings_and_Specs",
            "Quality_Records",
            "Production_Reports/YYYY-MM",
        ]
    },
    "05_Store": {
        "description": "Inventory and store records",
        "sub": [
            "Stock_Registers",
            "GRN",
            "Issue_Records",
            "Vendor_Packing_Slips",
        ]
    },
    "06_HR_Admin": {
        "description": "HR and administration",
        "sub": [
            "Employee_Records",
            "Attendance",
            "Salary_Sheets",
            "Compliance",
        ]
    },
    "07_Common": {
        "description": "Shared reference documents",
        "sub": [
            "Company_Letterheads",
            "SOPs",
            "Price_Lists",
            "Certificates",
            "ISO_Documents",
        ]
    },
}

# ── Pen drive archive structure ───────────────────────────────────────────────
# For offline backup of essential files per machine during migration
PENDRIVE_STRUCTURE = {
    "[PC-Name]_Archive_[YYYY-MM-DD]": {
        "description": "One folder per PC during migration",
        "sub": [
            "Desktop_Files",
            "My_Documents",
            "Tally_Data",        # if applicable
            "Accounting_Files",
            "Old_Backups",       # items user wants to keep but not sync
        ]
    },
    "Software_Installers": {
        "description": "Offline installers in case of reinstall",
        "sub": [
            "Tally",
            "Office",
            "Antivirus",
            "Other",
        ]
    },
    "Company_Data_Master": {
        "description": "Master copy of critical non-cloud data",
        "sub": [
            "Tally_Company_Data",
            "ERP_Exports",
        ]
    },
}

# ── File routing rules ────────────────────────────────────────────────────────
FILE_ROUTING = [
    {
        "extensions":   [".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt", ".pdf", ".csv", ".txt"],
        "destination":  "OneDrive",
        "onedrive_path": "by department folder",
        "rationale":    "All work documents should be in OneDrive for sharing and backup",
    },
    {
        "extensions":   [".900", ".tdb", ".tdl"],
        "destination":  "Keep local + pen drive backup",
        "onedrive_path": "01_Accounts/Tally_Backups",
        "rationale":    "Tally data should stay local for Tally to access; back up exports to OneDrive",
    },
    {
        "extensions":   [".jpg", ".jpeg", ".png", ".bmp", ".tif"],
        "destination":  "OneDrive if work-related, delete if personal",
        "onedrive_path": "relevant department folder",
        "rationale":    "Product photos, drawings go to OneDrive; personal photos delete",
    },
    {
        "extensions":   [".mp4", ".avi", ".mkv", ".mov", ".wmv"],
        "destination":  "Review and delete",
        "onedrive_path": None,
        "rationale":    "Videos consume large space; training videos only — move to NAS if needed",
    },
    {
        "extensions":   [".zip", ".rar", ".7z"],
        "destination":  "Review — extract if work files inside, delete archive",
        "onedrive_path": None,
        "rationale":    "Archives often contain documents that should be extracted and organised",
    },
    {
        "extensions":   [".exe", ".msi"],
        "destination":  "Pen drive / NAS software store",
        "onedrive_path": None,
        "rationale":    "Keep one copy of required installers offline; no need on every PC",
    },
]


def assess_machine(scan: dict) -> dict:
    """Return OneDrive migration readiness for a single machine."""
    od      = scan.get("onedrive", {})
    uf      = scan.get("user_folders", {})
    si      = scan.get("system_info", {})
    os_rel  = si.get("os", {}).get("release", "")

    issues = []

    if os_rel == "7":
        issues.append("Windows 7 does not support modern OneDrive client — upgrade OS first")

    client_ok = od.get("client_installed", False)
    teams_ok  = od.get("teams_installed",  False)
    biz_acct  = bool(od.get("business_account", {}).get("useremail"))

    if not client_ok:
        issues.append("OneDrive client not installed — install before migration")
    elif not biz_acct:
        issues.append("OneDrive not signed in to a business account")

    # Estimate how much should move to OneDrive
    move_bytes = 0
    for name, data in uf.items():
        types = data.get("by_type_bytes", {})
        move_bytes += types.get("office_docs", 0)

    return {
        "hostname":         si.get("hostname", "unknown"),
        "onedrive_ready":   client_ok and biz_acct,
        "teams_ready":      teams_ok,
        "signed_in_email":  od.get("business_account", {}).get("useremail", ""),
        "estimated_move_gb": round(move_bytes / _GB, 2),
        "issues":           issues,
    }


def fleet_migration_summary(scans: list[dict]) -> dict:
    """Aggregate migration readiness across the whole fleet."""
    assessments = [assess_machine(s) for s in scans]
    ready_count = sum(1 for a in assessments if a["onedrive_ready"])
    total_move  = sum(a["estimated_move_gb"] for a in assessments)

    return {
        "total_machines":    len(scans),
        "ready_for_onedrive": ready_count,
        "not_ready":         len(scans) - ready_count,
        "estimated_total_move_gb": round(total_move, 2),
        "per_machine":       assessments,
        "recommended_structure": ONEDRIVE_STRUCTURE,
        "pendrive_structure":    PENDRIVE_STRUCTURE,
        "file_routing_rules":    FILE_ROUTING,
    }
