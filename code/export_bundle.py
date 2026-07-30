"""Export the extracted acts from data/decisions.db as JSON, next to the schemas
that shaped them. Not a pipeline stage — a one-off dump for taking the data off
this host. Re-runnable; overwrites data/export/ in place."""

import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "decisions.db"
OUT = ROOT / "data" / "export"

# table -> (json file, schema file in code/, Ukrainian act type)
TABLES = {
    "decisions": ("decisions.json", "extraction_schema.json", "Рішення Дисциплінарної палати"),
    "rulings": ("rulings.json", "ruling_schema.json", "Ухвала про відкриття дисциплінарної справи"),
    "reviews": ("reviews.json", "review_schema.json", "Рішення ВРП за скаргою на рішення ДП"),
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "schemas").mkdir(exist_ok=True)

    conn = sqlite3.connect(DB)
    manifest = {
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_db": str(DB),
        "tables": {},
    }

    for table, (json_name, schema_name, act_type) in TABLES.items():
        rows = conn.execute(
            f"SELECT filename, data, processed_at, error FROM {table} ORDER BY filename"
        ).fetchall()

        records, errors = [], []
        for filename, data, processed_at, error in rows:
            if error or not data:
                errors.append({"filename": filename, "error": error})
                continue
            records.append(
                {
                    "filename": filename,
                    "processed_at": processed_at,
                    "data": json.loads(data),
                }
            )

        (OUT / json_name).write_text(
            json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        shutil.copy(ROOT / "code" / schema_name, OUT / "schemas" / schema_name)

        manifest["tables"][table] = {
            "act_type": act_type,
            "json": json_name,
            "schema": f"schemas/{schema_name}",
            "records": len(records),
            "errors": len(errors),
            "error_rows": errors,
        }
        print(f"{table:10s} {len(records):4d} records -> {json_name}  (schema: {schema_name})")

    (OUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    conn.close()


if __name__ == "__main__":
    main()
