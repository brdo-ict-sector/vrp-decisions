#!/usr/bin/env bash
#
# The whole nightly cycle: scrape → extract what is new → export → publish.
#
# Ingest (11-14) reads the ВРП register and converts new acts to Markdown.
# Extraction (21/22/24) sends **only the acts this scrape discovered** to the
# API. Export (32) rebuilds the site's JSON, and the last step commits and
# pushes so GitHub Pages republishes. Nothing here needs a human.
#
# The one thing that must never happen is the extraction stage walking into the
# ~500-act backlog and spending tens of dollars overnight, so it is fenced twice:
# `--new-since-days` restricts it to acts stamped «Вперше побачено» by a recent
# scrape (seeded history has no stamp and can never qualify), and
# `--limit` caps the act count whatever the register says. At ~$0.11 an act the
# nightly ceiling is about $13 across all three stages, and a normal night —
# two or three acts — costs well under a dollar.
#
# Safe to run by hand at any time; a second copy will not start while one is
# running.
#
# Usage:
#   code/run_daily.sh                    # the full cycle
#   code/run_daily.sh --since-days 90    # extra args go to the register scrape
#   SKIP_EXTRACT=1 code/run_daily.sh     # ingest only (the pre-2026-07 behaviour)
#   SKIP_PUBLISH=1 code/run_daily.sh     # extract and export, but do not push
#
# Tunables (environment):
#   NEW_SINCE_DAYS  how far back "new" reaches, in days   (default 5)
#   EXTRACT_LIMIT   max acts per act type per run         (default 40)
#
set -euo pipefail

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$BASE_DIR/venv/bin/python3"
LOG_DIR="$BASE_DIR/data/logs"
LOG_FILE="$LOG_DIR/daily-$(date +%F).log"
LOCK_FILE="$BASE_DIR/data/.daily.lock"

NEW_SINCE_DAYS="${NEW_SINCE_DAYS:-5}"
EXTRACT_LIMIT="${EXTRACT_LIMIT:-40}"
PUBLISH_BRANCH="main"

# The API key lives here, not in the unit file, so it is never in a
# world-readable place under /etc.
if [[ -f "$BASE_DIR/.env" ]]; then
    set -a; . "$BASE_DIR/.env"; set +a
fi

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

# ── 03: витягування даних з нових актів ─────────────────────────────────────
# Order matters: ухвали and рішення ВРП are what a рішення ДП card links to, so
# extracting them in the same run means a new decision can be published already
# joined to its opening act rather than joined a night later.
if [[ "${SKIP_EXTRACT:-0}" == "1" ]]; then
    echo; echo "── 03: витягування пропущено (SKIP_EXTRACT=1) ──────────────────"
elif [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
    echo; echo "── 03: ПОМИЛКА — ANTHROPIC_API_KEY не заданий, витягування пропущено"
    echo "   (перевірте $BASE_DIR/.env)"
else
    echo; echo "── 03: витягування даних з нових актів (за $NEW_SINCE_DAYS дн., макс. $EXTRACT_LIMIT на тип) ──"
    for stage in 22_extract_rulings 24_extract_reviews 21_extract_decisions; do
        echo; echo "   · $stage"
        "$PY" "code/$stage.py" --new-since-days "$NEW_SINCE_DAYS" --limit "$EXTRACT_LIMIT"
    done
fi

# ── 04: експорт у JSON для сайту ────────────────────────────────────────────
# Always runs, even when nothing new was extracted: the export also refreshes
# the «Оновлено» stamp, and joins can change when a related act arrives.
echo; echo "── 04: експорт у docs/decisions.json ───────────────────────────"
"$PY" code/32_export_to_json.py

# ── 05: публікація ──────────────────────────────────────────────────────────
# GitHub Pages serves main:/docs, so a push is the deployment.
if [[ "${SKIP_PUBLISH:-0}" == "1" ]]; then
    echo; echo "── 05: публікація пропущена (SKIP_PUBLISH=1) ───────────────────"
else
    echo; echo "── 05: публікація на GitHub Pages ──────────────────────────────"
    branch="$(git -C "$BASE_DIR" rev-parse --abbrev-ref HEAD)"
    if [[ "$branch" != "$PUBLISH_BRANCH" ]]; then
        # Committing here would put the data on a branch Pages does not serve,
        # and the site would silently stop updating. Say so instead.
        echo "   УВАГА: гілка «$branch», а не «$PUBLISH_BRANCH» — публікацію пропущено"
    else
        # Only the generated artefacts. `git add -A` would sweep in whatever else
        # happens to be in the tree, which is not this job's to commit.
        git -C "$BASE_DIR" add docs/decisions.json docs/meta.json
        git -C "$BASE_DIR" add -f data/register/hcj_acts.xlsx data/register/hcj_acts_selected.xlsx

        if git -C "$BASE_DIR" diff --cached --quiet; then
            echo "   змін немає — нічого публікувати"
        else
            git -C "$BASE_DIR" commit -q -m "data: автоматичне оновлення $(date +%F)" \
                -m "Щоденний цикл: реєстр → витягування нових актів → експорт → публікація."
            if ! git -C "$BASE_DIR" push -q origin "$PUBLISH_BRANCH" 2>&1; then
                # Someone pushed while this ran. Replay our commit on top and retry
                # once; a real conflict aborts the rebase and is left for a human.
                echo "   push відхилено — пробуємо rebase на origin/$PUBLISH_BRANCH"
                if git -C "$BASE_DIR" pull --rebase --autostash -q origin "$PUBLISH_BRANCH" \
                   && git -C "$BASE_DIR" push -q origin "$PUBLISH_BRANCH"; then
                    echo "   опубліковано після rebase"
                else
                    git -C "$BASE_DIR" rebase --abort 2>/dev/null || true
                    echo "   ПОМИЛКА: не вдалося опублікувати — потрібне втручання"
                    exit 1
                fi
            fi
            echo "   опубліковано: $(git -C "$BASE_DIR" rev-parse --short HEAD)"
        fi
    fi
fi

echo; echo "$(date -Is)  завершено успішно"

# Keep a month of logs; they are small but there is no reason to grow forever.
find "$LOG_DIR" -name 'daily-*.log' -mtime +30 -delete
