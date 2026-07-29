# Roadmap

> Last updated: 2026-07-29
> Status: Active
> Source: derived from [00_stakeholder_requirements.md](./00_stakeholder_requirements.md),
> [01_mission.md](./01_mission.md), [02_tech_stack.md](./02_tech_stack.md), and
> [04_spec_proceedings.md](./04_spec_proceedings.md)

## Vocabulary

Two words were doing the same job in earlier drafts. From now on:

- **Phase** — one of the three parts of the pipeline: **ingestion → extraction → merge**.
  Phases are permanent; they are what the code is organized by, and the stage number's first
  digit names the phase (`11–14` ingestion, `21–23` extraction, `31–32` merge).
- **Milestone** — a unit of delivery (M1, M2, …). Milestones come and go; each one advances
  one or more phases and has explicit exit criteria.

## The three phases

| Phase | Stages | What it produces | State |
|-------|--------|------------------|-------|
| **1 · Ingestion** | `11_scrape_register` → `12_select_and_download` → `13_transform_raw_to_md` → `14_extract_complaint_numbers` | Every disciplinary act as Markdown, plus its complaint number(s) in the register | ✅ **Operating.** Runs nightly, unattended. 935/935 acts converted. |
| **2 · Extraction** | `21_extract_decisions` (ДП рішення), `22_extract_rulings` (ухвали), `24_extract_reviews` (ВРП перегляди) | One structured record per act in SQLite, against `DECISION_SCHEMA` / `RULING_SCHEMA` / `REVIEW_SCHEMA` | 🚧 **Sampled, not run.** 5/325 ДП рішення, 14/485 ухвали, 4/111 ВРП переглядів (14 of the 125 ВРП acts review no palate decision and are skipped). Schemas rebuilt around the per-judge grain 2026-07-29; model switched to `claude-sonnet-5` after a 20-act A/B against Opus 5. 862 acts remain, estimated ~\$85. |
| **3 · Merge** | `31_merge_proceedings` *(not written)*, `32_export_to_json` | One record per **proceeding** — one judge × one complaint, with its ухвала, рішення and ВРП review attached | ⛔ **Not built.** `32` exports decision records only, flattening to a lead judge for the current UI. |

