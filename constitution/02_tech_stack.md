# Tech Stack

> Last updated: 2026-07-30
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

Each stage selects its own acts from the register by act number, and the three sets partition
the corpus exactly: 486 + 329 + 125 = 940, no overlap.

Every stage reads the register through `register.py` and works **newest act first**. The stages
used to glob the Markdown directory and sort it, which sorts by act serial as a *string* — so
`--limit 50` extracted acts 1004–1049 from mid-2025 rather than the 50 most recent. Order now
comes from `Дата прийняття`, so a partial run leaves the recent end covered. `--only STEM …`
overrides the order to name specific acts, which is how a whole case gets backfilled: an ухвала
and the рішення it opens are six to eighteen months apart, so no recent window contains both.

Stage 24 additionally skips ВРП acts that quote no palate decision number — 14 of 125. Those are
ВККСУ подання про звільнення, complaints against disciplinary inspectors, and висновки про заходи
щодо забезпечення незалежності суддів: real ВРП acts, but not reviews of anything. The check is
free (it reads the same text the model would have been sent) and runs *before* the API call.

### Phase 3 — Merge (`3x`)

Assemble acts into proceedings and publish. **Stage 31 is not written yet** — see
[04_spec_proceedings.md](./04_spec_proceedings.md).

| Stage | Script | Purpose |
|-------|--------|---------|
| 31 | `31_merge_proceedings.py` *(planned)* | Resolve judges and build one record per **proceeding** (judge × complaint) from `rulings` + `decisions` + `reviews`. |
| 32 | `32_export_to_json.py` | Export records from SQLite to `docs/decisions.json` for the site, attaching each decision's ухвала and ВРП review via `joins.py`. `--output` writes elsewhere, so a batch can be reviewed in the UI before it is published. |

Until stage 31 exists, `joins.py` does the decision-centred half of the merge: the рішення ДП is
the record, with its ухвала and its ВРП review attached. Two rules keep those joins honest. **A
null key never joins** — four acts carry no complaint number (two name the complaint only by
complainant, one is a ВККСУ referral), and matching them on "both are null" silently linked all
four to each other. **The register's `Ключ справи` is not the key** — it strips the letter prefix
and the middle segment, so `М-6/19/7-22` collapses to `6/7-22`, a key shared by 36 unrelated acts.
The join uses the full complaint number *and* requires a judge in common; a decision's judge is
matched to *their own* entry in the ухвала, with no fallback to the first entry, because
attributing one judge's misconduct to another is the worst failure this system can produce.

Shared rule modules carry no stage number, because they are libraries rather than steps:

| Module | What it owns |
|---|---|
| `extraction_schema.py` | the three schemas, the shared vocabularies, the union budget, and `clip_for_model()` |
| `act_numbers.py` | who issued an act, which chamber, and which decision a review reviews |
| `register.py` | one ordered read of the register — newest act first, plus `--only` selection |
| `joins.py` | attaching an ухвала and a ВРП review to the рішення they belong to |
| `compare_models.py` | field-by-field A/B of two models' extractions of the same acts |
| `extract_runner.py` | the loop all three extraction stages run: parallel dispatch, upsert, usage accounting |

### The extraction loop: concurrency and accounting

Stages 21, 22 and 24 differ only in which acts they select, which schema they enforce and which
table they write; everything around that — skip-if-done, try/except, upsert, progress line — was
copied three times. `extract_runner.py` owns it once, which is why parallelism and usage
accounting could be added in one place instead of three.

- **`--workers N` (default 6).** Extraction is I/O-bound — nearly all wall-clock is spent waiting
  on the API — so threads help and processes would not. Measured: 6 ухвали in **76 seconds** at
  `--workers 6`, against roughly 6 minutes sequentially. Lower it if the API starts returning 429.
- **Only the main thread touches SQLite.** Workers call the API; results come back through
  `as_completed()` and are written by the main thread. SQLite serialises writers, so a pool of
  writing threads buys `database is locked` retries and no throughput. Each row is committed as it
  lands, so an interrupted run keeps everything already finished.
