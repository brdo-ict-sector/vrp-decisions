"""
Extract the structured Art. 106 schema + summaries from HCJ disciplinary-chamber
decisions using the Claude API. Results are stored in SQLite (data/decisions.db).

Extraction is schema-enforced via structured outputs: the request sets
`output_config.format` to DECISION_SCHEMA (see extraction_schema.py), so the model's
response is guaranteed to be valid JSON conforming to the schema — and the enum on
кваліфікація діяння guarantees grounds come only from the fixed corpus enum. Structured
outputs are compatible with adaptive thinking (unlike forcing a specific tool_choice).

Per decision the model returns:
  - decision_num, date, short_name, complaint_number
  - judges[] — one entry per judge the decision rules on, each carrying that judge's
    qualification (скарга / ДП), conduct, sanction + sanction_type, and outcome
  - summary: essence (суть), facts (фабула), conclusions (ключові висновки)

The judge, not the act, is the unit of observation: a decision routinely punishes one
judge and refuses to punish another in the same operative part, so an act-level
sanction would have to pick one and discard the rest.

Two things are deliberately NOT asked of the model. `chamber` is stated by the act
number (`…/2дп/…` = Друга) and is derived by `act_numbers.chamber_of()`. The ВРП
review is a separate act with its own schema (stage 24), not a stage inside this one.

AI drafts; an expert verifies. Re-runs are idempotent (skips done files).

Usage:
    ANTHROPIC_API_KEY=<key> python 21_extract_decisions.py [markdown_dir]
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
import extract_runner
import register
from extraction_schema import (
    ART106_GROUNDS,
    DECISION_SCHEMA,
    SANCTION_TYPES,
    STRUCTURE_KEYS,
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
_SANCTION_LIST = "\n".join(f"  - {s}" for s in SANCTION_TYPES)

SYSTEM_PROMPT = f"""Ти — юридичний аналітик, який спеціалізується на дисциплінарному провадженні щодо суддів України.
Аналізуй рішення дисциплінарних палат Вищої ради правосуддя (ВРП) і готуй структуровані огляди.
Відповідай виключно українською мовою. Будь точним, лаконічним та юридично коректним.

ОДИНИЦЯ СПОСТЕРЕЖЕННЯ — СУДДЯ. Одне рішення може стосуватися кількох суддів, і палата вирішує
щодо КОЖНОГО окремо: одного притягнути, іншому — відмовити. Тому масив judges містить по одному
запису на кожного суддю, згаданого в резолютивній частині, і кваліфікація, поведінка, стягнення
та результат заповнюються ОКРЕМО для кожного. НЕ зводь кількох суддів до одного запису і не
переноси стягнення одного судді на іншого. Поле name — ПІБ так, як його зазначено в акті.

Для кожного судді кваліфікацію діяння (поле qualification) фіксуй ОКРЕМО для двох стадій:
  - complaint — як діяння кваліфіковано у дисциплінарній скарзі;
  - dp — як його кваліфікувала дисциплінарна палата у цьому рішенні.
Для кожної стадії "grounds" — це перелік підстав за частиною першою статті 106 ВИКЛЮЧНО з такого фіксованого набору:
{_GROUNDS_LIST}
Обирай лише ті значення зі списку, що відповідають тексту. Якщо у скарзі згадано підставу, якої немає в списку,
не вигадуй значення — стисло опиши її в полі "note". Поле "note" — короткий уточнювальний коментар; якщо додати нічого, став порожній рядок "".

Стягнення фіксуй ДВІЧІ, для кожного судді окремо:
  - sanction — повне формулювання стягнення так, як його викладено в акті (разом із позбавленням доплат і строком);
  - sanction_type — те саме стягнення, зведене до виду за частиною першою статті 109 Закону, ВИКЛЮЧНО з набору:
{_SANCTION_LIST}
Розрізняй «догану» і «сувору догану» — це різні види стягнення з різними наслідками (позбавлення доплат
на один місяць проти трьох), і плутати їх не можна. Якщо щодо цього судді справу закрито, його звільнено
від дисциплінарної відповідальності або сплив строк притягнення — став "стягнення не накладено", а
sanction — null. Поле outcome — що палата вирішила щодо ЦЬОГО судді.

Це рішення дисциплінарної палати — перша інстанція. Перегляд рішенням ВРП є ОКРЕМИМ актом
і в цій схемі не фіксується: не намагайся вгадати, чи буде перегляд, і не переноси сюди його наслідки.