Phase 1 is done and self-maintaining. Phase 2 is a money question, not an engineering one.
Phase 3 is the remaining engineering work, and it is what makes the product answer the
question the stakeholders actually asked — see [M5](#m5--proceedings-merge).

**Three act types, not two.** The act number states who issued it (`…/2дп/15-…` a palate,
`…/0/15-…` the ВРП in review), and it partitions the corpus exactly: 485 ухвали + 325 ДП
рішення + 125 ВРП рішення = 935. The ВРП reviews were previously extracted as if they were
chamber decisions, which is why every «Перегляд від ВРП» field came back empty.

## Milestones

### M1 · MVP: AI summaries ✅

Validate that AI can draft useful summaries of disciplinary-chamber decisions.

- [x] Ingestion: raw `.docx` → Markdown (Docling).
- [x] AI summary per decision: **суть рішення**, **фабула**, **ключові висновки**.
- [x] SQLite store + JSON export.
- [x] Static published site: searchable table of summaries.
- [x] Scope: ~30 sample decisions.

**Outcome:** end-to-end pipeline proven; summaries readable and broadly accurate.

### M2 · Structured extraction of рішення ✅

Move from free text to the schema the stakeholders asked for, so practice becomes filterable.

- [x] Legacy formats `.doc` / `.rtf` via headless LibreOffice.
- [x] Source-URL join for interactive links on every record.
- [x] Strict JSON Schema (`code/extraction_schema.py`), enforced through structured outputs.
- [x] Per-decision: metadata; **кваліфікація** per stage (скарга → ДП → ВРП) as a fixed
      Art. 106 enum + note; **conduct** per stage; **стягнення** at ДП and ВРП.
- [x] Site rebuilt as a per-record detail view with faceted filtering.

**Exit criteria met** on the round-2 batch of 32 decisions.

### M3 · Ingestion at corpus scale ✅

Let the source define the corpus instead of a hand-assembled batch.

- [x] Scrape the official register (`hcj.gov.ua/acts`) into a growing index.
- [x] Nightly unattended run at 02:00 Kyiv (systemd timer), incremental by construction —
      every document is fetched and converted exactly once.
- [x] Rule-based complaint-number extraction (stage 14) writing the join key into the register.
- [x] `RULING_SCHEMA` + stage 22, so ухвали про відкриття справи are extracted as what they
      are rather than through a рішення-shaped schema.

**Outcome:** 935 acts for 2025–2026 (450 рішення + 485 ухвали) downloaded, converted, and keyed.

### M4 · Extraction across the corpus 🚧 *(current)*

The corpus is ingested; almost none of it is extracted.

- [x] Ухвала schema verified on a hand-checked sample (6 acts, 2026-07-29) — the
      `requested → opened → rejected` split reproduces the narrowing correctly.
- [x] **Distinguish догана from сувора догана** — stakeholder feedback, 2026-07-29. Schema
      field `sanction_type` (ст. 109 enum) plus a prompt rule requiring `summary.essence` to
      name the sanction. Ships with the re-run below.
- [x] **Per-judge grain in every schema.** 67 acts name more than one judge and decide
      differently for each; the old schemas forced a single `judge_name` and would have
      silently dropped the rest. Qualification, conduct, sanction and outcome now hang off
      `judges[]`. Verified on a two-judge ухвала returning different grounds per judge.
- [x] **`REVIEW_SCHEMA` + stage 24** for the 125 ВРП review acts, joined to the decision they
      review by the number quoted in their title.
- [x] **Chamber derived from the act number** (`act_numbers.py`) instead of being asked of the
      model; matches the model's previous answer on all 32 existing records.
- [x] Stage 21 confined to ДП рішення — it globbed all 935 Markdown files and would have
      extracted ухвали and reviews against the wrong schema.
- [x] Reconcile the model pinned by each extraction stage — all three now run `claude-sonnet-5`
      at `MAX_TOKENS` 16000, chosen over `claude-opus-5` on a 20-act A/B (140/145 fields agree,
      identical judge identification, ~40% cheaper). See `02_tech_stack.md` → Why Sonnet.
- [x] Order extraction newest-act-first (`register.py`); add `--only` to backfill whole cases.
- [x] Stop clipping act text (`MAX_CHARS` 500 000) — the old 160 000 tail-clip removed the
      operative part, and with it the sanction, on the 30 longest acts.
- [x] Skip the 14 ВРП acts that review no palate decision, before spending an API call.
- [x] Drop `cache_control` from stages 22/24 — measured 0 cache reads, 1.25× write premium.
- [x] Factor the shared extraction loop into `extract_runner.py`; add `--workers` (default 6,
      ~5× faster) and per-row usage + model accounting (`python code/extract_runner.py` reports).
- [x] Clear the 32 legacy decision rows so they pick up the new schema (done 2026-07-29).
- [x] Discard all Opus-extracted rows and re-key the working store to Sonnet output only
      (2026-07-29), so the corpus has one model's provenance rather than two.
- [ ] Run stage 21 over all 325 ДП рішення — **one** run, with every schema change included.
- [ ] Run stage 22 over all 485 ухвали, and stage 24 over all 125 ВРП переглядів.
- [x] Cost controls: resumability (skip-if-done), per-row token+model accounting, and a
      measured estimate (~$85 at introductory pricing) to check the invoice against.
- [ ] Re-export and publish.

**Exit criteria:** every act in the register has a structured record or a logged error;
`sanction_type` populated for every рішення; the published dataset covers the whole 2025–2026
corpus rather than a 32-record sample.

**Known gap:** all three extract stages skip rows that already carry `data`, so a schema change
does not reach already-extracted records — clear the affected rows before re-running. This is the
same property that makes a long run resumable, so it is a trade-off rather than a defect.

### M5 · Proceedings merge

Turn three piles of acts into one story per **proceeding** — one judge × one complaint. This is
phase 3, and it does not exist yet.

- [ ] `31_merge_proceedings.py` — resolve judges, build proceedings, record edges and states.
- [ ] `32_export_to_json.py` reads all three tables and exports proceeding records.
- [ ] Site view of a proceeding: what was requested, what was opened, what was decided, what
      sanction, and whether the ВРП changed it.
- [ ] Expose «по чому відкрилися vs по чому реально було притягнуто» — a ухвала's
      `grounds.opened` against its рішення's `qualification.dp`, **for that judge**.

Measured over all 935 acts before building:

| edge | key | coverage |
|---|---|---|
| ухвала → рішення ДП | complaint number | 97% of ухвали, 95% of ДП рішення |
| рішення ДП → рішення ВРП | decision number quoted in the review's title | **112 of 112** |

The ДП→ВРП edge is the most reliable link in the dataset. 59 of 112 resolve inside the corpus;
all 53 misses cite decisions from 2020, 2021 and 2024, so backfill closes them.

The complaint edge is many-to-many in both directions (`А-305/0/7-22` → 2 ухвали / 1 рішення;
`Ч-444/26/7-25` → 1 ухвала / 2 рішення), roughly half of each side has no counterpart inside
this time window, and **43 acts can never join** because no number appears in their text.

Full specification — grain, data model, states, requirements, open questions — in
[04_spec_proceedings.md](./04_spec_proceedings.md).

**Exit criteria:** a proceeding exists for every (judge × complaint) pair the acts name;
multi-judge acts produce one proceeding per judge with that judge's own outcome; unmatched acts
are visible as such rather than silently dropped; where a review exists, the sanction shown is
the one in force after review.

### M6 · Verification workflow & quality

Make expert correction first-class and measure it, per the success metrics in the mission.

- [ ] Verification state per record (draft → verified) with reviewer and timestamp.
- [ ] An editing path for experts to correct fields without hand-touching JSON.
- [ ] Track **extraction accuracy** (expert-correction rate) and **expert time saved**.
- [ ] Confidence / "needs review" flags on low-certainty AI fields, starting with the 43 acts
      that carry no complaint number.

### M7 · Depth & breadth

- [ ] Backfill years before 2025 (one-off `--full` scrape).
- [ ] Trends & analytics: grounds, conduct, and sanctions over time.
- [ ] **Vision:** expand from disciplinary practice to *all categories of ВРП practice*.

## Cross-cutting, ongoing

- AI drafts / human verifies, for any published field.
- Pipeline stays reproducible, resumable, and source-linked.
- Stage numbering stays phase-aligned: a new script gets its phase's digit.
- Track the latest Claude model; revisit prompts and schemas as requirements evolve.
