# Tech Stack

> Last updated: 2026-07-29
> Status: Active
> Source: derived from [00_stakeholder_requirements.md](./00_stakeholder_requirements.md) and [01_mission.md](./01_mission.md)
> Downstream: [03_roadmap.md](./03_roadmap.md), [04_spec_proceedings.md](./04_spec_proceedings.md)

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

The pipeline has **three phases**. The first digit of a stage number names its phase, so a
script's place in the flow is readable from its filename alone.

### Phase 1 — Ingestion (`1x`)

Turn the public register into local Markdown. Runs unattended every night.

| Stage | Script | Purpose |
|-------|--------|---------|
| 11 | `11_scrape_register.py` | Scrape the official register at `hcj.gov.ua/acts` into one growing table of acts. |
| 12 | `12_select_and_download.py` | Pick the disciplinary acts out of the register and download their source files. |
| 13 | `13_transform_raw_to_md.py` | Convert raw act files into clean Markdown. |
| 14 | `14_extract_complaint_numbers.py` | Read the «номер дисциплінарної скарги» out of each act by rule and write it to the register — the key that joins a рішення to its ухвала. |

### Phase 2 — Extraction (`2x`)

Turn each act into a structured record. Costs money per act; run by hand.

| Stage | Script | Purpose |
|-------|--------|---------|
| 21 | `21_extract_decisions.py` | Claude API: summaries + the structured Art. 106 schema for **рішення дисциплінарної палати** (325 acts); store to SQLite. |
| 22 | `22_extract_rulings.py` | Same for **ухвали про відкриття справи** (485 acts), against their own schema. |
| 24 | `24_extract_reviews.py` | Same for **рішення ВРП про перегляд** (125 acts) — the second-instance act type. |
| 23 | `23_load_manual_extractions.py` | Stopgap loader for hand-drafted records in the same schema, for when no API key is available. |

Each stage selects its own acts from the register by act number, and the three sets partition
the corpus exactly: 485 + 325 + 125 = 935, no overlap.

### Phase 3 — Merge (`3x`)

Assemble acts into proceedings and publish. **Stage 31 is not written yet** — see
[04_spec_proceedings.md](./04_spec_proceedings.md).

| Stage | Script | Purpose |
|-------|--------|---------|
| 31 | `31_merge_proceedings.py` *(planned)* | Resolve judges and build one record per **proceeding** (judge × complaint) from `rulings` + `decisions` + `reviews`. |
| 32 | `32_export_to_json.py` | Export records from SQLite to `docs/decisions.json` for the site. Today it exports decision records, flattening the lead judge into the fields the current UI expects. |

Shared rule modules carry no stage number, because they are libraries rather than steps:
`extraction_schema.py` (the schemas) and `act_numbers.py` (who issued an act, and which act a
review reviews).

