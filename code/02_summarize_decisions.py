"""
Extract the structured Art. 106 schema + summaries from HCJ disciplinary-chamber
decisions using the Claude API. Results are stored in SQLite (data/decisions.db).

Per decision the model returns:
  - judge_name (ПІП), court, decision_num
  - qualification of the act under Art. 106 at the complaint / ДП / ВРП stages
  - summary of the judge's assessed conduct at the complaint / ДП / ВРП stages
  - sanction (стягнення) at the ДП / ВРП stages
  - summaries: essence (суть), facts (фабула), key conclusions (ключові висновки)

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

# ── Config ──────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
MARKDOWN_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE_DIR / "data" / "round2" / "md"
DB_PATH = BASE_DIR / "data" / "decisions.db"

MODEL = "claude-opus-4-8"
MAX_TOKENS = 4096
MAX_CHARS = 160_000  # truncate very long decisions to stay within context

SYSTEM_PROMPT = """Ти — юридичний аналітик, який спеціалізується на дисциплінарному провадженні щодо суддів України.
Аналізуй рішення дисциплінарних палат Вищої ради правосуддя (ВРП) та готуй структуровані огляди.
Відповідай виключно українською мовою. Будь точним, лаконічним та юридично коректним.
Кваліфікацію діяння завжди прив'язуй до конкретних пунктів/підпунктів частини першої статті 106
Закону України «Про судоустрій і статус суддів».
Якщо певної інформації немає в тексті (наприклад, не було перегляду рішенням ВРП), став значення null.
Повертай ВИКЛЮЧНО валідний JSON без додаткового тексту, markdown-огорожі чи коментарів."""

USER_PROMPT_TEMPLATE = """Проаналізуй рішення дисциплінарної палати ВРП і поверни JSON такої структури:

{{
  "judge_name": "ПІП судді, щодо якого відбувається розгляд",
  "court": "назва суду, де працює суддя",
  "decision_num": "номер рішення (напр. 983/1дп/15-25) або null",
  "chamber": "яка дисциплінарна палата (Перша/Друга/Третя) або null",
  "qualification": {{
    "complaint": "кваліфікація діяння за ст.106 у скарзі (пункти + короткий опис) або null",
    "dp": "кваліфікація діяння за ст.106 у рішенні дисциплінарної палати або null",
    "vrp": "кваліфікація за ст.106 у рішенні ВРП, якщо був перегляд, інакше null"
  }},
  "conduct": {{
    "complaint": "стисле самарі поведінки судді, оціненої скаржником як проступок, або null",
    "dp": "стисле самарі поведінки судді, оціненої дисциплінарною палатою як проступок, або null",
    "vrp": "самарі поведінки за рішенням ВРП, якщо був перегляд, інакше null"
  }},
  "sanction": {{
    "dp": "стягнення у рішенні дисциплінарної палати (або 'відмовлено у притягненні' / опис) або null",
    "vrp": "стягнення у рішенні ВРП, якщо був перегляд, інакше null"
  }},
  "art106_grounds": ["перелік застосованих пунктів ст.106, напр. \\"п.3 ч.1\\", \\"пп.б п.1 ч.1\\""],
  "summary": {{
    "essence": "Суть рішення: 2–4 речення (хто суддя, яке стягнення/відмова, підстава за законом)",
    "facts": "Фабула: 4–8 речень про встановлені палатою факти",
    "conclusions": ["3–5 ключових висновків палати, кожен — одне речення"]
  }}
}}

ТЕКСТ РІШЕННЯ:
{decision_text}"""

STRUCTURE_KEYS = (
    "judge_name", "court", "decision_num", "chamber",
    "qualification", "conduct", "sanction", "art106_grounds", "summary",
)


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


def parse_json(text: str) -> dict:
    """Parse the model's JSON, tolerating accidental markdown fences."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```", 2)[1]
        t = t[4:] if t.lower().startswith("json") else t
        t = t.strip()
    return json.loads(t)


def extract_file(client: anthropic.Anthropic, md_path: Path) -> dict:
    decision_text = md_path.read_text(encoding="utf-8")
    if len(decision_text) > MAX_CHARS:
        decision_text = decision_text[:MAX_CHARS] + "\n\n[текст скорочено]"

    message = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user",
                   "content": USER_PROMPT_TEMPLATE.format(decision_text=decision_text)}],
    )
    data = parse_json(message.content[0].text)
    # Ensure all top-level keys exist for a stable schema.
    for k in STRUCTURE_KEYS:
        data.setdefault(k, None)
    return data


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
