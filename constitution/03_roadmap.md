# Roadmap

> Last updated: 2026-06-07
> Status: Active
> Source: derived from [00_stakeholder_requirements.md](./00_stakeholder_requirements.md), [01_mission.md](./01_mission.md), and [02_tech_stack.md](./02_tech_stack.md)

The product grows in phases, each adding capability while keeping the
AI-drafts / human-verifies model and the offline-batch + static-site architecture.

## Phase 1 — MVP: AI summaries (✅ done)

Validate that AI can draft useful summaries of disciplinary-chamber decisions.

- [x] Ingest pipeline: raw `.docx` → Markdown (Docling).
- [x] AI summary per decision: **суть рішення**, **фабула**, **ключові висновки**.
- [x] SQLite store + JSON export.
- [x] Static published site: searchable table of summaries.
- [x] Scope: ~30 sample disciplinary-chamber decisions.

**Outcome:** end-to-end pipeline proven; summaries are readable and broadly accurate.

## Phase 2 — Structured extraction (🚧 current)

Move from free-text summaries to the structured schema the stakeholders asked for, so the
practice becomes filterable and comparable.

- [x] Ingest legacy formats: `.doc` and `.rtf` via headless LibreOffice → `.docx`.
- [x] Join the decision → public-URL mapping (web-links spreadsheet) for interactive source links.
- [x] Define a strict JSON Schema for extraction (`code/extraction_schema.py`) and enforce it
  via a forced strict tool call.
- [x] Extract the structured Art. 106 schema per decision:
  - metadata: ПІП of the judge, court, `chamber`, `decision_num`, `date`, `short_name`.
  - **Qualification** per stage (complaint → ДП → ВРП) as a **fixed enum** of Art. 106 grounds
    (short labels) plus a free-text note.
  - **Conduct summary** of the judge — at the complaint, ДП decision, and ВРП review.
  - **Sanction (стягнення)** — at the ДП decision and ВРП review.
- [x] Keep the AI summaries (суть / фабула / висновки) alongside the structured fields.
- [x] Rebuild the site as a per-decision detail view with faceted filtering
  (by Art. 106 ground, sanction, court, judge, ДП vs ВРП stage) and a source link on every record.
- [ ] Scope: the round-2 batch (~32 decisions, `.docx/.doc/.rtf`) — run extraction with an API key.

**Exit criteria:** structured fields populated for the round-2 batch; site filters by ground,
sanction, court, and stage; every record links to its ВРП source.

## Phase 3 — Verification workflow & quality

Make expert correction first-class and measure quality, per the success metrics.

- [ ] Verification state per record (draft → verified) with reviewer and timestamp.
- [ ] An editing path for experts to correct fields without hand-touching JSON.
- [ ] Track **extraction accuracy** (expert-correction rate) and **expert time saved**.
- [ ] Confidence / "needs review" flags on low-certainty AI fields.

## Phase 4 — Full ДП→ВРП chain

- [ ] Link each disciplinary-chamber decision to its ВРП review decision where one exists.
- [ ] Show the complete accountability outcome (qualification and sanction across stages) in
  one view.

## Phase 5 — Scale to the full corpus

- [ ] Process the complete corpus of **600+** ДП + ВРП decisions.
- [ ] Batch throughput, cost controls, and incremental re-runs as new decisions are published.
- [ ] Trends & analytics: aggregate views of grounds, conduct, and sanctions over time.

## Phase 6 — Beyond the disciplinary chambers (vision)

- [ ] Expand from disciplinary practice to **all categories of ВРП practice**, growing into a
  comprehensive, structured, verifiable resource on the work of the High Council of Justice.

## Cross-cutting, ongoing

- Keep AI-drafts / human-verifies as the rule for any published field.
- Keep the pipeline reproducible, resumable, and source-linked.
- Track the latest Claude model and update the extraction prompt/schema as requirements evolve.
