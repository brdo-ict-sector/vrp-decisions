"""The loop every extraction stage runs: dispatch, record, account.

Stages 21, 22 and 24 differ only in which acts they select, which schema they
enforce, and which table they write. Everything around that was copied three
times — the skip-if-done check, the try/except, the SQLite upsert, the progress
line. This module owns it once, which is why parallelism and usage accounting
could be added in one place rather than three.

**Concurrency.** Extraction is I/O-bound — almost the whole wall-clock is spent
waiting on the API — so worker threads help and processes would not. `--workers`
threads call the API; **only the main thread touches SQLite**. That is deliberate:
SQLite tolerates concurrent readers but serialises writers, and a pool of writing
threads trades a clean loop for `database is locked` retries. Results come back
through `as_completed()` and are written as they land, so a run can be
interrupted at any point without losing what already finished.

**Usage accounting.** Every row records the tokens it cost and the model that
produced it. Before this, a corpus run left an invoice and no way to attribute
it — no per-stage breakdown, no way to check an estimate, and (worse) no record
of *which model* wrote a row, which is exactly the provenance gap that made
mixing Opus and Sonnet output dangerous. `usage` is a JSON blob rather than
columns so a new field in the API response does not need a migration.

**Ordering.** Files arrive newest-first (see `register.py`) and are submitted in
that order, so an interrupted run still leaves the recent end covered. Completion
order is not submission order, so each progress line carries its own index.
"""

import json
import sqlite3
import sys
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

