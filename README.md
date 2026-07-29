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
- **Judge and court** under review
- **Qualification under Article 106** of the Law "On the Judiciary and the Status
  of Judges" — drawn from a fixed list of grounds so cases can be filtered and compared
- **The judge's assessed conduct** and the **sanction** imposed
- **Plain-language summaries** — the facts (фабула), the essence (суть), and the
  key conclusions (висновки)
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
schema and writes the result to a local database. Decisions and opening rulings
have separate schemas: a ruling records what was *asked for* and what the chamber
agreed to *open* on, a decision records what the judge was actually held liable
for and the sanction.

**3. Merge** — the two are joined on the complaint number into one record per
case, exported to JSON, and served by a single-page web app (filter by chamber,
Article 106 grounds, sanction, and more).

Ingestion runs **automatically every night at 02:00 Kyiv time**, so newly
published acts are collected without anyone doing anything. Extraction and
publishing stay manual: the AI output is a draft, and a human decides when it is
ready to go on the site.

**Current state:** ingestion is complete and running — **935** disciplinary acts
for 2025–2026 (450 decisions + 485 opening rulings) are downloaded and converted.
Extraction has so far covered a **32-decision working sample**, which is what the
published dataset contains; the rest is queued. The merge phase is specified but
not yet built. Earlier years are still to be backfilled.

## Project layout

- `code/` — the pipeline, numbered by phase (`1x` ingestion, `2x` extraction,
  `3x` merge)
- `deploy/` — the systemd timer that runs the nightly ingestion
- `constitution/` — the project specification: stakeholder requirements, mission,
  tech stack, roadmap, and per-phase specs
- `docs/` — the published web app (`index.html`) and data (`decisions.json`)

Source documents, the local database, and credentials are intentionally **not**
committed to this repository.

---

*This is a sandbox / proof-of-concept. Summaries are AI-generated drafts and have
not yet been verified by a human expert; always consult the linked original
decision as the authoritative source.*
