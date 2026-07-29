"""
Extract the structured schema from ухвали про відкриття дисциплінарної справи
using the Claude API. Results are stored in SQLite (data/decisions.db, table
`rulings`).

Why rulings get their own stage: an ухвала is not a smaller рішення. It records
what the complainant asked for, what the disciplinary inspector proposed, what
the palace actually opened the case on, and — uniquely — which grounds the palace
expressly refused to open on. Set against the decision's `qualification.dp`, that
is the «по чому відкрилися vs по чому реально було притягнуто» comparison.

The complaint number is never transcribed by the model. Stage 14 extracts every
candidate verbatim from the same act, and `with_complaint_candidates()` turns
them into an enum — so the model *chooses* among real numbers and cannot invent
one. Acts where stage 14 found nothing get a null-only field and surface as gaps.

Extraction is schema-enforced via structured outputs: the request sets
`output_config.format` to the per-document schema, so the response is guaranteed
to be valid JSON conforming to it — and the enums guarantee grounds, complainant
type, and complaint number come only from the fixed vocabularies.

AI drafts; an expert verifies. Re-runs are idempotent (skips done files).

Usage:
    ANTHROPIC_API_KEY=<key> python 22_extract_rulings.py [markdown_dir]
    ANTHROPIC_API_KEY=<key> python 22_extract_rulings.py --limit 5   # smoke test
"""

import argparse
import importlib.util
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

import anthropic

import extract_runner
import register
from extraction_schema import (
    ART106_GROUNDS,
    COMPLAINANT_TYPES,
    INSPECTOR_PROPOSALS,
    RULING_KEYS,
    RULING_SCHEMA,
    clip_for_model,
    enforce_no_candidates,
    with_complaint_candidates,
)

# ── Config ──────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
MARKDOWN_DIR = BASE_DIR / "data" / "acts" / "md"
REGISTER_PATH = BASE_DIR / "data" / "register" / "hcj_acts_selected.xlsx"
DB_PATH = BASE_DIR / "data" / "decisions.db"

MODEL = "claude-sonnet-5"  # A/B tested against Opus 5 on 20 acts: 96.6% agreement on
                          # structured fields, no judge-identity differences, ~40% cheaper.
MAX_TOKENS = 16000  # caps thinking + response together — leave the model room
MAX_CHARS = 500_000  # the whole act: the largest in the corpus is ~430k chars

_GROUNDS_LIST = "\n".join(f"  - {g}" for g in ART106_GROUNDS)
_COMPLAINANT_LIST = "\n".join(f"  - {t}" for t in COMPLAINANT_TYPES)
_PROPOSAL_LIST = "\n".join(f"  - {p}" for p in INSPECTOR_PROPOSALS)

SYSTEM_PROMPT = f"""Ти — юридичний аналітик, який спеціалізується на дисциплінарному провадженні щодо суддів України.
Аналізуй ухвали дисциплінарних палат Вищої ради правосуддя (ВРП) про відкриття дисциплінарної справи
і готуй структуровані огляди. Відповідай виключно українською мовою. Будь точним, лаконічним та юридично коректним.

ОДИНИЦЯ СПОСТЕРЕЖЕННЯ — СУДДЯ. Одна ухвала може стосуватися кількох суддів, і палата вирішує
щодо КОЖНОГО окремо: щодо одного відкрити справу, щодо іншого — відмовити, і за різними підставами.
Тому масив judges містить по одному запису на кожного суддю, а підстави (grounds), результат
(outcome), опис діяння та позиція судді заповнюються ОКРЕМО для кожного. НЕ зводь кількох суддів
до одного запису. Поле name — ПІБ так, як його зазначено в акті.

Для КОЖНОГО судді поле grounds фіксуй ОКРЕМО для трьох стадій — це головна аналітична цінність ухвали:
  - requested — підстави, за якими скаржник просив притягнути цього суддю до відповідальності;
  - opened — підстави, за якими палата встановила ознаки дисциплінарного проступку і відкрила справу;
  - rejected — підстави, щодо яких палата ПРЯМО зазначила, що ознак складу проступку НЕ встановила.
Якщо стадія у тексті відсутня — став null. НЕ дублюй requested у opened «за замовчуванням»:
палата часто відкриває справу за вужчим переліком, ніж просив скаржник, і саме ця різниця нас цікавить.

Для кожної стадії "grounds" — це перелік підстав за частиною першою статті 106 ВИКЛЮЧНО з такого фіксованого набору:
{_GROUNDS_LIST}
Обирай лише ті значення зі списку, що відповідають тексту. Якщо згадано підставу, якої немає в списку,
не вигадуй значення — стисло опиши її в полі "note". Поле "note" — короткий уточнювальний коментар; якщо додати нічого, став порожній рядок "".

Поле complainant_type — хто подав скаргу, з набору:
{_COMPLAINANT_LIST}
Поле inspector_proposal — що пропонував дисциплінарний інспектор у своєму висновку, з набору:
{_PROPOSAL_LIST}
Якщо палата не погодилася з інспектором, це важливо: обери те, що інспектор пропонував НАСПРАВДІ,
а не те, що вирішила палата.

Поле complaint_number обирай ВИКЛЮЧНО зі значень, наведених у схемі — це номери, знайдені дослівно
в тексті саме цієї ухвали. Основний номер — той, за скаргою якого відкрито справу.
Решту (для об'єднаних справ) перелічи в related_complaint_numbers. Нічого не вигадуй і не виправляй.

Поле panel — склад палати, головуючий ПЕРШИМ у списку.
Поля date і complaint_date — у форматі дд.мм.рррр.
Якщо певної інформації немає в тексті, став відповідні значення null."""