# Priced per million tokens (input, output). Used for the end-of-run summary and
# for the `--budget` ceiling — the invoice is authoritative, this is what we
# steer by. Sonnet 5 is at introductory pricing ($2/$10) through 2026-08-31;
# list is $3/$15, so a run that straddles that date costs 1.5× this estimate.
PRICES = {
    "claude-sonnet-5": (2.00, 10.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-haiku-4-5": (1.00, 5.00),
}


def cost_of(totals: dict, model: str) -> float:
    """Dollar cost of `{"in": n, "out": n}` at list prices for `model` (0 if unpriced)."""
    price = PRICES.get(model)
    if not price:
        return 0.0
    return totals["in"] / 1e6 * price[0] + totals["out"] / 1e6 * price[1]


def spent_so_far(db_path, model: str) -> float:
    """What the database says has already been spent, at `model` prices.

    The budget ceiling has to survive a restart: a run stopped at $45 and resumed
    must not spend $45 again. Every extracted row carries its own token counts, so
    the ledger is the database rather than anything this process remembers.
    """
    agg = {"in": 0, "out": 0}
    for table in totals_for(db_path).values():
        agg["in"] += table["input_tokens"]
        agg["out"] += table["output_tokens"]
    return cost_of(agg, model)


def ensure_schema(conn: sqlite3.Connection, table: str) -> None:
    """Create the table if absent and add the `usage` column to older databases."""
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {table} (
            filename TEXT PRIMARY KEY,
            data TEXT,
            processed_at TEXT DEFAULT (datetime('now')),
            error TEXT
        )
    """)
    have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    if "usage" not in have:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN usage TEXT")
    conn.commit()


def usage_row(message, model: str) -> dict:
    """The billable shape of one API call, as stored."""
    u = message.usage
    return {
        "model": model,
        "input_tokens": getattr(u, "input_tokens", 0) or 0,
        "output_tokens": getattr(u, "output_tokens", 0) or 0,
        "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
    }


def _pending(conn: sqlite3.Connection, table: str, md_files, limit):
    """Files still needing extraction, newest first, capped by `limit`."""
    done = {r[0] for r in conn.execute(
        f"SELECT filename FROM {table} WHERE data IS NOT NULL")}
    todo = [p for p in md_files if p.stem not in done]
    skipped = len(md_files) - len(todo)
    return (todo[:limit] if limit else todo), skipped


def run(md_files, table, extract_fn, model, db_path, limit=None, workers=1,
        label="acts", precheck=None, budget=None) -> int:
    """Extract `md_files` into `table`, `workers` calls at a time.

    `extract_fn(md_path)` returns `(record, message)` — the parsed record and the
    raw API message, whose usage is recorded alongside it. `precheck(md_path)`
    may return a reason string to skip an act *before* spending a call.
    `budget` is a dollar ceiling on the **whole database**, not on this run:
    submission stops as soon as recorded spend reaches it, so a corpus run
    against a fixed pot of credit stops itself instead of failing on a 400.
    Returns the number of records written.
    """
    conn = sqlite3.connect(db_path)
    ensure_schema(conn, table)
    todo, already = _pending(conn, table, md_files, limit)

    print(f"{len(md_files)} {label} selected; {already} already extracted; "
          f"{len(todo)} to do, {workers} at a time")
    if budget:
        prior = spent_so_far(db_path, model)
        print(f"budget: ${budget:.2f} across {Path(db_path).name}; "
              f"${prior:.2f} already spent, ${max(0.0, budget - prior):.2f} left")
        if prior >= budget:
            print("budget already exhausted — nothing submitted")
            conn.close()
            return 0
    if not todo:
        conn.close()
        return 0

    lock = threading.Lock()          # guards stdout only; SQLite stays single-threaded
    totals = {"in": 0, "out": 0, "cache_write": 0, "cache_read": 0}
    done = failed = skipped = 0
    prior_cost = spent_so_far(db_path, model) if budget else 0.0
    halted = False

    def work(md_path):
        reason = precheck(md_path) if precheck else None
        if reason:
            return md_path, None, None, reason
        record, message = extract_fn(md_path)
        return md_path, record, message, None

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            queue = iter(list(enumerate(todo, 1)))
            inflight = {}
            # Submit only `workers` acts at a time rather than all of them up
            # front: the budget can only be enforced at a submission boundary,
            # and a queue of 400 already-submitted calls has no such boundary.
            while True:
                while not halted and len(inflight) < workers:
                    nxt = next(queue, None)
                    if nxt is None:
                        break
                    n, md_path = nxt
                    inflight[pool.submit(work, md_path)] = (n, md_path)
                if not inflight:
                    break
                finished, _ = wait(inflight, return_when=FIRST_COMPLETED)
                for fut in finished:
                    n, md_path = inflight.pop(fut)
                    stem = md_path.stem
                    try:
                        _, record, message, reason = fut.result()
                    except Exception as e:                  # noqa: BLE001 — recorded, not raised
                        failed += 1
                        conn.execute(
                            f"INSERT INTO {table} (filename, error) VALUES (?, ?) "
                            f"ON CONFLICT(filename) DO UPDATE SET error=excluded.error",
                            (stem, str(e)))
                        conn.commit()
                        with lock:
                            print(f"[{n}/{len(todo)}] {stem} ERROR: {e}", flush=True)
                        continue

                    if reason:
                        skipped += 1
                        with lock:
                            print(f"[{n}/{len(todo)}] {stem} skipped ({reason})", flush=True)
                        continue

                    u = usage_row(message, model)
                    for k, key in (("in", "input_tokens"), ("out", "output_tokens"),
                                   ("cache_write", "cache_creation_input_tokens"),
                                   ("cache_read", "cache_read_input_tokens")):
                        totals[k] += u[key]
                    conn.execute(
                        f"""INSERT INTO {table} (filename, data, processed_at, error, usage)
                            VALUES (?, ?, datetime('now'), NULL, ?)
                            ON CONFLICT(filename) DO UPDATE SET
                                data=excluded.data, processed_at=datetime('now'),
                                error=NULL, usage=excluded.usage""",
                        (stem, json.dumps(record, ensure_ascii=False),
                         json.dumps(u, ensure_ascii=False)))
                    conn.commit()
                    done += 1
                    with lock:
                        print(f"[{n}/{len(todo)}] {stem} done "
                              f"({u['input_tokens']:,} in / {u['output_tokens']:,} out)",
                              flush=True)

                if budget and not halted:
                    running = prior_cost + cost_of(totals, model)
                    if running >= budget:
                        halted = True
                        print(f"\n⛔ budget reached: ~${running:.2f} of ${budget:.2f} — "
                              f"no further acts submitted; finishing {len(inflight)} in flight",
                              flush=True)
    except KeyboardInterrupt:
        # Everything already written is committed; say so rather than implying loss.
        print(f"\nInterrupted — {done} записів збережено.", file=sys.stderr)

    summary(model, totals, done, failed, skipped, db_path)
    if halted:
        print("  stopped by --budget; re-run with a higher ceiling to continue")
    conn.close()
    return done


def summary(model, totals, done, failed, skipped, db_path) -> None:
    print(f"\n  written: {done}   failed: {failed}   skipped: {skipped}")
    print(f"  tokens : {totals['in']:,} in  ·  {totals['out']:,} out"
          + (f"  ·  {totals['cache_write']:,} cache-write" if totals["cache_write"] else "")
          + (f"  ·  {totals['cache_read']:,} cache-read" if totals["cache_read"] else ""))
    if PRICES.get(model) and done:
        cost = cost_of(totals, model)
        print(f"  cost   : ~${cost:.2f} ({model}); ~${cost/done:.3f} per act")
    print(f"  model  : {model}   database: {db_path}")


def totals_for(db_path, tables=("decisions", "rulings", "reviews")) -> dict:
    """Aggregate recorded usage across tables — what the run actually cost."""
    conn = sqlite3.connect(db_path)
    out = {}
    for t in tables:
        try:
            rows = [json.loads(u) for (u,) in conn.execute(
                f"SELECT usage FROM {t} WHERE usage IS NOT NULL")]
        except sqlite3.OperationalError:
            continue
        if not rows:
            continue
        agg = {"acts": len(rows), "input_tokens": 0, "output_tokens": 0}
        for r in rows:
            agg["input_tokens"] += r.get("input_tokens", 0)
            agg["output_tokens"] += r.get("output_tokens", 0)
        models = {r.get("model") for r in rows}
        agg["models"] = sorted(m for m in models if m)
        out[t] = agg
    conn.close()
    return out


if __name__ == "__main__":
    # `python extract_runner.py [db]` — report what the corpus has cost so far.
    db = Path(sys.argv[1]) if len(sys.argv) > 1 else \
        Path(__file__).resolve().parent.parent / "data" / "decisions.db"
    tot = totals_for(db)
    if not tot:
        raise SystemExit(f"No recorded usage in {db} (rows written before usage logging).")
    gi = go = 0
    print(f"{'table':12}{'acts':>6}{'input':>14}{'output':>12}   models")
    for t, a in tot.items():
        gi += a["input_tokens"]; go += a["output_tokens"]
        print(f"{t:12}{a['acts']:>6}{a['input_tokens']:>14,}{a['output_tokens']:>12,}"
              f"   {', '.join(a['models'])}")
    every = {m for a in tot.values() for m in a["models"]}
    print(f"{'TOTAL':12}{sum(a['acts'] for a in tot.values()):>6}{gi:>14,}{go:>12,}")
    if len(every) == 1 and (p := PRICES.get(next(iter(every)))):
        print(f"\n  ~${gi/1e6*p[0] + go/1e6*p[1]:.2f} at {next(iter(every))} prices "
              f"(${p[0]:.2f}/${p[1]:.2f} per MTok)")
    elif len(every) > 1:
        print(f"\n  ⚠ mixed provenance: {', '.join(sorted(every))}")
