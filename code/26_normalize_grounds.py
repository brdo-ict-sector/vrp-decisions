"""
Fold ст.106 ground values back onto the canonical enum.

Structured outputs are supposed to make an off-enum value impossible, and almost
always do: 13 of 1 580 ground mentions in the corpus run came back differing from
the enum only by the case of the first letter («106-1а Незаконна…» for
«106-1а незаконна…»). A reader cannot see the difference; an exact-match facet
can, and would list the same ground twice.

This is a deterministic repair, not a re-extraction: the ground the model chose
is unambiguous, only its spelling drifted. Anything that does *not* fold onto an
enum member case-insensitively is left alone and reported — that would be a real
disagreement, and silently rewriting it would be the wrong call.

Usage:
    python 26_normalize_grounds.py [--db PATH] [--apply]      # dry-run by default
"""

import argparse
import json
import sqlite3
from pathlib import Path

from extraction_schema import ART106_GROUNDS

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "decisions.db"
TABLES = ("decisions", "rulings", "reviews")

# Canonical form keyed by a case- and whitespace-insensitive fingerprint.
CANONICAL = {" ".join(g.lower().split()): g for g in ART106_GROUNDS}


def fold(value: str):
    """Canonical enum member for `value`, or None if it is not one."""
    if value in ART106_GROUNDS:
        return value
    return CANONICAL.get(" ".join(str(value).lower().split()))


def normalize(node, changes: list, unresolved: list):
    """Rewrite every `grounds` list in place, recording what moved."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "grounds" and isinstance(value, list):
                for i, ground in enumerate(value):
                    if not isinstance(ground, str) or ground in ART106_GROUNDS:
                        continue
                    folded = fold(ground)
                    if folded:
                        changes.append((ground, folded))
                        value[i] = folded
                    else:
                        unresolved.append(ground)
            else:
                normalize(value, changes, unresolved)
    elif isinstance(node, list):
        for item in node:
            normalize(item, changes, unresolved)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=DB_PATH)
    ap.add_argument("--apply", action="store_true",
                    help="write the folded values back (default: report only)")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    total, touched_rows, unresolved = [], 0, []
    for table in TABLES:
        rows = list(conn.execute(
            f"SELECT filename, data FROM {table} WHERE data IS NOT NULL"))
        for filename, raw in rows:
            record = json.loads(raw)
            changes = []
            normalize(record, changes, unresolved)
            if not changes:
                continue
            touched_rows += 1
            total += changes
            print(f"  {table:10} {filename:20} {len(changes)} value(s)")
            if args.apply:
                conn.execute(f"UPDATE {table} SET data = ? WHERE filename = ?",
                             (json.dumps(record, ensure_ascii=False), filename))
    if args.apply:
        conn.commit()

    print(f"\n{len(total)} mention(s) across {touched_rows} row(s) "
          f"{'folded' if args.apply else 'would fold'} onto the enum")
    for before, after in sorted(set(total)):
        print(f"   {before!r}\n→  {after!r}")
    if unresolved:
        print(f"\n⚠ {len(unresolved)} value(s) are not enum members even "
              f"case-insensitively — left untouched, they need a look:")
        for value in sorted(set(unresolved)):
            print(f"   {value!r}")
    if not args.apply and total:
        print("\ndry run — re-run with --apply to write")
    conn.close()


if __name__ == "__main__":
    main()
