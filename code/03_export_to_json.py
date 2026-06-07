"""
Export structured decisions from SQLite to docs/decisions.json for the web app,
joining the public source URL from the web-links spreadsheet.

The spreadsheet maps a decision number (e.g. "983/1дп/15-25") to its ВРП URL.
We join on the leading number, which matches each file's name prefix (983_...).

Usage:
    python 03_export_to_json.py
"""

import json
import sqlite3
from pathlib import Path

import openpyxl

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "decisions.db"
LINKS_XLSX = BASE_DIR / "data" / "round2" / "decisions to web-links.xlsx"
DOCS_DIR = BASE_DIR / "docs"
OUTPUT_JSON = DOCS_DIR / "decisions.json"


def load_links() -> dict[str, dict]:
    """Map leading decision number -> {decision_num, url}."""
    links: dict[str, dict] = {}
    if not LINKS_XLSX.exists():
        print(f"WARN: links file not found: {LINKS_XLSX}")
        return links
    wb = openpyxl.load_workbook(LINKS_XLSX, read_only=True)
    ws = wb.active
    for num, url in list(ws.iter_rows(values_only=True))[1:]:
        if not num:
            continue
        lead = str(num).split("/", 1)[0].strip()
        links[lead] = {"decision_num": str(num).strip(), "url": str(url).strip() if url else None}
    return links


def main():
    if not DB_PATH.exists():
        raise SystemExit(f"Database not found: {DB_PATH}\nRun 02_summarize_decisions.py first.")

    links = load_links()

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT filename, data, processed_at FROM decisions "
            "WHERE data IS NOT NULL ORDER BY filename"
        ).fetchall()

    def stage_grounds(qual: dict, stage: str) -> list:
        s = (qual or {}).get(stage)
        return (s or {}).get("grounds", []) if isinstance(s, dict) else []

    decisions = []
    for r in rows:
        data = json.loads(r["data"])
        filename = r["filename"]
        lead = filename.split("_", 1)[0]
        link = links.get(lead, {})
        # Date from the decision, falling back to the filename suffix (983_12.05.2025).
        date = data.get("date") or (filename.split("_", 1)[1] if "_" in filename else None)

        qual = data.get("qualification") or {}
        # Flat ground list for the facet filter: the chamber's qualification
        # (ВРП on review if present, else ДП, else the complaint).
        grounds = (stage_grounds(qual, "vrp") or stage_grounds(qual, "dp")
                   or stage_grounds(qual, "complaint"))

        decisions.append({
            "filename": filename,
            "date": date,
            "decision_num": data.get("decision_num") or link.get("decision_num"),
            "short_name": data.get("short_name"),
            "url": link.get("url"),
            "judge_name": data.get("judge_name"),
            "court": data.get("court"),
            "chamber": data.get("chamber"),
            "art106_grounds": grounds,
            "qualification": qual,
            "conduct": data.get("conduct") or {},
            "sanction": data.get("sanction") or {},
            "summary": data.get("summary") or {},
            "processed_at": r["processed_at"],
        })

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(decisions, ensure_ascii=False, indent=2), encoding="utf-8")
    linked = sum(1 for d in decisions if d["url"])
    print(f"Exported {len(decisions)} decisions ({linked} with source links) → {OUTPUT_JSON}")


if __name__ == "__main__":
    main()
