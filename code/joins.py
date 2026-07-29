"""Attaching an ухвала and a ВРП review to the рішення they belong to.

The рішення дисциплінарної палати is the record at the centre: it is where a judge
is actually held liable and a sanction imposed. An ухвала is what the case was
opened on, and a ВРП рішення is what survived review. Read alone, each is a
fragment; read together they answer the question the corpus exists to answer —
what was alleged, what the palate opened on, what it punished, and what stood.

This is the modest, decision-centred half of what `04_spec_proceedings.md` calls
stage 31. It does not build the proceedings grain (complaint × judge) or resolve
judges into a table; it attaches related acts to a decision so the site can show
them in one card.

Two rules keep the joins honest.

**A null key never joins.** Four acts in the current batch carry no complaint
number — two name the complaint only by complainant, one is a ВККСУ referral.
Matching them on "both are null" silently linked all four to each other. A join
key that fails silently is worse than a missing one, so empty keys are dropped
before matching, not after.

**The register's `Ключ справи` is not the key.** It strips the letter prefix and
the middle segment, so `М-6/19/7-22` becomes `6/7-22` — a key shared by 36
unrelated acts in the corpus. The full complaint number as it appears in the act
is the key, and even that is only accepted when the two acts also name a judge in
common. An ухвала attached to the wrong judge's decision is the worst failure the
system can produce: it attributes one judge's misconduct to another.
"""

import re

import act_numbers

# «Поліщук Андрій Сергійович (та його представник – адвокат …)» — the parenthetical
# is commentary, never part of the name.
_PAREN = re.compile(r"\s*[(（].*$")
_NON_NAME = re.compile(r"[^\w\s'’ʼ-]", re.UNICODE)


def judge_key(name: str) -> str:
    """`Шкорупеєв Дмитро Анатолійович` → `шкорупеєв|д.а.`

    Surname plus initials, which is as much identity as an act reliably gives.
    Court is compared separately: two judges can share a surname and initials, but
    almost never in the same court.
    """
    if not name:
        return ""
    cleaned = _NON_NAME.sub(" ", _PAREN.sub("", str(name))).strip().lower()
    parts = [p for p in cleaned.split() if p]
    if not parts:
        return ""
    surname, given = parts[0], parts[1:]
    initials = ".".join(p[0] for p in given[:2])
    return f"{surname}|{initials}." if initials else surname


def judge_keys(record: dict) -> set[str]:
    """Every judge named in an act, as comparable keys."""
    return {judge_key(j.get("name")) for j in (record.get("judges") or [])} - {""}


def complaint_keys(record: dict) -> set[str]:
    """The complaint numbers an act carries — primary plus об'єднані справи.

    Normalized only for case and whitespace. These numbers are never typed by the
    model (stage 14 finds them verbatim and they are handed over as an enum), so
    there is no transcription noise to repair here.
    """
    numbers = [record.get("complaint_number"), *(record.get("related_complaint_numbers") or [])]
    return {re.sub(r"\s+", "", str(n)).upper() for n in numbers if n and str(n).strip()}


def _act_date(record: dict, filename: str):
    """Sort key for an act: its stated date, else the date in its filename."""
    raw = record.get("date") or (filename.split("_", 1)[1] if "_" in filename else "")
    try:
        d, m, y = str(raw).split(".")
        return (int(y), int(m), int(d))
    except ValueError:
        return (0, 0, 0)


def _normalized_num(number: str) -> str:
    parsed = act_numbers.parse_act_number(number)
    return parsed["normalized"] if parsed else re.sub(r"\s+", "", str(number or "")).lower()


def find_ruling(decision: dict, dec_file: str, rulings: dict[str, dict]) -> dict | None:
    """The ухвала that opened this decision's case, or None.

    Requires a shared complaint number *and* a judge in common, and requires the
    ухвала not to postdate the decision. Where several ухвали qualify — a case can
    be opened, joined and re-opened — the latest one before the decision is taken,
    and the rest are counted so a reviewer can see the choice was not unique.
    """
    dec_complaints, dec_judges = complaint_keys(decision), judge_keys(decision)
    if not dec_complaints or not dec_judges:
        return None

    dec_date = _act_date(decision, dec_file)
    matches = []
    for filename, ruling in rulings.items():
        shared = dec_complaints & complaint_keys(ruling)
        if not shared or not (dec_judges & judge_keys(ruling)):
            continue
        if _act_date(ruling, filename) > dec_date:
            continue  # an ухвала cannot follow the decision it opened
        matches.append((_act_date(ruling, filename), filename, ruling, sorted(shared)))

    if not matches:
        return None
    _, filename, ruling, shared = max(matches, key=lambda m: m[0])
    return {
        "filename": filename,
        "record": ruling,
        "matched_on": shared[0],
        "method": "complaint_number+judge",
        "other_candidates": len(matches) - 1,
    }


def find_review(decision: dict, reviews: dict[str, dict]) -> dict | None:
    """The ВРП review of this decision, or None.

    Joined on the decision number the review quotes in its own title — the most
    reliable edge in the corpus, since it is structured, exact, and chosen by the
    model from numbers a rule found rather than transcribed.
    """
    number = _normalized_num(decision.get("decision_num"))
    if not number:
        return None
    for filename, review in reviews.items():
        if _normalized_num(review.get("reviewed_decision_num")) == number:
            return {
                "filename": filename,
                "record": review,
                "matched_on": decision.get("decision_num"),
                "method": "decision_number",
            }
    return None


def judge_view(act_record: dict, judge_name: str) -> dict | None:
    """The entry for one judge inside a related act.

    A single ухвала opens against several judges and refuses different grounds for
    each, so the decision's judge must be matched to *their own* entry. Falling
    back to the first entry would attribute another judge's grounds to them, so
    there is no fallback: no match means no data.
    """
    key = judge_key(judge_name)
    if not key:
        return None
    for j in act_record.get("judges") or []:
        if judge_key(j.get("name")) == key:
            return j
    return None
