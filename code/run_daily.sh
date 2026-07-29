#!/usr/bin/env bash
#
# Nightly ingest: register → selection → downloads → Markdown.
#
# Stages 00-02 only. Extraction (03) costs money per decision and produces
# drafts that an expert must verify, and publishing (04) puts them on the live
# site — neither belongs in an unattended job.
#
# Safe to run by hand at any time; a second copy will not start while one is
# running.
#
# Usage:
#   code/run_daily.sh                 # last 30 days
#   code/run_daily.sh --since-days 90 # extra args go to stage 00
#
set -euo pipefail

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$BASE_DIR/venv/bin/python3"
LOG_DIR="$BASE_DIR/data/logs"
LOG_FILE="$LOG_DIR/daily-$(date +%F).log"
LOCK_FILE="$BASE_DIR/data/.daily.lock"

mkdir -p "$LOG_DIR"

# One run at a time: converting a large backlog can take hours and must not be
# overtaken by the next night's run.
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "$(date -Is) вже виконується інший запуск — вихід" >> "$LOG_FILE"
    exit 0
fi

# Everything below is both shown and logged, so a manual run still gives output.
exec > >(tee -a "$LOG_FILE") 2>&1

echo "════════════════════════════════════════════════════════════════"
echo "$(date -Is)  старт щоденного оновлення"

cd "$BASE_DIR"

echo; echo "── 00: реєстр ──────────────────────────────────────────────────"
"$PY" code/11_scrape_register.py "$@"

echo; echo "── 01: відбір і завантаження файлів ────────────────────────────"
"$PY" code/12_select_and_download.py

echo; echo "── 02: конвертація у Markdown ──────────────────────────────────"
"$PY" code/13_transform_raw_to_md.py

# Must follow 01 (which rebuilds the table from scratch) and 02 (which supplies
# the Markdown the numbers are read from).
echo; echo "── 02b: номери дисциплінарних скарг у таблицю ───────────────────"
"$PY" code/14_extract_complaint_numbers.py --update-xlsx

echo; echo "$(date -Is)  завершено успішно"

# Keep a month of logs; they are small but there is no reason to grow forever.
find "$LOG_DIR" -name 'daily-*.log' -mtime +30 -delete