У полі summary.essence ОБОВ'ЯЗКОВО назви накладене стягнення повністю і точно
(«попередження», «догану», «сувору догану», «подання про звільнення судді з посади» тощо), а якщо
суддів кілька — щодо кожного. Короткий зміст без виду стягнення є неповним. Не пиши просто «догану»,
якщо накладено сувору догану.

Поле complaint_number обирай ВИКЛЮЧНО зі значень, наведених у схемі — це номери дисциплінарних скарг,
знайдені дослівно в тексті саме цього рішення. Основний номер — той, за скаргою якого відкрито справу.
Решту (для об'єднаних справ) перелічи в related_complaint_numbers. Нічого не вигадуй і не виправляй.

Поле date — у форматі дд.мм.рррр. Поле short_name — офіційна назва рішення
(напр. «Про притягнення судді ... до дисциплінарної відповідальності»).
Якщо певної інформації немає в тексті, став відповідні значення null."""

USER_PROMPT_TEMPLATE = """Проаналізуй наведене рішення дисциплінарної палати ВРП і поверни структуровані дані за схемою.

ТЕКСТ РІШЕННЯ:
{decision_text}"""


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS decisions (
            filename TEXT PRIMARY KEY,
            data TEXT,                       -- full structured JSON result
            processed_at TEXT DEFAULT (datetime('now')),
            error TEXT
        )
    """)
    conn.commit()


def already_processed(conn: sqlite3.Connection, filename: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM decisions WHERE filename = ? AND data IS NOT NULL", (filename,)
    ).fetchone()
    return row is not None


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


def extract_file(client: anthropic.Anthropic, md_path: Path, stage_14,
                 model: str = MODEL) -> dict:
    decision_text = md_path.read_text(encoding="utf-8")

    # Constrain the complaint-number fields to what stage 14 found in THIS act, so the
    # join key is chosen from real numbers rather than transcribed by the model.
    candidates = stage_14.accepted_numbers(stage_14.find_numbers(decision_text))
    schema = with_complaint_candidates(DECISION_SCHEMA, candidates)

    # Head *and* tail: the sanction is in the last paragraph of the act.
    decision_text = clip_for_model(decision_text, MAX_CHARS)

    message = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        thinking={"type": "adaptive"},
        system=SYSTEM_PROMPT,
        output_config={"format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user",
                   "content": USER_PROMPT_TEMPLATE.format(decision_text=decision_text)}],
    )

    # output_config.format guarantees the response carries a text block of valid JSON.
    text = next((b.text for b in message.content if b.type == "text"), None)
    if text is None:
        raise RuntimeError(f"no JSON in response (stop_reason={message.stop_reason})")
    data = json.loads(text)
    # Stable key set for downstream storage.
    result = enforce_no_candidates(
        {k: data.get(k) for k in (*STRUCTURE_KEYS, "related_complaint_numbers")}, candidates
    )
    result["complaint_number_candidates"] = candidates
    # The message travels with the record so the runner can bank its token usage.
    return result, message


def is_decision(record: dict) -> bool:
    """Is this register row a first-instance palate decision?

    Selected by act number: `…/2дп/15-…` is a palate deciding, `…/0/15-…` is the ВРП
    reviewing (stage 24). Without this the stage globbed every Markdown file in the
    corpus and would have extracted 485 ухвали and 125 ВРП reviews against a schema
    that does not describe them.
    """
    return (
        record.get(register.KIND_COL) == "Рішення"
        and act_numbers.issuer_of(record.get(register.NUMBER_COL)) == act_numbers.ISSUER_DP
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("markdown_dir", nargs="?", type=Path, default=MARKDOWN_DIR)
    ap.add_argument("--limit", type=int,
                    help="process at most N not-yet-extracted decisions, newest first")
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
    ap.add_argument("--budget", type=float,
                    help="stop submitting acts once recorded spend across the whole "
                         "database reaches this many dollars (survives restarts)")
    args = ap.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit("ERROR: ANTHROPIC_API_KEY environment variable not set")

    stage_14 = load_stage_14()
    md_files = register.markdown_files(
        args.markdown_dir, register.stems(args.register, is_decision), args.only
    )
    print(f"Found {len(md_files)} рішень дисциплінарних палат in {args.markdown_dir}"
          f" (newest first)")

    # More retries than the SDK default: an 862-act run will meet a 429 or an
    # overloaded response eventually, and losing an act to one is pure waste.
    client = anthropic.Anthropic(api_key=api_key, max_retries=8)
    extract_runner.run(
        md_files, "decisions",
        lambda p: extract_file(client, p, stage_14, args.model),
        model=args.model, db_path=args.db, limit=args.limit,
        workers=args.workers, budget=args.budget, label="рішень ДП",
    )


if __name__ == "__main__":
    main()
