"""
Load hand-prepared structured extractions into the SQLite store, in the same
schema that 21_extract_decisions.py produces. This is a stopgap for when the
Claude API key is unavailable: an analyst (here, the model) drafts the records,
which an expert still verifies. Once a key is available, 03 can regenerate them.

Usage:
    python 23_load_manual_extractions.py [extractions.json]
"""

import json
import sqlite3
import sys
from pathlib import Path

from extraction_schema import STRUCTURE_KEYS

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "decisions.db"
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE_DIR / "data" / "reference" / "manual_extractions.json"


def init_db(conn: sqlite3.Connection) -> None:
    # Never drop the table: since the corpus became a growing daily feed it
    # holds records this file knows nothing about.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS decisions (
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
                "INSERT OR REPLACE INTO decisions (filename, data, processed_at, error) "
                "VALUES (?, ?, datetime('now'), NULL)",
                (filename, json.dumps(data, ensure_ascii=False)),
            )
        conn.commit()
    print(f"Loaded {len(records)} extractions into {DB_PATH}")


if __name__ == "__main__":
    main()
