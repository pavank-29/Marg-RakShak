"""MARG-RAKSHAK Database CLI Inspector.
Displays formatted ASCII/Unicode record tables directly in the terminal, matching console.table format.
Usage:
    py check_db.py             # View all tables
    py check_db.py users       # View users table
    py check_db.py hotspots    # View hotspots table
    py check_db.py accidents   # View accidents table
    py check_db.py history     # View navigation history
    py check_db.py risk_zones  # View danger risk zones
    py check_db.py predictions # View AI predictions
    py check_db.py --all       # Show full unfiltered rows for all tables
"""
import sys
import os
import sqlite3
from pathlib import Path

# Ensure UTF-8 output encoding for terminal box-drawing characters on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

def find_db_path() -> Path:
    candidates = [
        Path(__file__).resolve().parent / "BackEnd" / "margrakshak.db",
        Path(__file__).resolve().parent / "margrakshak.db",
        Path.cwd() / "BackEnd" / "margrakshak.db",
        Path.cwd() / "margrakshak.db",
    ]
    for p in candidates:
        if p.exists() and p.stat().st_size > 0:
            return p
    return candidates[0]

def format_cell(val, max_len: int = 30) -> str:
    if val is None:
        return "null"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, str):
        s = val.strip()
        if len(s) > max_len:
            s = s[:max_len - 3] + "..."
        return f"'{s}'"
    return str(val)

def print_console_table(title: str, rows: list, max_rows: int = None):
    if not rows:
        print(f"\n{title}: [Empty table - 0 records]")
        return

    display_rows = rows if (max_rows is None or len(rows) <= max_rows) else rows[:max_rows]
    cols = list(display_rows[0].keys())
    
    # Calculate column widths
    idx_header = "(index)"
    widths = {idx_header: max(len(idx_header), len(str(len(display_rows) - 1)))}
    for c in cols:
        w = len(c)
        for r in display_rows:
            cell_str = format_cell(r.get(c))
            if len(cell_str) > w:
                w = len(cell_str)
        widths[c] = w

    top_parts = ["─" * (widths[idx_header] + 2)] + ["─" * (widths[c] + 2) for c in cols]
    top_border = "┌" + "┬".join(top_parts) + "┐"
    
    header_parts = [f" {idx_header.ljust(widths[idx_header])} "] + [f" {c.ljust(widths[c])} " for c in cols]
    header = "│" + "│".join(header_parts) + "│"
    
    mid_parts = ["─" * (widths[idx_header] + 2)] + ["─" * (widths[c] + 2) for c in cols]
    mid_border = "├" + "┼".join(mid_parts) + "┤"
    
    row_lines = []
    for idx, r in enumerate(display_rows):
        idx_str = str(idx).ljust(widths[idx_header])
        r_parts = [f" {idx_str} "]
        for c in cols:
            val = r.get(c)
            cell_str = format_cell(val)
            if isinstance(val, (int, float)):
                r_parts.append(f" {cell_str.rjust(widths[c])} ")
            else:
                r_parts.append(f" {cell_str.ljust(widths[c])} ")
        row_lines.append("│" + "│".join(r_parts) + "│")
        
    bot_parts = ["─" * (widths[idx_header] + 2)] + ["─" * (widths[c] + 2) for c in cols]
    bot_border = "└" + "┴".join(bot_parts) + "┘"
    
    print(f"\n{title} ({len(rows)} records):")
    print(top_border)
    print(header)
    print(mid_border)
    for rl in row_lines:
        print(rl)
    print(bot_border)
    if max_rows and len(rows) > max_rows:
        print(f"... and {len(rows) - max_rows} more records ({len(rows)} total. Use --all to show all)")

def main():
    db_path = find_db_path()
    if not db_path.exists():
        print(f"Error: Database file not found at: {db_path}")
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    args = [a.lower().strip() for a in sys.argv[1:]]
    show_all = "--all" in args or "-a" in args
    table_filter = next((a for a in args if not a.startswith("-")), None)

    # 1. Users
    if not table_filter or table_filter in ("users", "user"):
        cur.execute("""
            SELECT id, email, full_name, role, mobile, preferred_language as lang, is_active as active, is_superuser as admin 
            FROM users 
            ORDER BY id ASC
        """)
        users = [dict(r) for r in cur.fetchall()]
        print_console_table("Users Table (`users`)", users, max_rows=None)

    # 2. Hotspots
    if not table_filter or table_filter in ("hotspots", "hotspot", "blackspots", "blackspot"):
        cur.execute("""
            SELECT id, name, latitude as lat, longitude as lng, risk_level as level, risk_score as score, density, accident_count as accidents, fatalities, source 
            FROM hotspots 
            ORDER BY id ASC
        """)
        hotspots = [dict(r) for r in cur.fetchall()]
        limit = None if (show_all or table_filter) else 15
        print_console_table("Hotspots & Blackspots Table (`hotspots`)", hotspots, max_rows=limit)

    # 3. Accidents
    if not table_filter or table_filter in ("accidents", "accident"):
        cur.execute("""
            SELECT id, location_name as location, latitude as lat, longitude as lng, severity, accident_type as type, fatalities, injuries, vehicles_involved as vehicles, substr(accident_date, 1, 19) as date 
            FROM accidents 
            ORDER BY id ASC
        """)
        accidents = [dict(r) for r in cur.fetchall()]
        limit = None if (show_all or table_filter) else 15
        print_console_table("Accident Incident Records (`accidents`)", accidents, max_rows=limit)

    # 4. Navigation History
    if not table_filter or table_filter in ("history", "navigation", "navigation_history", "trips"):
        cur.execute("""
            SELECT id, user_id as uid, source_name as source, destination_name as destination, selected_route as route, distance_km as distance, duration_min as duration, hotspots_count as hotspots, risk_level as risk, status 
            FROM navigation_history 
            ORDER BY id ASC
        """)
        trips = [dict(r) for r in cur.fetchall()]
        print_console_table("Navigation & Trip History (`navigation_history`)", trips, max_rows=None)

    # 5. Risk Zones
    if not table_filter or table_filter in ("risk_zones", "risk_zone", "zones"):
        cur.execute("""
            SELECT id, name, zone_type as type, center_lat as lat, center_lng as lng, risk_level as level, risk_score as score, speed_limit_kmh as speed_limit, is_active as active 
            FROM risk_zones 
            ORDER BY id ASC
        """)
        zones = [dict(r) for r in cur.fetchall()]
        print_console_table("Danger Corridors & Polygons (`risk_zones`)", zones, max_rows=None)

    # 6. Predictions
    if not table_filter or table_filter in ("predictions", "prediction", "ml"):
        cur.execute("""
            SELECT id, model_name as model, algorithm, latitude as lat, longitude as lng, predicted_risk_level as pred_level, predicted_risk_score as score, confidence_score as confidence 
            FROM predictions 
            ORDER BY id DESC
            LIMIT 10
        """)
        preds = [dict(r) for r in cur.fetchall()]
        print_console_table("AI Risk Predictions (`predictions`)", preds, max_rows=None)

    conn.close()

if __name__ == "__main__":
    main()
