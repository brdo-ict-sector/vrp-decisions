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

The project is a small data pipeline plus a static web app:

1. **Convert** — original decisions (`.docx` / `.doc` / `.rtf`) are converted to
   clean Markdown text.
2. **Summarize** — each decision is sent to the Claude API, which extracts the
   fields above against a fixed schema and writes them to a local database.
3. **Publish** — the records are exported to JSON, joined with source-document
   links, and served by a single-page web app (filter by chamber, Article 106
   grounds, and more).

The current dataset covers **32 first-instance disciplinary decisions** as a
working sample; the full corpus is 600+ decisions.

## Project layout

- `code/` — the three-stage pipeline (convert → summarize → export)
- `constitution/` — the project specification: stakeholder requirements, mission,
  tech stack, and roadmap
- `docs/` — the published web app (`index.html`) and data (`decisions.json`)

Source documents, the local database, and credentials are intentionally **not**
committed to this repository.

---

*This is a sandbox / proof-of-concept. Summaries are AI-generated drafts and have
not yet been verified by a human expert; always consult the linked original
decision as the authoritative source.*
