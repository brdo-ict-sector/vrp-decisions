"""Compare two models' extractions of the same acts, field by field.

The question this answers is not "are the two outputs identical" — they never
will be, because three of the fields are free prose. It is: **would an expert
verifying the cheaper model's output have to correct more of it?**

So the fields are judged separately, by what a disagreement would mean:

  - **Structured fields** (complaint number, ст. 106 grounds, sanction type,
    outcome, review outcome) come from fixed enums or from a rule-supplied
    candidate list. A disagreement here is a substantive one: exactly one of the
    two models is wrong about what the act says, and the error is the kind that
    reaches the site as a wrong fact. These are reported as exact-match rates.
  - **Identity fields** (judge names, courts) are compared as sets, since order
    carries no meaning. A missing judge is much worse than a differently spelled
    one, so the count is reported apart from the names.
  - **Prose fields** (фабула, суть, висновки) cannot be scored by string equality
    and are not pretended to be. Only their presence and length are reported —
    a model that returns a two-word «суть» is failing visibly, and anything finer
    needs a human to read it.

Usage:
    python compare_models.py BASELINE_DB CANDIDATE_DB
"""

import argparse
import json
import sqlite3
from pathlib import Path

TABLES = ("decisions", "rulings", "reviews")


def load(db: Path, table: str) -> dict[str, dict]:
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
            f"SELECT filename, data FROM {table} WHERE data IS NOT NULL"
        ).fetchall()
    except sqlite3.OperationalError:          # table absent in this database
        return {}
    finally:
        conn.close()
    return {f: json.loads(d) for f, d in rows}


def judges(rec: dict) -> list[dict]:
    return rec.get("judges") or []


def is_legacy(rec: dict) -> bool:
    """Was this record written before the per-judge schema?

    Older rows carry `judge_name` and the grounds flat at the top level instead of
    a `judges[]` array. Compared against a current-schema record they look like a
    model that found no judges at all, which is an artefact of when the row was
    written and says nothing about the model that wrote it. Scoring them would
    have credited the candidate model with 15 phantom wins.
    """
    return "judges" not in rec and bool(rec.get("judge_name"))


def ground_set(node) -> frozenset:
    """The ст. 106 grounds inside a {grounds, note} node, as a set."""
    if not isinstance(node, dict):
        return frozenset()
    return frozenset(node.get("grounds") or [])


def structured_fields(table: str, rec: dict) -> dict:
    """The fields where a disagreement means one model is factually wrong."""
    out = {
        "complaint_number": rec.get("complaint_number"),
        "date": rec.get("date"),
        "judge_count": len(judges(rec)),
    }
    if table == "reviews":
        out["reviewed_decision_num"] = rec.get("reviewed_decision_num")
        out["appellant_type"] = rec.get("appellant_type")
    if table == "rulings":
        out["complainant_type"] = rec.get("complainant_type")
        out["inspector_proposal"] = rec.get("inspector_proposal")

    # Per judge, keyed by surname so the comparison survives a reordered array.
    for j in judges(rec):
        key = (j.get("name") or "?").split()[0]
        if table == "rulings":
            g = j.get("grounds") or {}
            out[f"{key}:grounds.requested"] = ground_set(g.get("requested"))
            out[f"{key}:grounds.opened"] = ground_set(g.get("opened"))
            out[f"{key}:grounds.rejected"] = ground_set(g.get("rejected"))
            out[f"{key}:outcome"] = j.get("outcome")
        elif table == "decisions":
            q = j.get("qualification") or {}
            out[f"{key}:qual.complaint"] = ground_set(q.get("complaint"))
            out[f"{key}:qual.dp"] = ground_set(q.get("dp"))
            out[f"{key}:sanction_type"] = j.get("sanction_type")
            out[f"{key}:outcome"] = j.get("outcome")
        else:
            out[f"{key}:review_outcome"] = j.get("review_outcome")
            out[f"{key}:sanction_type"] = j.get("sanction_type")
            out[f"{key}:qualification"] = ground_set(j.get("qualification"))
    return out


PROSE = {
    "decisions": [("summary", "facts"), ("summary", "essence"), ("summary", "conclusions")],
    "rulings": [("summary", "facts"), ("summary", "essence")],
    "reviews": [("summary", "facts"), ("summary", "essence")],
}


def prose_len(rec: dict, path: tuple) -> int:
    node = rec
    for k in path:
        node = (node or {}).get(k)
    if isinstance(node, list):
        return sum(len(str(x)) for x in node)
    return len(str(node)) if node else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("baseline_db", type=Path)
    ap.add_argument("candidate_db", type=Path)
    ap.add_argument("--show", type=int, default=25, help="how many disagreements to print")
    args = ap.parse_args()

    agree = disagree = 0
    diffs, name_notes, prose_rows, skipped = [], [], [], []

    for table in TABLES:
        base, cand = load(args.baseline_db, table), load(args.candidate_db, table)
        shared = sorted(set(base) & set(cand))
        legacy = [f for f in shared if is_legacy(base[f]) or is_legacy(cand[f])]
        shared = [f for f in shared if f not in set(legacy)]
        if not shared and not legacy:
            continue
        print(f"\n{'='*72}\n{table}: {len(shared)} acts compared"
              + (f"  ({len(legacy)} excluded — baseline predates the per-judge "
                 f"schema: {', '.join(legacy)})" if legacy else ""))
        skipped.extend(legacy)

        for f in shared:
            b, c = structured_fields(table, base[f]), structured_fields(table, cand[f])
            for key in sorted(set(b) | set(c)):
                bv, cv = b.get(key, "<absent>"), c.get(key, "<absent>")
                if bv == cv:
                    agree += 1
                else:
                    disagree += 1
                    diffs.append((table, f, key, bv, cv))

            bn = {(j.get("name") or "").strip() for j in judges(base[f])}
            cn = {(j.get("name") or "").strip() for j in judges(cand[f])}
            if bn != cn:
                name_notes.append((f, sorted(bn - cn), sorted(cn - bn)))

            for path in PROSE[table]:
                prose_rows.append((table, ".".join(path),
                                   prose_len(base[f], path), prose_len(cand[f], path)))

    total = agree + disagree
    print(f"\n{'='*72}\nSTRUCTURED FIELDS: {agree}/{total} agree "
          f"({agree/total*100:.1f}%), {disagree} disagree")

    if diffs:
        print(f"\nDisagreements (baseline → candidate), first {args.show}:")
        for table, f, key, bv, cv in diffs[:args.show]:
            fmt = lambda v: sorted(v) if isinstance(v, frozenset) else v
            print(f"  [{table}] {f}  {key}")
            print(f"      opus:   {fmt(bv)}")
            print(f"      sonnet: {fmt(cv)}")

    print(f"\nJUDGE IDENTITY: {len(name_notes)} acts where the named judges differ")
    for f, only_b, only_c in name_notes:
        print(f"  {f}: only-opus={only_b}  only-sonnet={only_c}")

    print("\nPROSE FIELDS (mean chars; equality is not expected, emptiness is a failure)")
    seen = {}
    for table, field, bl, cl in prose_rows:
        s = seen.setdefault((table, field), [0, 0, 0, 0, 0])
        s[0] += bl; s[1] += cl; s[2] += 1
        s[3] += (bl == 0); s[4] += (cl == 0)
    for (table, field), (bl, cl, n, be, ce) in sorted(seen.items()):
        print(f"  {table:10} {field:18} opus {bl//n:>6}  sonnet {cl//n:>6}"
              f"   empty: opus {be}, sonnet {ce}")


if __name__ == "__main__":
    main()
