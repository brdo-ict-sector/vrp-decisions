# Roadmap

> Last updated: 2026-07-30
> Status: Active
> Source: derived from [00_stakeholder_requirements.md](./00_stakeholder_requirements.md),
> [01_mission.md](./01_mission.md), [02_tech_stack.md](./02_tech_stack.md), and
> [04_spec_proceedings.md](./04_spec_proceedings.md)

## Vocabulary

Two words were doing the same job in earlier drafts. From now on:

- **Phase** — one of the three parts of the pipeline: **ingestion → extraction → merge**.
  Phases are permanent; they are what the code is organized by, and the stage number's first
  digit names the phase (`11–14` ingestion, `21–24` extraction, `31–33` merge and export).
- **Milestone** — a unit of delivery (M1, M2, …). Milestones come and go; each one advances
  one or more phases and has explicit exit criteria.

## The three phases

| Phase | Stages | What it produces | State |
|-------|--------|------------------|-------|
| **1 · Ingestion** | `11_scrape_register` → `12_select_and_download` → `13_transform_raw_to_md` → `14_extract_complaint_numbers` | Every disciplinary act as Markdown, plus its complaint number(s) in the register | ✅ **Operating.** Runs nightly, unattended. 940/940 acts converted. |
| **2 · Extraction** | `21_extract_decisions` (ДП рішення), `22_extract_rulings` (ухвали), `24_extract_reviews` (ВРП перегляди) | One structured record per act in SQLite, against `DECISION_SCHEMA` / `RULING_SCHEMA` / `REVIEW_SCHEMA` | 🚧 **Recent half extracted, and self-maintaining at the front.** 165/329 ДП рішення, 207/486 ухвали, 43/125 ВРП переглядів — 415 records. Unbroken from the newest act back to **03.11.2025** (рішення), **05.11.2025** (ухвали), **23.12.2025** (ВРП). New acts are now extracted the night they appear; the ~525 acts *behind* the front still need roughly **\$58**. |
| **3 · Merge and export** | `31_merge_proceedings` *(not written)*, `32_export_to_json`, `33_export_dataset` | One record per **proceeding** — one judge × one complaint, with its ухвала, рішення and ВРП review attached | ⛔ **Merge not built.** `32` exports decision records with the related acts joined onto each, flattening to a lead judge for the current UI; `33` writes the reviewable JSON dataset. |

