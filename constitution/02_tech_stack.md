# Tech Stack

> Last updated: 2026-06-07
> Status: Active
> Source: derived from [00_stakeholder_requirements.md](./00_stakeholder_requirements.md) and [01_mission.md](./01_mission.md)

The system is a small, file-driven pipeline plus a static published site. There is no
backend service to operate: documents are processed offline in batches, results are stored
locally, and only a flat JSON dataset and a single HTML page are published.

## Guiding principles

- **Offline batch, static delivery.** Heavy work (document conversion, AI extraction) runs
  locally on demand. The public artifact is a static site — cheap to host, nothing to keep
  running, no secrets in production.
- **AI drafts, human verifies.** Every AI output is a first draft that an expert corrects
  before it becomes authoritative. The data format must stay easy to inspect and edit by hand.
- **Reproducible & resumable.** Each stage is idempotent and skips already-processed inputs,
  so a batch can be re-run safely after adding decisions or fixing a single record.
- **Source-linked.** Every record keeps an interactive link to the original decision so any
  field can be checked against the source.

## Pipeline (`code/`)

| Stage | Script | Purpose |
|-------|--------|---------|
| 1. Ingest | `01_transform_raw_to_md.py` | Convert raw decision files into clean Markdown. |
| 2. Extract | `02_summarize_decisions.py` | Use the Claude API to produce summaries and the structured Art. 106 schema; store to SQLite. |
| 3. Export | `03_export_to_json.py` | Export verified records from SQLite to `docs/decisions.json` for the site. |

### Language & runtime
- **Python 3.13**, dependencies isolated in a local `venv/` (git-ignored).

### Document ingestion
- **[Docling](https://github.com/docling-project/docling)** (`docling` 2.x) — converts `.docx`
  to Markdown, preserving headings and tables.
- **LibreOffice (headless `soffice`)** — pre-converts legacy `.doc` and `.rtf` to `.docx`,
  which Docling does not ingest directly.

### AI extraction & summarization
- **Anthropic Claude API** via the official `anthropic` Python SDK.
- **Model:** latest Claude Opus (`claude-opus-4-x`) for legal-grade Ukrainian-language
  extraction. The system prompt fixes the role (Ukrainian judicial-discipline analyst) and a
  strict output schema so results parse deterministically.
- **Prompting:** a fixed schema aligned to Art. 106 of the Law "On the Judiciary and the
  Status of Judges", capturing qualification, conduct, and sanction at the complaint → ДП →
  ВРП stages, plus the фабула / суть / ключові висновки summaries.

### Storage
- **SQLite** (`data/decisions.db`) — the working store of extracted records, keyed by
  decision filename. Idempotent upserts make the extract stage resumable.
- **Reference data:** `data/round2/decisions to web-links.xlsx` maps each decision number to
  its public ВРП URL; read with **openpyxl** / **pandas** and joined during export.

### Published site (`docs/`, GitHub Pages)
- **Static HTML/CSS/vanilla JavaScript** — a single `index.html` with no build step and no
  framework. It `fetch`es `decisions.json` and renders, searches, and filters client-side.
- **Hosting:** GitHub Pages serves the `docs/` directory directly.

## Data layout

```
data/                         # git-ignored: build inputs & local artifacts
  round2/
    raw_data/                 # source .docx / .doc / .rtf decisions
    md/                       # Markdown produced by stage 1
    decisions to web-links.xlsx
  decisions.db                # SQLite working store (stage 2)
docs/                         # published by GitHub Pages
  decisions.json              # dataset consumed by the site (stage 3)
  index.html                  # the application
code/                         # the pipeline scripts
constitution/                 # SDD documents (requirements, mission, this file, roadmap)
```

## What is deliberately *not* in the stack

- **No server / database service in production.** Nothing to host beyond static files.
- **No client-side AI or API keys in the browser.** All AI runs offline during the build; the
  API key lives only in the local environment (`ANTHROPIC_API_KEY`), never in the repo or site.
- **No heavyweight frontend framework.** The dataset is small and read-only; a single page is
  enough.
