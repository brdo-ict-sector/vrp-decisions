"""
Summarize HCJ disciplinary chamber decisions using Claude API.
Stores results in SQLite database.

Usage:
    ANTHROPIC_API_KEY=<key> python 02_summarize_decisions.py
"""

import os
import sqlite3
import time
from pathlib import Path

import anthropic

# ── Config ──────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
MARKDOWN_DIR = BASE_DIR / "data" / "markdown_disc_chamber_sample"
DB_PATH = BASE_DIR / "data" / "decisions.db"

MODEL = "claude-opus-4-6"
MAX_TOKENS = 2048

SYSTEM_PROMPT = """Ти — юридичний аналітик, який спеціалізується на дисциплінарному провадженні щодо суддів України.
Твоє завдання — аналізувати рішення дисциплінарних палат Вищої ради правосуддя України та готувати структуровані огляди трьома частинами.
Відповідай виключно українською мовою. Будь точним, лаконічним та юридично коректним."""

USER_PROMPT_TEMPLATE = """Проаналізуй рішення дисциплінарної палати Вищої ради правосуддя та надай структурований огляд з трьох частин.

РІШЕННЯ:
{decision_text}

Надай відповідь у такому форматі (суворо дотримуйся структури):

## Суть рішення
[Стисло опиши у 2–4 реченнях: хто є суддею (ім'я, суд), яке дисциплінарне стягнення застосовано або чому відмовлено у стягненні, та підстава за законом]

## Фабула
[Виклади встановлені палатою факти: що саме зробив або не зробив суддя, обставини дисциплінарного проступку, ключові докази. 4–8 речень]

## Ключові висновки
[Перелічи 3–5 ключових правових та фактичних висновків палати у вигляді коротких тез (кожна — одне речення, починай з нового рядка зі знаком «–»)]"""


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT UNIQUE NOT NULL,
            decision_essence TEXT,
            facts TEXT,
            key_conclusions TEXT,
            processed_at TEXT DEFAULT (datetime('now')),
            error TEXT
        )
    """)
    conn.commit()


def already_processed(conn: sqlite3.Connection, filename: str) -> bool:
    row = conn.execute(
        "SELECT id FROM decisions WHERE filename = ? AND decision_essence IS NOT NULL",
        (filename,)
    ).fetchone()
    return row is not None


def parse_response(text: str) -> dict:
    """Extract the three sections from Claude's response."""
    sections = {"decision_essence": "", "facts": "", "key_conclusions": ""}
    markers = {
        "## Суть рішення": "decision_essence",
        "## Фабула": "facts",
        "## Ключові висновки": "key_conclusions",
    }
    current_key = None
    current_lines = []

    for line in text.splitlines():
        stripped = line.strip()
        matched = False
        for marker, key in markers.items():
            if stripped.startswith(marker):
                if current_key:
                    sections[current_key] = "\n".join(current_lines).strip()
                current_key = key
                current_lines = []
                matched = True
                break
        if not matched and current_key is not None:
            current_lines.append(line)

    if current_key:
        sections[current_key] = "\n".join(current_lines).strip()

    return sections


def summarize_file(client: anthropic.Anthropic, md_path: Path) -> dict:
    decision_text = md_path.read_text(encoding="utf-8")
    # Truncate very long documents to stay within context (keep ~120k chars)
    if len(decision_text) > 120_000:
        decision_text = decision_text[:120_000] + "\n\n[текст скорочено]"

    message = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": USER_PROMPT_TEMPLATE.format(decision_text=decision_text)}
        ],
    )
    raw = message.content[0].text
    return parse_response(raw)


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
            filename = md_path.stem  # filename without extension
            print(f"[{i}/{len(md_files)}] {filename} ... ", end="", flush=True)

            if already_processed(conn, filename):
                print("skipped (already done)")
                continue

            try:
                sections = summarize_file(client, md_path)
                conn.execute(
                    """INSERT INTO decisions (filename, decision_essence, facts, key_conclusions)
                       VALUES (?, ?, ?, ?)
                       ON CONFLICT(filename) DO UPDATE SET
                           decision_essence=excluded.decision_essence,
                           facts=excluded.facts,
                           key_conclusions=excluded.key_conclusions,
                           processed_at=datetime('now'),
                           error=NULL""",
                    (filename, sections["decision_essence"], sections["facts"], sections["key_conclusions"]),
                )
                conn.commit()
                print("done")
            except Exception as e:
                print(f"ERROR: {e}")
                conn.execute(
                    "INSERT INTO decisions (filename, error) VALUES (?, ?) ON CONFLICT(filename) DO UPDATE SET error=excluded.error",
                    (filename, str(e)),
                )
                conn.commit()

            # Polite rate-limit pause between API calls
            if i < len(md_files):
                time.sleep(1)

    print(f"\nDone. Database: {DB_PATH}")


if __name__ == "__main__":
    main()
