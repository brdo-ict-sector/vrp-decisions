# Scheduling the nightly cycle

The **whole pipeline** runs unattended once a day at **02:00 Kyiv time**:

1. **Ingest** (11–14) — scrape the register, download new acts, convert to
   Markdown, read out complaint numbers.
2. **Extract** (22 → 24 → 21) — send only the acts this scrape discovered to the
   Claude API. Rulings and reviews first, so a decision published the same night
   already carries the acts it links to.
3. **Export** (32, 33) — rebuild the site's JSON and the committed dataset.
4. **Publish** — commit and push. GitHub Pages serves `main:/docs`, so the push
   is the deployment.

Extraction needs `ANTHROPIC_API_KEY` in the repository's `.env` (mode 600). It is
deliberately *not* in the unit file: units under `/etc` are world-readable.

Spending is fenced twice — `--new-since-days` restricts it to newly discovered
acts, and `--limit` caps the count regardless. A normal night is two or three
acts, well under a dollar; the ceiling is about $13.

## Install

```bash
sudo cp deploy/vrp-ingest.service deploy/vrp-ingest.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now vrp-ingest.timer
```

The units assume the repository lives at `/home/ubuntu/vrp-ai-sandbox` and runs
as user `ubuntu`; edit `WorkingDirectory`, `ExecStart` and `User` if it does not.

## Check

```bash
systemctl list-timers vrp-ingest.timer     # next / last run
systemctl status vrp-ingest.service        # result of the last run
journalctl -u vrp-ingest.service -n 100    # full output
sudo systemctl start vrp-ingest.service    # run it right now
```

Each run also appends to `data/logs/daily-YYYY-MM-DD.log` (kept 30 days).

## Notes

- `Timezone=Europe/Kyiv` keeps the job at 02:00 local time across the DST
  switch; the host clock itself is UTC.
- `Persistent=true` means a missed run (machine off) happens once at next boot.
- `run_daily.sh` takes a `flock`, so a long backlog conversion is never
  overtaken by the following night's run.
- Arguments are passed through to stage 11, e.g. `code/run_daily.sh --since-days 90`
  to widen the window after an outage.
- `SKIP_EXTRACT=1` runs the ingest alone (no API spend); `SKIP_PUBLISH=1` does
  everything but the push. `NEW_SINCE_DAYS` and `EXTRACT_LIMIT` tune the fences.
- The publish step refuses to run on any branch but `main`. If the repository is
  left on a feature branch the log says so and the site quietly stops updating —
  check `git -C /home/ubuntu/vrp-ai-sandbox branch --show-current` first if the
  «Оновлено» date on the site stops advancing.