USER_PROMPT_TEMPLATE = """Проаналізуй наведену ухвалу дисциплінарної палати ВРП і поверни структуровані дані за схемою.

ТЕКСТ УХВАЛИ:
{ruling_text}"""


def load_stage_14():
    """Load the complaint-number extractor.

    Imported by path because pipeline stages are named with numeric prefixes,
    which are not valid Python module names. stage 14 stays the single source of
    truth for the extraction rules.
    """
    path = Path(__file__).resolve().parent / "14_extract_complaint_numbers.py"
    spec = importlib.util.spec_from_file_location("complaint_numbers", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def is_ruling(record: dict) -> bool:
    """Is this register row an ухвала? The register's own document kind decides."""
    return record.get(register.KIND_COL) == "Ухвала"


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rulings (
            filename TEXT PRIMARY KEY,
            data TEXT,                       -- full structured JSON result
            processed_at TEXT DEFAULT (datetime('now')),
            error TEXT
        )
    """)
    conn.commit()


def already_processed(conn: sqlite3.Connection, filename: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM rulings WHERE filename = ? AND data IS NOT NULL", (filename,)
    ).fetchone()
    return row is not None


def extract_file(client: anthropic.Anthropic, md_path: Path, stage_14,
                 model: str = MODEL) -> dict:
    ruling_text = md_path.read_text(encoding="utf-8")

    # Constrain the complaint-number fields to what stage 14 found in THIS act.
    candidates = stage_14.accepted_numbers(stage_14.find_numbers(ruling_text))
    schema = with_complaint_candidates(RULING_SCHEMA, candidates)

    # Head *and* tail: what the palate opened on is stated in the last paragraph.
    ruling_text = clip_for_model(ruling_text, MAX_CHARS)

    message = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        thinking={"type": "adaptive"},
        # No cache_control. It was here on the theory that an identical system
        # prompt across the batch would turn ~500 prefills into cache reads, and
        # measurement disproved it: `cache_read_input_tokens` was 0 on every call
        # while `cache_creation_input_tokens` was ~15 700. The cached prefix is
        # not the system prompt (1 755 tokens) — it is dominated by the per-act
        # schema, whose complaint-number enum is rebuilt for each act by
        # `with_complaint_candidates()`. A prefix that differs every call can
        # never be read back, so the only effect was paying the 1.25× write
        # premium on 15 700 tokens per act.
        system=SYSTEM_PROMPT,
        output_config={"format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user",
                   "content": USER_PROMPT_TEMPLATE.format(ruling_text=ruling_text)}],
    )

    if message.stop_reason == "refusal":
        raise RuntimeError(f"refused ({getattr(message.stop_details, 'category', None)})")

    # output_config.format guarantees the response carries a text block of valid JSON.
    text = next((b.text for b in message.content if b.type == "text"), None)
    if text is None:
        raise RuntimeError(f"no JSON in response (stop_reason={message.stop_reason})")
    data = json.loads(text)

    keys = (*RULING_KEYS, "related_complaint_numbers")
    result = enforce_no_candidates({k: data.get(k) for k in keys}, candidates)
    # Keep the candidate set alongside the answer so a reviewer can see what the
    # model was choosing between.
    result["complaint_number_candidates"] = candidates
    # The message travels with the record so the runner can bank its token usage.
    return result, message


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("markdown_dir", nargs="?", type=Path, default=MARKDOWN_DIR)
    ap.add_argument("--limit", type=int,
                    help="process at most N not-yet-extracted rulings, newest first")
    ap.add_argument("--register", type=Path, default=REGISTER_PATH)
    # A different model writes to a different database. Overwriting the rows in
    # place would destroy the baseline the comparison exists to measure against.
    ap.add_argument("--model", default=MODEL, help=f"extraction model (default {MODEL})")
    ap.add_argument("--db", type=Path, default=DB_PATH,
                    help="SQLite file to write to (default the pipeline database)")
    ap.add_argument("--only", nargs="+", metavar="STEM",
                    help="extract only these acts (e.g. 617_08.04.2026) — used to "
                         "backfill a whole case rather than a recent window")
    ap.add_argument("--workers", type=int, default=6,
                    help="concurrent API calls (default 6); lower it if you see 429s")
    args = ap.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit("ERROR: ANTHROPIC_API_KEY environment variable not set")

    stage_14 = load_stage_14()
    md_files = register.markdown_files(
        args.markdown_dir, register.stems(args.register, is_ruling), args.only
    )
    print(f"Found {len(md_files)} ухвали in {args.markdown_dir} (newest first)")

    # More retries than the SDK default: an 862-act run will meet a 429 or an
    # overloaded response eventually, and losing an act to one is pure waste.
    client = anthropic.Anthropic(api_key=api_key, max_retries=8)
    extract_runner.run(
        md_files, "rulings",
        lambda p: extract_file(client, p, stage_14, args.model),
        model=args.model, db_path=args.db, limit=args.limit,
        workers=args.workers, label="ухвал",
    )


if __name__ == "__main__":
    main()