Phase 1 runs unattended every night; phases 2 and 3 are run by hand — see
[Daily ingest](#daily-ingest) below.

### The act number: who issued an act, and what it reviews

Every act is numbered `NNNN/<body>/15-YY`, and the middle segment names the issuing body:
`1дп`/`2дп`/`3дп` for the First/Second/Third disciplinary palate, `0` for the ВРП itself sitting
in review. Two things follow, both previously guessed at:

- **There are three act types, not two.** 125 of the 450 «рішення» are numbered `…/0/15-…` —
  they are the ВРП reviewing a palate decision, not a palate deciding. Extracted against the
  рішення schema they described a document that does not exist, which is why every «Перегляд від
  ВРП» field came back empty. They now have `REVIEW_SCHEMA` and stage 24.
- **The chamber is stated, not inferred.** `act_numbers.chamber_of()` derives it, so the model
  is not asked to re-read what the number already says. Checked against the 32 records extracted
  before this change: the rule agrees with the model on all of them.

A review names the decision it reviews in its own title — «Про залишення без змін рішення Другої
Дисциплінарної палати ВРП від 4 лютого 2026 року № 151/2дп/15-26 …» — and **all 112 review acts
in the corpus do this**, which makes it the most reliable join in the dataset. Like the complaint
number it is found by rule and offered to the model as an enum: one review act quotes six palate
decision numbers, and another quotes `335/2дп/15-25` beside the correct `335/2дп/15-26`.

### The complaint number: how a рішення finds its ухвала

The two act types that describe one disciplinary case carry different act numbers — the ухвала
that opens the case and the рішення that decides it are numbered independently. What they share
is the incoming number of the complaint that started it, quoted in the text of both:

    Л - 1720 / 0 / 7 - 25
    │   │     │   │    └─ year the complaint was registered
    │   │     │   └────── register index = who complained
    │   │     └────────── sub-number (доповнення, пояснення…)
    │   └──────────────── serial number in that register
    └──────────────────── first letter of the complainant's surname (individuals only)

The register index says who complained, and that is what decides whether a number is a
complaint at all: **7** (an individual) and **13** (a state body — НАЗК, НАБУ, прокуратура) always
are; **8** is general incoming mail that carries complaints from officials alongside court letters
and ВККС references, so it is accepted only where the surrounding text describes a complaint;
**6** is the judge's own file (пояснення, appeals) and never qualifies.

Stage 14 writes two columns to `data/register/hcj_acts_selected.xlsx`:

- **Номер дисциплінарної скарги** — the numbers as the act writes them, for a human reader.
- **Ключ справи** — `serial/index-year`, dropping the sub-number and the letter. This is what
  documents are actually joined on: one complaint accumulates sub-numbers as it is supplemented,
  and conversion sometimes loses the letter.

An act can legitimately carry many numbers — an об'єднана дисциплінарна справа folds several
complaints together, and the largest in the corpus lists 18. Stage 12 rebuilds the register from
scratch on each run, so stage 14 must run after it; the columns are refreshed, never duplicated.

The number is extracted by rule rather than by the model **because it is a join key**: a
mis-transcribed digit does not look wrong, it silently fails to join or joins to the wrong case.
Where the extraction stages need it, the numbers stage 14 found are passed into the request as a
per-document `enum`, so the model chooses among real numbers and cannot invent one.

### The register and what is selected from it

Stage 11 builds an index of the register — one row per act, with its number, type, date,
title, `Ознака до документа`, the link to the act's page and to its source file. The table
`data/register/hcj_acts.xlsx` is never replaced, only merged into: rows are keyed on the
act's node URL (the only unique key — several acts legitimately share a number, date and
title), and rows a merge has not seen before are stamped in `Вперше побачено`, which
doubles as the change log of each run. A daily run re-reads only the last 30 days, wide
enough to catch acts the HCJ publishes days after they were adopted.

Stage 12 narrows the register to the disciplinary corpus:

- `Ознака до документа` = *Результати розгляду питань щодо притягнення суддів до
  дисциплінарної відповідальності*, then
- every **Рішення**, plus
- a **Ухвала** only if its title mentions *відкриття дисциплінарної справи* — the act that
  opens a case. The far more numerous ухвали about *відмову у відкритті*, extensions of
  review deadlines and returned complaints are left out.

Each selected act is saved as `<номер>_<дата>.<ext>` (e.g. `1503_22.07.2026.docx`) — the stem
the whole pipeline keys on, through Markdown and into SQLite. Every document is fetched and
converted **once**: a file already downloaded, or already converted to Markdown, is skipped.

### Language & runtime
- **Python 3.13**, dependencies isolated in a local `venv/` (git-ignored).

### Register scraping
- **requests + BeautifulSoup/lxml** against the register's exposed Drupal view filters,
  paginated 20 rows at a time and sorted by document number — the default date ordering is
  not stable across requests, which both duplicates and silently skips records.