- **`max_retries=8`** on the client, above the SDK default of 2. An 862-act run will meet a 429 or
  an overloaded response eventually, and losing an act to one is pure waste.
- **`--budget N` is a ceiling in dollars on the whole database**, not on one run. Acts are
  submitted `--workers` at a time rather than all at once, because the budget can only be
  enforced at a submission boundary and a queue of 400 already-submitted calls has none. Spend is
  read back from the per-row `usage` blobs (`spent_so_far()`), so the ceiling survives a restart:
  a run stopped at \$45 and resumed does not spend \$45 again. Acts dropped by a `precheck` cost
  nothing and do not count against it. This is what makes a corpus run against a fixed pot of
  credit stop itself instead of failing act after act on a 400.
- **Every row records what it cost and which model wrote it** — `usage` is a JSON blob
  (`input_tokens`, `output_tokens`, cache counters, `model`) rather than columns, so a new field in
  the API response needs no migration. `python code/extract_runner.py [db]` prints the per-table
  totals and flags mixed provenance. Rows written before this existed have `usage NULL`; the column
  is added automatically to older databases by `ensure_schema()`.

Recording the model per row is the durable fix for the provenance problem that made mixing Opus
and Sonnet output dangerous: a corpus can now say which model produced each record, instead of
depending on someone remembering when the default changed.

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
- **Model:** `claude-sonnet-5` on every extraction stage, with adaptive thinking. The system
  prompt fixes the role (Ukrainian judicial-discipline analyst). `MAX_TOKENS` is 16000
  throughout — it caps thinking *and* response together, and the per-judge arrays make the
  response longer than the single-judge schema did.
- **Why Sonnet and not Opus.** Both models extracted the same 20 acts (13 ухвали, 5 рішення ДП,
  2 ВРП перегляди) into separate databases; `code/compare_models.py` compared them field by
  field. They agreed on **140 of 145** structured fields, and — the property that matters most —
  named **the same judges in every act**. Of the five disagreements, one was a schema limitation
  (an act whose operative part states both «відмовити у притягненні» *and* «провадження
  припинити», where `outcome` allows one), two were a single Opus error (a ground the act never
  mentions), and two were a single Sonnet error (an inspector proposal inferred from the palate's
  decision). One substantive mistake each, on a sample where one field is 0.7% — enough to show
  the models are comparable, not enough to rank them. Sonnet costs ~40% less at list and ~60%
  less at the introductory rate, and tokenizes this corpus identically (2.41 chars/token,
  measured with `count_tokens`), so the saving is the price ratio with no token penalty.
- **Text is never clipped.** `MAX_CHARS` is 500 000, above the largest act in the corpus
  (429 497 chars), so every act reaches the model whole. It was 160 000, which truncated the
  *tail* — and a ВРП act states its outcome last. In act 617/2дп/15-26 the operative paragraph
  begins at character 184 572 of 185 491, so the clip removed the sanction and nothing else:
  the record came back with a null sanction for a judge the palate had moved to dismiss.
  `clip_for_model()` survives as a guard for an act longer than any yet seen, and keeps the
  head *and* the tail rather than the head alone.
- **No prompt caching.** `cache_control` was set on the system prompt of stages 22 and 24 on the
  theory that an identical prompt across a batch would turn hundreds of prefills into cache
  reads. Measurement disproved it: `cache_read_input_tokens` was 0 on every call while
  `cache_creation_input_tokens` was ~15 700. The cached prefix is not the system prompt
  (1 755 tokens) — it is dominated by the per-act schema, whose complaint-number enum is rebuilt
  for every act, so the prefix differs each call and can never be read back. The only effect was
  the 1.25× write premium. Removed; verified `cache_creation_input_tokens` is now 0.
