"""
Extract the structured Art. 106 schema + summaries from HCJ disciplinary-chamber
decisions using the Claude API. Results are stored in SQLite (data/decisions.db).

Extraction is schema-enforced via structured outputs: the request sets
`output_config.format` to DECISION_SCHEMA (see extraction_schema.py), so the model's
response is guaranteed to be valid JSON conforming to the schema — and the enum on
кваліфікація діяння guarantees grounds come only from the fixed corpus enum. Structured
outputs are compatible with adaptive thinking (unlike forcing a specific tool_choice).

Per decision the model returns:
  - judge_name (ПІП), court, decision_num, chamber, date, short_name
  - qualification per stage (скарга / ДП / ВРП): a list of enum grounds + a note
  - conduct (summary) per stage; sanction (стягнення) at ДП / ВРП
  - summary: essence (суть), facts (фабула), conclusions (ключові висновки)

AI drafts; an expert verifies. Re-runs are idempotent (skips done files).

Usage:
    ANTHROPIC_API_KEY=<key> python 02_summarize_decisions.py [markdown_dir]
"""

import json
import os
import sqlite3
import sys
import time
from pathlib import Path

import anthropic

from extraction_schema import ART106_GROUNDS, DECISION_SCHEMA, STRUCTURE_KEYS

# ── Config ──────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
MARKDOWN_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE_DIR / "data" / "round2" / "md"
DB_PATH = BASE_DIR / "data" / "decisions.db"

MODEL = "claude-opus-4-8"
MAX_TOKENS = 8192
MAX_CHARS = 160_000  # truncate very long decisions to stay within context

_GROUNDS_LIST = "\n".join(f"  - {g}" for g in ART106_GROUNDS)

SYSTEM_PROMPT = f"""Ти — юридичний аналітик, який спеціалізується на дисциплінарному провадженні щодо суддів України.
Аналізуй рішення дисциплінарних палат Вищої ради правосуддя (ВРП) і готуй структуровані огляди.
Відповідай виключно українською мовою. Будь точним, лаконічним та юридично коректним.

Кваліфікацію діяння (поле qualification) фіксуй ОКРЕМО для кожної стадії:
  - complaint — як діяння кваліфіковано у дисциплінарній скарзі;
  - dp — як його кваліфікувала дисциплінарна палата у цьому рішенні;
  - vrp — як його кваліфікувала ВРП, якщо був перегляд, інакше null.
Для кожної стадії "grounds" — це перелік підстав за частиною першою статті 106 ВИКЛЮЧНО з такого фіксованого набору:
{_GROUNDS_LIST}
Обирай лише ті значення зі списку, що відповідають тексту. Якщо у скарзі згадано підставу, якої немає в списку,
не вигадуй значення — стисло опиши її в полі "note". Поле "note" — короткий уточнювальний коментар або null.

Поле date — у форматі дд.мм.рррр. Поле short_name — офіційна назва рішення
(напр. «Про притягнення судді ... до дисциплінарної відповідальності»). Поле chamber — Перша/Друга/Третя.
Якщо певної інформації немає в тексті (напр., не було перегляду рішенням ВРП), став відповідні значення null."""

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


def extract_file(client: anthropic.Anthropic, md_path: Path) -> dict:
    decision_text = md_path.read_text(encoding="utf-8")
    if len(decision_text) > MAX_CHARS:
        decision_text = decision_text[:MAX_CHARS] + "\n\n[текст скорочено]"

    message = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        thinking={"type": "adaptive"},
        system=SYSTEM_PROMPT,
        output_config={"format": {"type": "json_schema", "schema": DECISION_SCHEMA}},
        messages=[{"role": "user",
                   "content": USER_PROMPT_TEMPLATE.format(decision_text=decision_text)}],
    )

    # output_config.format guarantees the response carries a text block of valid JSON.
    text = next((b.text for b in message.content if b.type == "text"), None)
    if text is None:
        raise RuntimeError(f"no JSON in response (stop_reason={message.stop_reason})")
    data = json.loads(text)
    # Stable key set for downstream storage.
    return {k: data.get(k) for k in STRUCTURE_KEYS}


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit("ERROR: ANTHROPIC_API_KEY environment variable not set")

    client = anthropic.Anthropic(api_key=api_key)
    md_files = sorted(MARKDOWN_DIR.glob("*.md"))
    print(f"Found {len(md_files)} markdown files in {MARKDOWN_DIR}")

    with sqlite3.connect(DB_PATH) as conn:
        init_db(conn)
        for i, md_path in enumerate(md_files, 1):
            filename = md_path.stem
            print(f"[{i}/{len(md_files)}] {filename} ... ", end="", flush=True)

            if already_processed(conn, filename):
                print("skipped (already done)")
                continue

            try:
                data = extract_file(client, md_path)
                conn.execute(
                    """INSERT INTO decisions (filename, data, processed_at, error)
                       VALUES (?, ?, datetime('now'), NULL)
                       ON CONFLICT(filename) DO UPDATE SET
                           data=excluded.data, processed_at=datetime('now'), error=NULL""",
                    (filename, json.dumps(data, ensure_ascii=False)),
                )
                conn.commit()
                print("done")
            except Exception as e:
                print(f"ERROR: {e}")
                conn.execute(
                    """INSERT INTO decisions (filename, error) VALUES (?, ?)
                       ON CONFLICT(filename) DO UPDATE SET error=excluded.error""",
                    (filename, str(e)),
                )
                conn.commit()

            if i < len(md_files):
                time.sleep(1)

    print(f"\nDone. Database: {DB_PATH}")


if __name__ == "__main__":
    main()