- **TLS:** `hcj.gov.ua` serves its leaf certificate without the intermediate CA. The scraper
  supplies the missing intermediate itself (`code/hcj_intermediate.pem`, or fetched live via
  the certificate's AIA extension) so verification stays real; it falls back to unverified
  only with a loud warning, or never at all under `--strict`.

### Document ingestion
- **[Docling](https://github.com/docling-project/docling)** (`docling` 2.x) — converts `.docx`
  to Markdown, preserving headings and tables.
- **LibreOffice (headless `soffice`)** — pre-converts legacy `.doc` and `.rtf` to `.docx`,
  which Docling does not ingest directly.

### AI extraction & summarization
- **Anthropic Claude API** via the official `anthropic` Python SDK.
- **Model:** `claude-opus-5` on every extraction stage, with adaptive thinking. The system
  prompt fixes the role (Ukrainian judicial-discipline analyst). `MAX_TOKENS` is 16000
  throughout — it caps thinking *and* response together, and the per-judge arrays make the
  response longer than the single-judge schema did.
- **Schema-enforced output.** Extraction sets `output_config.format` to the canonical JSON
  Schema in `code/extraction_schema.py` (dumped to `extraction_schema.json`,
  `ruling_schema.json` and `review_schema.json`). Structured outputs guarantee the result
  conforms to the schema and parses deterministically — no free-form JSON, no markdown fences.
- **Union budget.** Structured outputs allow at most **16** union-typed (nullable / `anyOf`)
  parameters per schema; past that the API rejects the request. Nesting per-judge blocks
  multiplies them fast, so `note` is a required plain string rather than `string|null`, and
  running `python code/extraction_schema.py` fails loudly if any schema exceeds the budget.
- **Three schemas, one vocabulary.** `DECISION_SCHEMA` covers рішення ДП, `RULING_SCHEMA`
  ухвали про відкриття справи, and `REVIEW_SCHEMA` рішення ВРП про перегляд. They share
  `ART106_GROUNDS` and `SANCTION_TYPES` so the act types stay comparable, but none of them is a
  smaller version of another.
- **The judge is the unit of observation.** Every schema carries a `judges[]` array, and
  qualification, conduct, sanction and outcome hang off each judge rather than off the act.
  67 acts name more than one judge, and the outcome routinely differs *within* one act — one
  decision punishes судді Підпалого and in the same operative part refuses to punish two judges
  of an appellate court. An act-level field would have to pick one and discard the rest.
- **Fixed schema** aligned to Art. 106 of the Law "On the Judiciary and the Status of
  Judges". Per decision it captures:
  - act metadata: `decision_num`, `date`, `short_name`. The `chamber` is *derived* from the act
    number, not asked of the model;
  - per judge — ПІБ, court, position;
  - **кваліфікація діяння** per stage (скарга → ДП) as a list of grounds drawn
    from a **fixed enum** (`ART106_GROUNDS` — short labels like
    `"106-2 безпідставне затягування розгляду справи"`, corpus-only) plus a free-text
    `note` for nuance;
  - **conduct** summary per stage;
  - **стягнення** per judge, twice over: `sanction` keeps the act's own wording, and
    `sanction_type` normalizes it to the ст. 109 vocabulary (`попередження` / `догана` /
    `сувора догана` / подання про відсторонення, переведення, звільнення / `стягнення не
    накладено`). The distinction between догана and сувора догана is a different sanction with
    different consequences — one month of withheld доплати against three — so it is a facet,
    not something to be recovered later by matching prose. `summary.essence` must name the
    sanction in full for the same reason;
  - summaries: **суть** (essence), **фабула** (facts), **ключові висновки** (conclusions);
  - **complaint_number** — chosen from the numbers stage 14 found in that act, never typed.
- **The ухвала schema records what the decision cannot.** A ухвала opens a case, so it has no
  sanction — but it holds the front half of the story, captured **per judge** as grounds at
  three stages: `requested` (what the complainant asked for), `opened` (what the palate
  actually opened on), and `rejected` (grounds the palate expressly declined). Set against a
  decision's `qualification.dp`, that answers *по чому відкрилися vs по чому реально було
  притягнуто*. It also captures who complained (name, organisation, and a `complainant_type`
  that cross-checks against the complaint number's register index), the disciplinary inspector
  and what they proposed — the palate overriding its inspector is a meaningful signal — the
  panel, the underlying court case, and the complaint's arrival date, which with the ухвала's
  own date gives the time a case waited.
- **The review schema records the second instance.** `REVIEW_SCHEMA` captures which decision is
  under review (chosen from numbers found by rule), who appealed — a judge contesting a sanction
  and a complainant contesting a refusal are opposite situations — and, per judge, the
  `review_outcome` (залишено без змін / скасовано повністю / частково / змінено стягнення) with
  the sanction **in force after review**. A quashed sanction must never read as standing.
- **Stopgap loader:** `23_load_manual_extractions.py` loads hand-drafted records in the
  same schema when no API key is available; once a key is set, stage 21 regenerates them.

### Storage
- **SQLite** (`data/decisions.db`) — the working store, keyed by act filename: `decisions`
  for рішення ДП (stage 21), `rulings` for ухвали (stage 22), `reviews` for рішення ВРП
  (stage 24), and — once phase 3 exists — `proceedings` for the assembled records. Idempotent
  upserts make every stage resumable.
  **Gotcha:** the extract stages skip rows that already carry `data`, so a schema change does
  not reach already-extracted records until their rows are cleared.
- **Source links** come from the register: the export joins each record to its selected-acts
  row by filename stem, taking the official number, the document type and the public ВРП URL.
  The round-2 spreadsheet `data/reference/decisions to web-links.xlsx` remains only as a
  fallback for records that predate the register.
- **`doc_type`** (`Рішення` / `Ухвала`) is carried into the exported JSON. It is not an AI
  field: an ухвала opening a case has no sanction and no ВРП review stage, and without the
  type those empty fields read as failed extractions.

### Published site (`docs/`, GitHub Pages)
- **Static HTML/CSS/vanilla JavaScript** — a single `index.html` with no build step and no
  framework. It `fetch`es `decisions.json` and renders, searches, and filters client-side.
- **Responsive, no framework.** Desktop shows a sticky filters sidebar beside the results; on
  narrow screens (≤860px) the layout collapses to one column and the filters become a
  collapsed-by-default panel (toggle to expand), so results are visible immediately on phones.
- **Hosting:** GitHub Pages serves the `docs/` directory directly.

## Data layout

```
data/                         # git-ignored: build inputs & local artifacts
  register/
    hcj_acts.xlsx             # the whole register, one growing table (stage 11)
    hcj_acts_selected.xlsx    # the disciplinary acts picked out of it (stage 12)
  acts/
    raw/                      # source .docx / .doc / .rtf acts (stage 12)
    md/                       # Markdown produced by stage 13
  reference/                  # round-2 leftovers: web-links, manual extractions
  logs/                       # one log per nightly run, kept 30 days
  decisions.db                # SQLite working store: decisions / rulings / reviews (phase 2)
docs/                         # published by GitHub Pages
  decisions.json              # dataset consumed by the site (stage 32)
  index.html                  # the application
code/                         # the pipeline scripts (1x ingestion, 2x extraction, 3x merge)
                              #   + extraction_schema.py, act_numbers.py, run_daily.sh
deploy/                       # systemd unit + timer for the nightly ingest
constitution/                 # SDD documents (requirements, mission, this file, roadmap, specs)
```

## Daily ingest

`code/run_daily.sh` chains the ingestion phase — stages 11 → 12 → 13 → 14 — driven by a systemd timer
(`deploy/vrp-ingest.timer`) at **02:00 Kyiv time**. The zone is named in the calendar spec,
so the job does not drift when Ukraine changes clocks even though the host runs on UTC. A
missed run (machine off) is caught up once at next boot, and `run_daily.sh` holds a `flock`
so a long conversion is never overtaken by the next night's run. Output goes to the journal
and to `data/logs/daily-YYYY-MM-DD.log`.

Extraction (phase 2) and merge/publish (phase 3) stay **outside** the nightly job on purpose:
extraction costs money per act, and what it produces is an AI draft that an expert verifies
before it may appear on the live site. Automating that would break the AI-drafts /
human-verifies rule. Stage 14 must stay inside the nightly job, and after stage 12: stage 12
rebuilds `hcj_acts_selected.xlsx` from scratch each run, so the complaint-number columns are
lost and re-added nightly. It costs nothing — regex over local Markdown, no API.

## What is deliberately *not* in the stack

- **No server / database service in production.** Nothing to host beyond static files.
- **No client-side AI or API keys in the browser.** All AI runs offline during the build; the
  API key lives only in the local environment (`ANTHROPIC_API_KEY`, e.g. a git-ignored `.env`),
  never in the repo or site.
- **No heavyweight frontend framework.** The dataset is small and read-only; a single page is
  enough.
