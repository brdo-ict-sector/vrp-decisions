"""
Extract the structured schema from рішення ВРП про перегляд рішення дисциплінарної
палати, using the Claude API. Results are stored in SQLite (data/decisions.db,
table `reviews`).

Why reviews get their own stage: 125 of the 450 «рішення» in the corpus are not
chamber decisions at all — they are the ВРП reviewing one, and the act number says
so (`…/0/15-…` versus `…/2дп/15-…`). Extracting them against DECISION_SCHEMA
described a document that does not exist and left every ВРП field empty.

A review is joined to the decision it reviews by the decision number quoted in its
own title — «Про залишення без змін рішення Другої Дисциплінарної палати ВРП від
4 лютого 2026 року № 151/2дп/15-26 …». All 112 review acts in the corpus do this,
which makes it the most reliable edge in the dataset. Like the complaint number, it
is found by rule (`act_numbers`) and handed to the model as an enum, so the model
chooses the reviewed decision and cannot transcribe a wrong digit.

Extraction is schema-enforced via structured outputs against REVIEW_SCHEMA.

AI drafts; an expert verifies. Re-runs are idempotent (skips done files).

Usage:
    ANTHROPIC_API_KEY=<key> python 24_extract_reviews.py [markdown_dir]
    ANTHROPIC_API_KEY=<key> python 24_extract_reviews.py --limit 5   # smoke test
"""

import argparse
import importlib.util
import json
import os
import sqlite3
import time
from pathlib import Path

import anthropic

import act_numbers
import register
from extraction_schema import (
    APPELLANT_TYPES,
    ART106_GROUNDS,
    REVIEW_KEYS,
    REVIEW_OUTCOMES,
    REVIEW_SCHEMA,
    SANCTION_TYPES,
    enforce_no_candidates,
    with_complaint_candidates,
    with_review_candidates,
)

# ── Config ──────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
MARKDOWN_DIR = BASE_DIR / "data" / "acts" / "md"
REGISTER_PATH = BASE_DIR / "data" / "register" / "hcj_acts_selected.xlsx"
DB_PATH = BASE_DIR / "data" / "decisions.db"

MODEL = "claude-opus-5"
MAX_TOKENS = 16000
MAX_CHARS = 160_000

_GROUNDS_LIST = "\n".join(f"  - {g}" for g in ART106_GROUNDS)
_SANCTION_LIST = "\n".join(f"  - {s}" for s in SANCTION_TYPES)
_OUTCOME_LIST = "\n".join(f"  - {o}" for o in REVIEW_OUTCOMES)
_APPELLANT_LIST = "\n".join(f"  - {a}" for a in APPELLANT_TYPES)

SYSTEM_PROMPT = f"""Ти — юридичний аналітик, який спеціалізується на дисциплінарному провадженні щодо суддів України.
Аналізуй рішення Вищої ради правосуддя (ВРП) про перегляд рішень дисциплінарних палат
і готуй структуровані огляди. Відповідай виключно українською мовою. Будь точним, лаконічним
та юридично коректним.

Це АКТ ДРУГОЇ ІНСТАНЦІЇ. Він переглядає рішення дисциплінарної палати, ухвалене раніше.
Чітко розрізняй, що встановила палата, а що — ВРП: у схему записуй позицію ВРП, а не палати.

ОДИНИЦЯ СПОСТЕРЕЖЕННЯ — СУДДЯ. Один перегляд може стосуватися кількох суддів, і ВРП може
щодо одного залишити рішення без змін, а щодо іншого — скасувати. Тому масив judges містить
по одному запису на кожного суддю, і результат перегляду заповнюється ОКРЕМО для кожного.

Поле review_outcome — що ВРП зробила з рішенням палати щодо ЦЬОГО судді, з набору:
{_OUTCOME_LIST}

Поля sanction і sanction_type — стягнення, ЧИННЕ ПІСЛЯ перегляду:
  - якщо рішення залишено без змін — те саме стягнення, що наклала палата;
  - якщо стягнення змінено — нове;
  - якщо рішення скасовано і стягнення не залишилося — sanction null, а
    sanction_type "стягнення не накладено".
sanction — повне формулювання, sanction_type — вид за частиною першою статті 109 з набору:
{_SANCTION_LIST}
Розрізняй «догану» і «сувору догану» — це різні стягнення (позбавлення доплат на один місяць
проти трьох). У полі summary.essence ОБОВ'ЯЗКОВО назви результат перегляду і чинне стягнення.

Поле qualification — як діяння кваліфікувала САМЕ ВРП, перелік підстав за частиною першою
статті 106 ВИКЛЮЧНО з такого фіксованого набору:
{_GROUNDS_LIST}
Якщо ВРП не переглядала кваліфікацію — став null. Підставу, якої немає в переліку, стисло
опиши в полі "note", не вигадуючи нових значень;
якщо коментаря немає, став порожній рядок "".

Поле appellant_type — хто ініціював перегляд, з набору:
{_APPELLANT_LIST}
Це важливо: суддя, який оскаржує стягнення, і скаржник, який оскаржує відмову, — протилежні
ситуації. Поле appellant_name — ПІБ або назва, якщо зазначено.

Поле reviewed_decision_num обирай ВИКЛЮЧНО зі значень, наведених у схемі — це номери рішень
дисциплінарних палат, знайдені дослівно в тексті цього акта. Обери те рішення, яке цим актом
переглядається (воно зазвичай названо в назві акта). Нічого не вигадуй і не виправляй.
Поле complaint_number так само обирай лише з наведених значень.

Поле panel — склад ВРП, головуючий ПЕРШИМ у списку.
Поля date і reviewed_decision_date — у форматі дд.мм.рррр.
Якщо певної інформації немає в тексті, став відповідні значення null."""

