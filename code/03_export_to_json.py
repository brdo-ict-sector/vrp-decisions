"""
Export processed decisions from SQLite to decisions.json for the web app.

Usage:
    python 03_export_to_json.py
"""

import json
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "decisions.db"
DOCS_DIR = BASE_DIR / "docs"
OUTPUT_JSON = DOCS_DIR / "decisions.json"

DOCS_DIR.mkdir(parents=True, exist_ok=True)


def main():
    if not DB_PATH.exists():
        raise SystemExit(f"Database not found: {DB_PATH}\nRun 02_summarize_decisions.py first.")

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT filename, decision_essence, facts, key_conclusions, processed_at
               FROM decisions
               WHERE decision_essence IS NOT NULL
               ORDER BY filename"""
        ).fetchall()

    decisions = [dict(r) for r in rows]
    OUTPUT_JSON.write_text(json.dumps(decisions, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Exported {len(decisions)} decisions → {OUTPUT_JSON}")


if __name__ == "__main__":
    main()