- **Cost — measured, not estimated (2026-07-29).** 387 acts cost **\$42.97**: 14.9M input and
  1.27M output tokens, **\$0.111 per act**, at Sonnet 5's introductory \$2/\$10 per MTok. The
  per-act figure is steady across act types (рішення \$0.117, ухвали \$0.111, ВРП \$0.135) and
  across the run, so it forecasts well: multiply by acts remaining. At that rate the corpus as it
  stood — 912 unextracted acts, up from 862 because ingestion keeps adding — prices at **~\$91**.
  `PRICES` in `extract_runner.py` carries the **introductory** rate, which expires **2026-08-31**;
  after that the same run costs 1.5× (\$3/\$15), so re-check the table before trusting an estimate
  made now. Note that **39% of the input is schema, not evidence**: ~14 000 tokens of JSON Schema
  ride along on every call, comparable to the act itself. That is the price of the enum constraint
  that stops the model inventing grounds and join keys, and it is the largest remaining
  optimisation.
- **`--max-tokens` (stage 22).** `MAX_TOKENS` caps thinking *and* JSON together, so a long
  multi-judge ухвала can exhaust it and return a record cut off mid-string. `1161_10.06.2026`
  (129k chars, 7 judges) needed **22 305 output tokens** and failed three times at the 16 000
  default. Above 16 000 the SDK refuses a non-streaming call it estimates will outlive the HTTP
  timeout, so a raised ceiling routes through `messages.stream()`; the default path is unchanged.
  A `stop_reason` of `max_tokens` now raises *«truncated at max_tokens=…»* rather than letting
  `json.loads` report an unterminated string 9 000 characters in — the fix is a bigger ceiling,
  not a parser.
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
    `"106-2 безпідставне затягування розгляду справи"`) plus a free-text
    `note` for nuance. The enum covers **all 25 підстав** of ст. 106 part one, including the six
    subpoints that were absent until 2026-07-29 — see *The Art. 106 enum* below;
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
- **Removed — the stopgap loader.** `23_load_manual_extractions.py` loaded hand-drafted records
  for when no API key was available. Both halves of its premise are gone: a key is configured,
  and its 32 records are in the pre-per-judge shape (`judge_name` flat, no `judges[]`). Loading
  them now would inject legacy-shape rows into a per-judge corpus — the shape that silently
  skewed the first Opus-vs-Sonnet comparison until `compare_models.py` learned to exclude it.
  Those 32 acts are inside the corpus window and the corpus run re-extracts them properly.
  `data/reference/manual_extractions.json` is kept as provenance for the records currently
  published on the site.

### The Art. 106 enum

`ART106_GROUNDS` is the vocabulary every act type is filtered by, so a defect in it is a defect
in the whole dataset. Three were found by auditing the extracted corpus on 2026-07-29 and fixed
the same day; all three are worth remembering, because each was invisible in the output.

- **It covered 19 of the statute's 25 підстав.** Missing: 106-7 (конфлікт інтересів), 106-12
  (недоброчесна поведінка / невідповідність рівня життя), 106-14, 106-14-1, 106-16, 106-18. A
  ground with no enum value does not fail — the model writes it into the free-text `note`, where
  no facet can reach it. Notes said so outright: *«не встановила ознак проступку за пунктом 12
  частини першої статті 106…»*. Re-extracting 35 affected acts turned **17 mentions of 106-12**
  from prose into a filterable ground, enough to rank it 9th of 25 corpus-wide.
- **One label welded two unrelated grounds together.** `106-19` read *порушення правил
  самовідводу / недостовірне декларування* — пункт 1д bolted onto пункт 19, with 1д already
  holding its own value. Both halves were in live use, so the facet returned a mixed bag. It now
  reads *недостовірні твердження в декларації доброчесності*. `106-9` was reworded in the same
  pass, because adding 106-16 and 106-18 would have left three overlapping «неподання декларації»
  values for the model to guess between.
- **Structured outputs are not an absolute guarantee.** 13 of 1 580 ground mentions (0.8%) came
  back differing from their enum member only in the case of the first letter. A reader cannot see
  it; an exact-match facet lists the same ground twice. `26_normalize_grounds.py` folds such
  values back deterministically — case- and whitespace-insensitively, and **only** onto an actual
  enum member; anything that does not fold is reported and left alone, since silently rewriting a
  real disagreement into conformity would be worse than the drift.

