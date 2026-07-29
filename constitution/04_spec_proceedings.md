# Spec — Phase 3: Proceedings

> Last updated: 2026-07-29
> Status: Draft — not implemented
> Source: derived from [00_stakeholder_requirements.md](./00_stakeholder_requirements.md) and
> [01_mission.md](./01_mission.md); scheduled as [M5](./03_roadmap.md#m5--proceedings-merge)
> Supersedes: `04_spec_case_merge.md` (case grain), replaced after the corpus showed the
> relation is judge-level, not case-level

## Why

Ingestion and extraction work one **act** at a time. But nobody wants to read acts — they want
to know what happened to a complaint about a judge. That story is spread across up to three
documents, published months apart, numbered independently:

| act | what it establishes |
|---|---|
| **Ухвала** ДП | what the complainant asked for, what the palate agreed to open on, what it refused |
| **Рішення** ДП | what the judge was actually held liable for, and the sanction |
| **Рішення ВРП** | whether that survived review, and what sanction stands afterwards |

Phase 3 assembles them. Until it exists, the corpus is a pile of documents; after it, it is a
record of disciplinary accountability.

## The grain: one judge × one complaint

The unit of observation is **not** the act and **not** the case. It is the **proceeding**:
one judge, one complaint.

Two facts in the corpus force it:

- **One act, several judges.** 67 acts name more than one — an ухвала opens against three
  judges of the same court at once. The outcome then diverges *inside a single act*: «Про
  притягнення судді Підпалого В.В. … про відмову у притягненні суддів Апеляційного суду…».
  An act-level outcome would have to pick one judge and discard the others.
- **One judge, several complaints.** The same judge recurs across unrelated complaints over
  time. A judge-level record would merge misconduct that has nothing to do with itself.

Verified against the extraction: a two-judge ухвала returns different `requested` and `opened`
grounds per judge (act `1494_22.07.2026` — six grounds requested against one judge, two against
the other). The per-judge grain is not theoretical.

## Three act types, distinguished by rule

The act number states who issued it — `NNNN/{1дп|2дп|3дп|0}/15-YY`, where `0` is the ВРП
sitting in review. `code/act_numbers.py` parses it, and the corpus partitions exactly:

| issuer | acts | stage |
|---|---|---|
| ДП — ухвала | 485 | 22 |
| ДП — рішення | 325 | 21 |
| ВРП — рішення | 125 | 24 |

No overlap, nothing left over. The chamber (Перша/Друга/Третя) comes from the same number, so
it is never asked of the model.

## The two edges, and how much they can be trusted

| edge | key | coverage | method |
|---|---|---|---|
| ухвала → рішення ДП | complaint number (`Ключ справи`) | 97% of ухвали, 95% of ДП рішення | rule (stage 14) + model chooses among candidates |
| **рішення ДП → рішення ВРП** | **ДП decision number quoted in the review's title** | **112 of 112 review acts** | rule (`act_numbers`) + model chooses |

The second edge is the most reliable link in the dataset — exact, structured, and never typed.
59 of 112 resolve to an act we hold; **all 53 misses cite decisions from 2020, 2021 and 2024**,
outside the corpus window. That is a backfill gap, not a quality problem.

Both keys are handed to the model as an enum rather than transcribed, for the same reason: a
join key fails silently. The value of that showed up immediately in testing — one review act
quoted six palate decision numbers, another quoted `335/2дп/15-25` alongside the correct
`335/2дп/15-26`.

Judge identity is the weak edge, and the one that will cost expert time. Ukrainian acts decline
surnames («стосовно судді Козленко Г.О.», «суддів Шкорупеєва Д.А.»), so the extracted string is
a label, not a key. Matching needs `surname-lemma + initials + court`, and a wrong match is the
worst failure mode in the system: it attributes one judge's misconduct to another.

## Data model

```
judges        judge_id, surname, initials, court, normalized_key
complaints    complaint_key (serial/index-year), numbers[], complainant, complainant_type, filed_at
acts          act_id (stem), issuer (ДП/ВРП), chamber, doc_type, number, date, url, extracted record

proceedings   proceeding_id            ← GRAIN: (complaint_key × judge_id)
              state
              opening_act  → ухвала      grounds requested / opened / rejected, ruling outcome
              chamber_act  → рішення ДП  qualification (скарга, ДП), conduct, sanction, sanction_type, outcome
              review_act   → рішення ВРП review_outcome, qualification, sanction in force after review

act_judges    act_id × judge_id         (one act, several judges)
act_complaints act_id × complaint_key   (об'єднані справи — up to 18 in one act)
edges         from_act, to_act, kind, key_value, method, confidence
overrides     human corrections, applied last, never overwritten by a re-run
```

`state` is derived, never guessed:

| state | meaning |
|---|---|
| `відкрито` | ухвала only — the case is open, no decision yet |
| `вирішено ДП` | palate decided, no review |
| `переглянуто ВРП` | review exists; the sanction in force is the review's |
| `без ухвали` | decision held, opening act outside the corpus window |
| `не приєднано` | act carries no complaint number — cannot join at all |

## Requirements

- **R1** — One proceeding per (complaint_key × judge) pair actually named in an act. Not the
  cross-product: an act with 3 judges and 5 complaints yields the pairs the act states, not 15.
- **R2** — A proceeding carries every act that touches it, each with number, date, issuer,
  chamber, `doc_type`, and source URL.
- **R3** — Every proceeding has an explicit `state` from the table above.
- **R4** — For proceedings with both halves, the record exposes the comparison directly: the
  ухвала's `grounds.opened` beside the рішення's `qualification.dp` for **that judge**, and the
  difference both ways (opened-but-not-punished, punished-but-not-opened).
- **R5** — Where a review exists, the sanction in force is the review's, not the palate's, and
  both are visible. A quashed sanction must never be presented as standing.
- **R6** — Sanctions reach the proceeding both as the act's wording and as `sanction_type`
  (ст. 109 enum), so догана and сувора догана are distinguishable without parsing prose.
- **R7** — Every edge records how it was derived (`decision_number`, `complaint_key`,
  `judge_match`, `manual`) and its confidence. A provisional link must be visibly provisional.
- **R8** — Unmatched acts and unresolved judges are exported, not dropped, and counted in the
  run summary. Silence is indistinguishable from a bug.
- **R9** — Human overrides are applied last and survive any re-run. Joins are subject to
  "AI drafts, human verifies" exactly as fields are.
- **R10** — The stage is idempotent and free: it reads SQLite and the register, calls no API,
  and can be re-run whenever extraction adds records.
- **R11** — Where an act's extracted `complaint_number` disagrees with what stage 14 found in
  its text, the rule wins and the disagreement is logged.

## Stages

| Stage | Script | Purpose |
|-------|--------|---------|
| 31 | `31_merge_proceedings.py` *(planned)* | Resolve judges, build proceedings from `rulings` + `decisions` + `reviews`, record edges and states. |
| 32 | `32_export_to_json.py` | Export proceedings (and their acts) for the site. Today it exports decision records with a lead-judge flattening for the current UI. |

## Open questions

1. **Multi-complaint acts.** Does an об'єднана справа appear under each complaint number it
   swallowed, or only its primary one? Lean: primary for counting, all numbers for lookup.
2. **Is a review the same proceeding or a new one?** Lean: the same proceeding advancing state —
   same judge, same complaint — with the review's own qualification recorded separately.
3. **The ~13 non-disciplinary ВРП acts** (ВККС подання про звільнення, complaints against
   disciplinary inspectors, заходи щодо забезпечення незалежності суддів) are about neither a
   judge's discipline nor a complaint. Recommend excluding them in stage 12 rather than
   carrying them into proceedings.

## Acceptance criteria

- [ ] Every act carrying a complaint number appears in at least one proceeding.
- [ ] The 43 acts without one appear as `не приєднано` and are listed in the run summary.
- [ ] Every multi-judge act produces one proceeding per judge, with that judge's own outcome.
- [ ] Every review act is attached to the decision it names, or logged as citing an act outside
      the corpus.
- [ ] For a proceeding under review, the sanction shown is the one in force after review.
- [ ] Re-running stage 31 twice produces byte-identical output.
