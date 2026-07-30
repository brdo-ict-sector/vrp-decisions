# VRP Disciplinary Practice — AI-Assisted Summaries

**Live site:** https://brdo-ict-sector.github.io/vrp-decisions/

## What this is

Ukraine's High Council of Justice (Вища рада правосуддя, **VRP**) holds judges
accountable through disciplinary proceedings. The resulting decisions are public,
but they are long, written in dense legal language, and scattered across official
registries. Reading and comparing them is slow expert work.

This project turns that body of decisions into a **structured, searchable, and
source-linked corpus**. For each decision, AI drafts a short plain-language
summary and pulls out the key facts into a consistent set of fields. A simple web
app then lets anyone browse and filter the results, with a direct link back to the
original document. It directly supports Ukraine's EU-integration commitment to
systematize and review (узагальнення) VRP disciplinary practice.

> **Important:** AI is the *drafter*, a human expert is the *verifier*. The
> summaries published here are AI-generated drafts pending expert review — useful
> for orientation, not yet authoritative.

## Who it's for

- **VRP members and disciplinary bodies** — to quickly see how comparable conduct
  was qualified and sanctioned in earlier cases, for consistency.
- **Judges and their assistants** — to understand, in plain language, what conduct
  leads to liability and what sanctions follow.
- **Lawyers, scholars, and trainers** — to analyze trends and cite specific
  decisions from a structured, navigable source.

## What each decision record contains

- **Metadata** — date, disciplinary chamber, decision number, and official short title
- **Every judge and court** the act names — one decision can rule on several judges
  and decide differently for each
- **Qualification under Article 106** of the Law "On the Judiciary and the Status
  of Judges" — drawn from a fixed list of all 25 grounds so cases can be filtered
  and compared
- **The judge's assessed conduct** and the **sanction** imposed, normalized to the
  Article 109 vocabulary so догана and сувора догана never blur together
- **Plain-language summaries** — the facts (фабула), the essence (суть), and the
  key conclusions (висновки)
- **The opening ruling and the review**, where they are in the corpus: what the
  complainant asked for, what the chamber agreed to open on, and whether the VRP
  changed the outcome on review
- **An interactive link** to the original decision

## How it works

The project is a small data pipeline plus a static web app. The pipeline has three
phases:

**1. Ingestion** — the official register at `hcj.gov.ua/acts` is scraped into an
index of what documents exist; the disciplinary acts are picked out of it (every
*рішення*, plus the *ухвали* that open a disciplinary case) and downloaded; the
originals (`.docx` / `.doc` / `.rtf`) are converted to clean Markdown; and the
complaint number is read out of each act by a plain rule, because it is the key
that later joins the two halves of a case.

**2. Extraction** — each act is sent to the Claude API, which fills in a fixed
schema and writes the result to a local database. The three act types have three
separate schemas: a *ухвала* records what was asked for and what the chamber
agreed to open on, a *рішення* records what the judge was actually held liable for
and the sanction, and a *рішення ВРП* records what survived review.

**3. Merge** — the acts are joined (the *ухвала* on the complaint number, the
review on the decision number it quotes), exported to JSON, and served by a
single-page web app with faceted filtering.

### The nightly cycle runs the whole thing

Every night at **02:00 Kyiv time** a systemd timer runs the complete loop
unattended: scrape the register → extract the acts that are new → re-export →
commit and push, which republishes the site. Nobody has to do anything for the
day's acts to appear.

Extraction is fenced so that an unattended job can never run away with the API
bill. It only considers acts stamped as newly discovered by a recent scrape —
seeded history carries no such stamp and can never qualify — and an act-count
limit caps it regardless. A normal night is two or three acts, costing well under
a dollar.

## Current state

| | |
|---|---|
| **Corpus ingested** | 937 acts for 2025–2026 — 485 ухвали, 327 рішення ДП, 125 рішення ВРП |
| **Extracted** | 163 рішення ДП · 206 ухвали · 43 рішення ВРП |
| **Published** | all 163 рішення ДП, 55 with their opening ruling attached, 17 with a VRP review |
| **Coverage** | complete from **03.11.2025** onward for рішення ДП, 05.11.2025 for ухвали, 23.12.2025 for ВРП reviews |
| **Automation** | full cycle nightly, unattended |
| **Cost** | ~$0.11 per act; the corpus so far cost about $47 |

Extraction is a **complete sweep back to a cut-off date, not a sample** — nothing
inside the covered window was skipped or cherry-picked. Roughly half the corpus
(everything before November 2025) has not been extracted yet; that is a budget
question rather than an engineering one.

Because an opening ruling and the decision that closes the case are typically
6–18 months apart, a window reaching back to late 2025 contains relatively few
complete pairs. 151 extracted ухвали have no decision inside the window and so
appear in the dataset but not on the site.

The merge phase (one record per *proceeding* — one judge × one complaint) is
specified but not yet built.

## The data

The extracted records are committed to this repository as plain JSON, next to the
schemas that constrained them:

```
dataset/decisions.json      рішення дисциплінарних палат
dataset/rulings.json        ухвали про відкриття справи
dataset/reviews.json        рішення ВРП за результатами перегляду
dataset/schemas/            the JSON Schema for each of the three
dataset/README.md           record shape, join keys, and caveats
```

`docs/decisions.json` is a different file: it is what the site loads — decisions
only, with the related acts already joined onto each record.

Regenerate the dataset from the local database with:

```bash
venv/bin/python code/33_export_dataset.py
```

## Project layout

- `code/` — the pipeline, numbered by phase (`1x` ingestion, `2x` extraction,
  `3x` merge and export)
- `deploy/` — the systemd timer and service that run the nightly cycle
- `constitution/` — the project specification: stakeholder requirements, mission,
  tech stack, roadmap, and per-phase specs
- `dataset/` — the extracted records as JSON, with their schemas
- `docs/` — the published web app (`index.html`), its data (`decisions.json`) and
  its currency stamp (`meta.json`)

Source documents (`data/acts/`), the working database, and credentials are
intentionally **not** committed.

## Running it by hand

```bash
code/run_daily.sh                  # the full cycle
SKIP_EXTRACT=1 code/run_daily.sh   # ingest only, no API spend
SKIP_PUBLISH=1 code/run_daily.sh   # everything except the push
```

Extraction needs `ANTHROPIC_API_KEY` in a `.env` file at the repository root.

---

*This is a sandbox / proof-of-concept. Summaries are AI-generated drafts and have
not yet been verified by a human expert; always consult the linked original
decision as the authoritative source.*