**Rule for changing the enum.** The first seven labels are frozen — round-2 extractions and
`docs/decisions.json` carry them verbatim. Outside those seven a reword is allowed **only
together with re-extraction of every act carrying the old label**: a stored value that is no
longer an enum member is worse than a bad label, because nothing downstream can validate it.
Appending is always safe, but only reaches records extracted afterwards.

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
                              #   NOT in git — a binary that changes nightly and cannot be
                              #   reviewed; dataset/ is the readable copy
dataset/                      # committed: the extracted records as JSON (stage 33)
  decisions.json rulings.json reviews.json
  schemas/                    # the JSON Schema each was extracted against
  manifest.json README.md     # both generated, so counts cannot drift
docs/                         # published by GitHub Pages
  decisions.json              # dataset consumed by the site (stage 32)
  meta.json                   # currency stamp rendered as «Оновлено …» (stage 32)
  index.html                  # the application
code/                         # the pipeline scripts (1x ingestion, 2x extraction,
                              #   3x merge and export)
                              #   + extraction_schema.py, act_numbers.py, register.py,
                              #     joins.py, compare_models.py, run_daily.sh
deploy/                       # systemd unit + timer for the nightly cycle
constitution/                 # SDD documents (requirements, mission, this file, roadmap, specs)
```

## The nightly cycle

`code/run_daily.sh` runs the **whole pipeline** — ingest (11 → 12 → 13 → 14), extract what is
new (22 → 24 → 21), export (32, 33), then commit and push — driven by a systemd timer
(`deploy/vrp-ingest.timer`) at **02:00 Kyiv time**. The zone is named in the calendar spec, so
the job does not drift when Ukraine changes clocks even though the host runs on UTC. A missed
run (machine off) is caught up once at next boot, and `run_daily.sh` holds a `flock` so a long
conversion is never overtaken by the next night's run. Output goes to the journal and to
`data/logs/daily-YYYY-MM-DD.log`.

GitHub Pages serves `main:/docs`, so the push **is** the deployment. The publish step stages
only generated artefacts, refuses to run on any branch but `main` — committing elsewhere would
stop the site updating with no error anywhere — and on a rejected push rebases once before
failing loudly.

### Why an unattended job may now spend money

Extraction used to sit outside the nightly run because it costs money per act and produces AI
drafts. The first objection was about *volume*: with the corpus unextracted, an unattended run
could have spent ~$58 in a night. That is no longer the shape of the work — the corpus front is
extracted, so a night's new acts are two or three, about thirty cents.

It is fenced twice all the same, because the failure being guarded against is monetary and
silent:

- **`--new-since-days N`** selects on «Вперше побачено», which stage 11 stamps only for acts a
  scrape genuinely discovered; seeded history carries an empty stamp on purpose, and re-reading
  an act never re-stamps it. An act with no stamp is never "new" — the safe direction to fail,
  since a missed act is a visible gap while a wrong filter is an invoice.
- **`--limit N`** caps the act count whatever the register says, so even a register rebuild that
  re-stamped every row could not produce more than ~$13 of calls.

The AI-drafts / human-verifies rule is **not** repealed by this. Every published record still
carries its source link and the site still says the summaries are unverified drafts. What
changed is that the draft now reaches the reader without a human relaying it — verification
becomes a correction workflow (M7) rather than a publication gate.

Extraction order is ухвали → ВРП → рішення ДП, the reverse of the corpus run: a decision
published tonight should already carry the opening act it links to rather than acquiring it a
night later.

Stage 14 must stay inside the nightly job, and after stage 12: stage 12 rebuilds
`hcj_acts_selected.xlsx` from scratch each run, so the complaint-number columns are lost and
re-added nightly. It costs nothing — regex over local Markdown, no API.

`SKIP_EXTRACT=1` and `SKIP_PUBLISH=1` turn the corresponding steps off for a manual run.

## What is deliberately *not* in the stack

- **No server / database service in production.** Nothing to host beyond static files.
- **No client-side AI or API keys in the browser.** All AI runs offline during the build; the
  API key lives only in the local environment (`ANTHROPIC_API_KEY`, e.g. a git-ignored `.env`),
  never in the repo or site.
- **No heavyweight frontend framework.** The dataset is small and read-only; a single page is
  enough.
