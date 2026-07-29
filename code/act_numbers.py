"""
Rules for reading the ВРП act number — who issued an act, and which act it reviews.

Every act carries a number of the form

    1503 / 3дп / 15 - 26
    │      │     │    └─ year
    │      │     └────── the ВРП's own register index (always 15 in this corpus)
    │      └──────────── the issuing body: 1дп/2дп/3дп = a disciplinary palate,
    │                    0 = the ВРП itself sitting in review
    └─────────────────── serial number within the year

Two facts fall out of that, and both are facts we were previously asking the model
for or guessing at:

  - **Who decided.** A «Рішення» numbered `…/0/15-…` is not a chamber decision at
    all — it is the ВРП reviewing one. 125 of the 450 рішення in the corpus are
    these, and a рішення-shaped schema cannot describe them.
  - **Which chamber.** `2дп` is the Друга дисциплінарна палата. Deriving it beats
    asking the model, which can only re-read what the number already states.

A review decision then names the decision it reviews, in its own title:

    Про залишення без змін рішення Другої Дисциплінарної палати Вищої ради
    правосуддя від 4 лютого 2026 року № 151/2дп/15-26 про притягнення судді…

All 112 review acts in the corpus do this, which makes it the most reliable join
in the dataset — exact, structured, and free of any model involvement.
"""

import re

# 1503/3дп/15-26  ·  1449/0/15-26
_ACT_NUM = re.compile(r"^\s*(\d+)\s*/\s*([^/]*?)\s*/\s*(\d+)\s*-\s*(\d+)\s*$", re.I)

# A palate decision number as quoted inside another act's text or title.
_QUOTED_DP_NUM = re.compile(r"(\d+/\d+дп/\d+-\d+)", re.I)

CHAMBER_BY_INDEX = {"1": "Перша", "2": "Друга", "3": "Третя"}

ISSUER_DP = "ДП"     # a disciplinary palate, first instance
ISSUER_VRP = "ВРП"   # the High Council itself, on review


def parse_act_number(number: str) -> dict | None:
    """Split an act number into serial / issuer / chamber / year.

    Returns None when the number does not parse — 2 acts in the corpus — so the
    caller can treat it as a gap rather than silently assume a chamber.
    """
    m = _ACT_NUM.match(str(number or ""))
    if not m:
        return None
    serial, body, register, year = m.groups()
    body = body.lower()

    if body in ("0", ""):
        issuer, chamber = ISSUER_VRP, None
    elif body.endswith("дп") and body[:-2] in CHAMBER_BY_INDEX:
        issuer, chamber = ISSUER_DP, CHAMBER_BY_INDEX[body[:-2]]
    else:
        return None

    return {
        "serial": int(serial),
        "issuer": issuer,
        "chamber": chamber,
        "register": register,
        "year": int(year),
        "normalized": f"{serial}/{body}/{register}-{year}",
    }


def issuer_of(number: str) -> str | None:
    """`ДП` / `ВРП` / None — which body issued this act."""
    parsed = parse_act_number(number)
    return parsed["issuer"] if parsed else None


def chamber_of(number: str) -> str | None:
    """Перша / Друга / Третя, or None for a ВРП act (or an unparseable number)."""
    parsed = parse_act_number(number)
    return parsed["chamber"] if parsed else None


def find_reviewed_decision_numbers(text: str) -> list[str]:
    """Palate-decision numbers quoted in this act, in order, deduplicated.

    Used exactly like the complaint-number candidates: the numbers found here are
    handed to the model as an enum so it chooses the reviewed decision rather than
    transcribing it. The act's own number is not excluded here — a review act is
    numbered `…/0/…` and so can never collide with a `…/Nдп/…` match.
    """
    seen: dict[str, None] = {}
    for m in _QUOTED_DP_NUM.finditer(text or ""):
        seen.setdefault(m.group(1).lower(), None)
    return list(seen)
