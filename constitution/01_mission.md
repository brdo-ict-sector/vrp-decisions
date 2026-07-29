# Product Mission

> Last updated: 2026-07-29
> Status: Active
> Source: derived from [00_stakeholder_requirements.md](./00_stakeholder_requirements.md)
> Downstream: [02_tech_stack.md](./02_tech_stack.md), [03_roadmap.md](./03_roadmap.md)

## Pitch

An AI-assisted system that automates the structured preprocessing and summarization
of the disciplinary practice of Ukraine's High Council of Justice (Вища рада правосуддя,
ВРП). It turns long disciplinary decisions into a uniform, verifiable, and navigable body
of practice — фабула, суть, key conclusions, the Art. 106 qualification, the судді's
conduct, and the sanction — so that legal professionals can study disciplinary practice
in a fraction of the time. The work fulfills Ukraine's EU-integration commitment to
systematize and review (узагальнення) ВРП practice.

## Users

### Primary Customers

- **ВРП members & disciplinary bodies** — decide disciplinary cases and need consistent,
  comparable access to prior practice.
- **Judges & their assistants** — need to understand disciplinary practice, grounds, and
  risks relevant to their work.
- **Lawyers & legal scholars** — advocates, academics, and NSJ trainers who analyze and
  cite disciplinary practice.

### User Personas

**Disciplinary Chamber Member** (ВРП)
- **Role:** Decides disciplinary cases and reviews chamber decisions
- **Need:** Quickly find how comparable conduct was qualified and sanctioned across prior
  decisions to support consistency.

**Judge / Judicial Assistant**
- **Role:** Sitting judge or supporting staff
- **Need:** Understand what conduct leads to liability under Art. 106 and the resulting
  sanctions, in plain language with a link to the source.

**Lawyer / Legal Scholar**
- **Role:** Advocate, academic, or trainer
- **Need:** A structured, citable corpus to analyze trends and reference specific decisions.

## The Problem

### Узагальнення is slow and labor-intensive

Producing the узагальнення requires experts to read long disciplinary decisions and
manually draft the фабула, суть, and key conclusions, while also extracting structured
facts (judge, court, qualification, conduct, sanction) for each decision — at every stage
of the ДП→ВРП chain. This is a major drain on scarce expert time and does not scale to a corpus
of 935 acts for 2025–2026 alone.

**Our Solution:** AI drafts the structured preprocessing for every decision according to a
fixed schema; an expert then verifies and corrects it before it becomes authoritative.

## Differentiators

- **Structured to the disciplinary-liability framework.** Unlike the raw full text in the
  public registry (ЄДРСР) or the VRP website, output is mapped to purpose-built fields
  aligned with Art. 106 of the Law "On the Judiciary and the Status of Judges" — the
  qualification of the act, the судді's conduct, and the sanction, captured at the
  complaint, ДП, and ВРП stages.
- **Plain-language AI summaries.** Concise фабула / суть / ключові висновки and a summary
  of the судді's assessed conduct, instead of long legal texts.
- **The whole proceeding, not the loose act.** A disciplinary proceeding is up to three
  documents, published separately and numbered independently: the **ухвала** that opens it, the
  **рішення** of the palate that decides it, and the **рішення ВРП** that may review that. They
  are assembled per judge and per complaint, so one record shows what was complained of, what
  the palate agreed to open on, what the judge was actually held liable for, what sanction
  followed, and whether it survived review.
  *(Planned — phase 3; see [04_spec_proceedings.md](./04_spec_proceedings.md).)*
- **Expert-verified and citable.** AI is the drafter, a human is the verifier; every record
  carries an interactive link to the original decision.

## Key Features

### Structured Extraction (per рішення дисциплінарної палати)
Recorded **per judge**: one decision can punish one judge and refuse to punish another.
- Decision metadata: date, disciplinary chamber (ДП), decision number, and the official
  short title (short_name)
- Each judge's full name (ПІП), court, and position
- Interactive link to the source decision
- Qualification of the act under Art. 106 — at the complaint and at the ДП decision, drawn from
  a controlled vocabulary (a fixed enum of Art. 106 grounds) for consistent filtering
- Summary of the судді's assessed conduct — at the complaint and at the ДП decision
- Sanction (стягнення) per judge, both in the act's own wording and normalized to the Art. 109
  vocabulary, so догана and сувора догана never blur together

### Structured Extraction (per ухвала про відкриття справи)
The opening act is not a smaller decision — it holds the front half of the case:
- Grounds at **three** stages: what the complainant **requested**, what the palate actually
  **opened** on, and what it expressly **rejected** — the narrowing between them is the finding
- Who complained (name, organization, and a type drawn from a controlled vocabulary)
- The disciplinary inspector and what they proposed — a palate overriding its inspector is a
  meaningful accountability signal
- The panel, the underlying court case, and the complaint's arrival date

### Structured Extraction (per рішення ВРП про перегляд)
The second instance, and its own act type:
- Which palate decision is under review, and who took it there — a judge contesting a sanction
  and a complainant contesting a refusal are opposite situations
- Per judge: what the ВРП did with the decision, and the sanction **in force after review**

### Proceeding Assembly
- Ухвала, рішення and ВРП review assembled into one record per **proceeding** — one judge, one
  complaint — so a reader follows a complaint from filing to final outcome
- The comparison that only the assembly can produce: **по чому відкрилися vs по чому реально
  було притягнуто**

### AI Summarization
- Concise фабула, суть рішення, and ключові висновки of the disciplinary chambers,
  generated by AI as the first draft.

### Human-in-the-Loop Verification
- AI output is reviewed and corrected by a specialist before publication; the source link
  is always provided so any record can be checked against the original.

### Practice Exploration (published site)
- Per-decision detail view with all structured fields and the source link
- Faceted filtering — by Art. 106 ground, sanction, court, judge, and ДП vs ВРП stage
- Trends & analytics — aggregate views of grounds, conduct, and sanction patterns over time

## Success Metrics

- **Extraction accuracy** — a low expert-correction rate on AI-generated preprocessing.
- **Expert time saved** — sharp reduction in the effort to preprocess each decision vs. the
  fully manual process.

Scale: the MVP targeted ~30 decisions to validate the approach. The register has since defined
the real corpus — **935 disciplinary acts for 2025–2026** (450 рішення + 485 ухвали про
відкриття справи) — and earlier years are still to be backfilled.

## Vision

Beyond phase 1, expand from the disciplinary chambers to **all categories of ВРП practice**,
growing into a comprehensive, structured, and verifiable resource on the work of the High
Council of Justice.
