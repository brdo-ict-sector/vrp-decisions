"""
Load hand-prepared structured extractions into the SQLite store, in the same
schema that 02_summarize_decisions.py produces. This is a stopgap for when the
Claude API key is unavailable: an analyst (here, the model) drafts the records,
which an expert still verifies. Once a key is available, 02 can regenerate them.

Usage:
    python 02b_load_manual_extractions.py [extractions.json]
"""

import json
import sqlite3
import sys
from pathlib import Path

from extraction_schema import STRUCTURE_KEYS

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "decisions.db"
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE_DIR / "data" / "round2" / "manual_extractions.json"


def init_db(conn: sqlite3.Connection) -> None:
    # round2 uses a structured-JSON schema; recreate the table to match it.
    conn.execute("DROP TABLE IF EXISTS decisions")
    conn.execute("""
        CREATE TABLE decisions (
            filename TEXT PRIMARY KEY,
            data TEXT,
            processed_at TEXT DEFAULT (datetime('now')),
            error TEXT
        )
    """)
    conn.commit()


def main():
    records = json.loads(SRC.read_text(encoding="utf-8"))
    with sqlite3.connect(DB_PATH) as conn:
        init_db(conn)
        for rec in records:
            filename = rec["filename"]
            data = {k: rec.get(k) for k in STRUCTURE_KEYS}
            conn.execute(
                "INSERT INTO decisions (filename, data, processed_at, error) "
                "VALUES (?, ?, datetime('now'), NULL)",
                (filename, json.dumps(data, ensure_ascii=False)),
            )
        conn.commit()
    print(f"Loaded {len(records)} extractions into {DB_PATH}")


if __name__ == "__main__":
    main()
