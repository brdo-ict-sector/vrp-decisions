# Scheduling the nightly ingest

The pipeline's ingestion phase (stages 11–14: scrape the register → download new
acts → convert to Markdown → read out complaint numbers) runs unattended once a
day at **02:00 Kyiv time**. Extraction (phase 2) and merge/publish (phase 3) stay
manual: extraction costs money per act, and its output is an AI draft that an
expert verifies before it reaches the live site.

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