USER_PROMPT_TEMPLATE = """Проаналізуй наведене рішення ВРП про перегляд рішення дисциплінарної палати і поверни структуровані дані за схемою.

ТЕКСТ РІШЕННЯ:
{review_text}"""


def load_stage_14():
    """Load the complaint-number extractor (its name is not a Python identifier)."""
    path = Path(__file__).resolve().parent / "14_extract_complaint_numbers.py"
    spec = importlib.util.spec_from_file_location("complaint_numbers", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def is_review(record: dict) -> bool:
    """Is this register row a ВРП review?

    Selected by act number, not by title: `…/0/15-…` is the ВРП sitting in review,
    while `…/2дп/15-…` is a palate deciding at first instance. The title wording
    varies («залишення без змін», «скасування повністю», «скасування частково»)
    and would need an ever-growing list of patterns to catch.
    """
    return (
        record.get(register.KIND_COL) == "Рішення"
        and act_numbers.issuer_of(record.get(register.NUMBER_COL)) == act_numbers.ISSUER_VRP
    )


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            filename TEXT PRIMARY KEY,
            data TEXT,                       -- full structured JSON result
            processed_at TEXT DEFAULT (datetime('now')),
            error TEXT
        )
    """)
    conn.commit()


def already_processed(conn: sqlite3.Connection, filename: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM reviews WHERE filename = ? AND data IS NOT NULL", (filename,)
    ).fetchone()
    return row is not None


def extract_file(client: anthropic.Anthropic, md_path: Path, stage_14) -> dict:
    review_text = md_path.read_text(encoding="utf-8")

    # Both join keys are chosen from what the rules found in THIS act, never typed.
    complaints = stage_14.accepted_numbers(stage_14.find_numbers(review_text))
    reviewed = act_numbers.find_reviewed_decision_numbers(review_text)
    schema = with_review_candidates(
        with_complaint_candidates(REVIEW_SCHEMA, complaints), reviewed
    )

    if len(review_text) > MAX_CHARS:
        review_text = review_text[:MAX_CHARS] + "\n\n[текст скорочено]"

    message = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        thinking={"type": "adaptive"},
        system=[{
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }],
        output_config={"format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user",
                   "content": USER_PROMPT_TEMPLATE.format(review_text=review_text)}],
    )

    if message.stop_reason == "refusal":
        raise RuntimeError(f"refused ({getattr(message.stop_details, 'category', None)})")

    text = next((b.text for b in message.content if b.type == "text"), None)
    if text is None:
        raise RuntimeError(f"no JSON in response (stop_reason={message.stop_reason})")
    data = json.loads(text)

    result = enforce_no_candidates({k: data.get(k) for k in REVIEW_KEYS}, complaints)
    # Keep both candidate sets beside the answer so a reviewer sees what the model
    # was choosing between.
    result["complaint_number_candidates"] = complaints
    result["reviewed_decision_candidates"] = reviewed
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("markdown_dir", nargs="?", type=Path, default=MARKDOWN_DIR)
    ap.add_argument("--limit", type=int,
                    help="process at most N not-yet-extracted reviews, newest first")
    ap.add_argument("--register", type=Path, default=REGISTER_PATH)
    args = ap.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit("ERROR: ANTHROPIC_API_KEY environment variable not set")

    stage_14 = load_stage_14()
    md_files = register.markdown_files(
        args.markdown_dir, register.stems(args.register, is_review)
    )
    print(f"Found {len(md_files)} рішень ВРП про перегляд in {args.markdown_dir}"
          f" (newest first)")

    client = anthropic.Anthropic(api_key=api_key)
    done = 0
    with sqlite3.connect(DB_PATH) as conn:
        init_db(conn)
        for i, md_path in enumerate(md_files, 1):
            if args.limit and done >= args.limit:
                break
            filename = md_path.stem
            print(f"[{i}/{len(md_files)}] {filename} ... ", end="", flush=True)

            if already_processed(conn, filename):
                print("skipped (already done)")
                continue

            try:
                data = extract_file(client, md_path, stage_14)
                conn.execute(
                    """INSERT INTO reviews (filename, data, processed_at, error)
                       VALUES (?, ?, datetime('now'), NULL)
                       ON CONFLICT(filename) DO UPDATE SET
                           data=excluded.data, processed_at=datetime('now'), error=NULL""",
                    (filename, json.dumps(data, ensure_ascii=False)),
                )
                conn.commit()
                done += 1
                print("done")
            except Exception as e:
                print(f"ERROR: {e}")
                conn.execute(
                    """INSERT INTO reviews (filename, error) VALUES (?, ?)
                       ON CONFLICT(filename) DO UPDATE SET error=excluded.error""",
                    (filename, str(e)),
                )
                conn.commit()

            time.sleep(1)

    print(f"\nDone. Database: {DB_PATH}")


if __name__ == "__main__":
    main()