Phase 1 is done and self-maintaining. Phase 2 now maintains its own front automatically and
is a money question only for the backlog behind it. Phase 3 is the remaining engineering
work, and it is what makes the product answer the question the stakeholders actually asked —
see [M6](#m6--proceedings-merge).

**Three act types, not two.** The act number states who issued it (`…/2дп/15-…` a palate,
`…/0/15-…` the ВРП in review), and it partitions the corpus exactly: 486 ухвали + 329 ДП
рішення + 125 ВРП рішення = 940. The ВРП reviews were previously extracted as if they were
chamber decisions, which is why every «Перегляд від ВРП» field came back empty.

**Coverage is a prefix, not a sample.** Within its window the extraction is a census: acts
were taken newest-first, so nothing inside was skipped or chosen. What looks like holes in
the ВРП reviews is 11 acts stage 24 declines before spending a call, because they review no
palate decision at all.

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

### M4 · Extraction across the corpus 🚧 *(front done, backlog outstanding)*

The corpus is ingested; the recent half is extracted and published, and the front now
maintains itself nightly (M5). What stops the rest is credit rather than code.

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
- [x] **Corpus run under a fixed budget** (2026-07-29). \$50 of credit against a ~\$91 corpus, so
      the run was ordered newest-first in four waves that advance all three act types together —
      finishing one type and starving the others would have left the recent end incoherent.
      387 acts for \$42.97, then 35 re-extracted for \$3.89 (below). Zero unrecovered failures.
- [x] **Budget ceiling in the runner** (`--budget`), enforced at the submission boundary and read
      back from stored `usage`, so it survives restarts. It never had to trip — the wave plan and
      the ceiling converged — but it is what makes an unattended run against finite credit safe.
- [x] **`sanction_type` verified, not assumed.** All 80 judge entries carrying a sanction name it
      in `summary.essence`, and догана is never stated where сувора догана was imposed. That was
      the stakeholder's complaint (8 of 9 failing before); it is closed.
- [x] **Art. 106 enum completed to all 25 підстав**, one conflated label split, one disambiguated,
      and 35 affected acts re-extracted — 17 mentions of 106-12 recovered from free text. See
      `02_tech_stack.md` → *The Art. 106 enum*.
- [ ] Extract the remaining ~525 acts (roughly \$58 at the measured \$0.111/act, or 1.5× that
      after Sonnet 5's introductory pricing ends **2026-08-31**).
- [x] Cost controls: resumability (skip-if-done), per-row token+model accounting, a `--budget`
      ceiling, and a measured **\$0.111 per act** to forecast and check the invoice against.
- [x] Re-export and publish — **done 2026-07-30**. `docs/decisions.json` carries all 165 рішення
      ДП (56 with their ухвала attached, 17 with a ВРП перегляд), replacing the round-2 sample
      of 32. The 151 extracted ухвали with no decision inside the window are in `dataset/` but
      have no card of their own: "a case was opened" is not yet an answer to anything.

**Exit criteria:** every act in the register has a structured record or a logged error;
`sanction_type` populated for every рішення; the published dataset covers the whole 2025–2026
corpus rather than a 32-record sample. **The last of these is met**; the first two wait on the
backlog.

**Where a resumed run picks up.** `--limit N` means "the next N *not-yet-extracted* acts, newest
first", so continuing needs no bookkeeping — the first gap in each type is `2189_22.10.2025`
(рішення), `2322_05.11.2025` (ухвали), `2799_23.12.2025` (ВРП).

**Known gap:** all three extract stages skip rows that already carry `data`, so a schema change
does not reach already-extracted records — clear the affected rows before re-running. This is the
same property that makes a long run resumable, so it is a trade-off rather than a defect.

### M5 · The automated daily cycle ✅

Close the loop. Ingest already ran unattended; extraction and publishing did not, on the
grounds that extraction costs money per act and publishing put unverified drafts on a live
site. Both objections expired once the corpus was extracted and published: what a night adds
is no longer 500 acts but the two or three the ВРП issued that day.

- [x] `run_daily.sh` extended from ingest-only to the whole cycle: scrape → extract new →
      export → commit → push. GitHub Pages serves `main:/docs`, so the push *is* the deploy.
- [x] **`--new-since-days` on all three extraction stages.** «Вперше побачено» is stamped only
      for acts a scrape genuinely discovered — seeded history carries an empty stamp on
      purpose — so the selector reaches last night's arrivals and cannot reach the backlog
      behind them. An act with no stamp is never "new", which is the safe direction to fail:
      a missed act is a visible gap, a wrong filter is an invoice.
- [x] `--limit` caps the act count regardless of what the register says. Two fences, because
      the failure mode being fenced against is monetary and silent.
- [x] Extraction order reversed relative to the corpus run — ухвали → ВРП → рішення ДП — so a
      decision published tonight already carries the opening act it links to.
- [x] Export runs even when nothing was extracted: it refreshes the «Оновлено» stamp, and a
      join can change when the act on the other end of it arrives.
- [x] Publish step commits only generated artefacts, refuses to run off `main`, and rebases
      once on a rejected push before failing loudly.
- [x] `32_export_to_json.py` also writes `docs/meta.json`; the page renders «Оновлено
      DD.MM.YYYY» from it. Stamped at export time, never computed in the browser — a page
      deriving "yesterday" from the visitor's clock would claim to be current on a day the
      pipeline never ran.
- [x] `33_export_dataset.py` writes `dataset/` — the extracted records as reviewable JSON,
      committed, unlike the binary database. It is the only off-host copy of work that cost
      real money.
- [x] Verified end to end by a manual run on 2026-07-30 that found 3 genuinely new acts,
      extracted them, re-exported and published.

**Exit criteria met:** a day's acts reach the live site with no human action.

**Deliberately still manual:** extracting the pre-November-2025 backlog. That is a spending
decision, and it belongs to a person.

### M6 · Proceedings merge

Turn three piles of acts into one story per **proceeding** — one judge × one complaint. This is
phase 3, and it does not exist yet.

- [ ] `31_merge_proceedings.py` — resolve judges, build proceedings, record edges and states.
- [ ] `32_export_to_json.py` reads all three tables and exports proceeding records.
- [ ] Site view of a proceeding: what was requested, what was opened, what was decided, what
      sanction, and whether the ВРП changed it.
- [ ] Expose «по чому відкрилися vs по чому реально було притягнуто» — a ухвала's
      `grounds.opened` against its рішення's `qualification.dp`, **for that judge**.

Measured over the whole corpus (935 acts, as it stood on 2026-07-29) before building:

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

### M7 · Verification workflow & quality

Make expert correction first-class and measure it, per the success metrics in the mission.

- [ ] Verification state per record (draft → verified) with reviewer and timestamp.
- [ ] An editing path for experts to correct fields without hand-touching JSON.
- [ ] Track **extraction accuracy** (expert-correction rate) and **expert time saved**.
- [ ] Confidence / "needs review" flags on low-certainty AI fields, starting with the 43 acts
      that carry no complaint number.

### M8 · Depth & breadth

- [ ] Backfill years before 2025 (one-off `--full` scrape).
- [ ] Trends & analytics: grounds, conduct, and sanctions over time.
- [ ] **Vision:** expand from disciplinary practice to *all categories of ВРП practice*.

## Cross-cutting, ongoing

- AI drafts / human verifies, for any published field.
- Pipeline stays reproducible, resumable, and source-linked.
- Stage numbering stays phase-aligned: a new script gets its phase's digit.
- Track the latest Claude model; revisit prompts and schemas as requirements evolve.
