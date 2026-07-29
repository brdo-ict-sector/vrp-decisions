"""
Single source of truth for the structured-extraction schema.

The schema is enforced two ways that must agree:
  - As a strict tool `input_schema` for the Claude API (phase 2 — extraction), so the model
    can only emit values the schema allows — in particular, кваліфікація діяння
    grounds are constrained to a fixed enum (ART106_GROUNDS).
  - As documentation: dumped to `extraction_schema.json` for reference and reuse.

Кваліфікація діяння is captured per stage (скарга → ДП → ВРП) as a short list of
enum grounds plus an optional free-text note for nuance. The enum is corpus-only:
it covers the підстави за ст.106 that actually appear in the acts. Add new
values here (and re-run extraction) when the corpus grows.

Two schemas live here:
  - DECISION_SCHEMA — рішення дисциплінарної палати (the outcome)
  - RULING_SCHEMA   — ухвала про відкриття дисциплінарної справи (the opening)

Both carry the complaint number, which is what joins them into one case. That
field is never transcribed by the model: `with_complaint_candidates()` narrows it
to the numbers stage 14 extracted verbatim from the same act.
"""

import json
from copy import deepcopy

# ── Кваліфікація діяння — strict enum (short labels), corpus-only ─────────────
# Format: "106-<пункт><підпункт> <короткий опис>". Keep labels short; the full
# legal wording lives in the decision text, not in the facet value.
#
# The first seven labels are FROZEN — round-2 extractions and docs/decisions.json
# already carry them verbatim. Never reword an existing label; only append.
#
# The rest were added when ухвали про відкриття entered the corpus: rulings cite a
# much wider slice of ст. 106 than the decisions did (106-1г alone appears 72
# times, 106-8 sixteen). Without them the model is forced to dump real grounds
# into the free-text `note`, which makes «по чому відкрилися vs по чому
# притягнуто» impossible to compute.
ART106_GROUNDS = [
    # ── frozen: present since round 2 ──
    "106-1а незаконна відмова в доступі до правосуддя / порушення процесуального права",
    "106-1б незазначення мотивів щодо аргументів сторін",
    "106-1в порушення гласності і відкритості процесу",
    "106-1д порушення правил відведення (самовідведення)",
    "106-2 безпідставне затягування розгляду справи",
    "106-3 поведінка, що порочить звання судді",
    "106-4 грубе порушення закону / прав людини",
    # ── added for ухвали ──
    "106-1г порушення рівності учасників процесу та змагальності сторін",
    "106-1ґ незабезпечення права на захист / перешкоджання реалізації прав учасників",
    "106-5 розголошення таємниці, що охороняється законом",
    "106-6 неповідомлення про втручання в діяльність судді",
    "106-8 втручання у процес здійснення правосуддя іншими суддями",
    "106-9 неподання або несвоєчасне подання декларації",
    "106-10 зазначення в декларації завідомо неправдивих відомостей",
    "106-11 використання статусу судді для незаконної вигоди",
    "106-13 ненадання інформації на законну вимогу члена ВРП",
    "106-15 визнання винним у корупційному правопорушенні",
    "106-17 недостовірні відомості в декларації родинних зв’язків",
    "106-19 порушення правил самовідводу / недостовірне декларування",
]

CHAMBERS = ["Перша", "Друга", "Третя"]

# Who filed the complaint. This mirrors the HCJ register index carried by the
# complaint number itself (7 = individual, 13 = state body, 8 = official), so the
# model's answer can be cross-checked against the number stage 14 extracted.
COMPLAINANT_TYPES = [
    "фізична особа",
    "суд / голова суду",
    "орган прокуратури",
    "НАЗК / НАБУ / інший державний орган",
    "Уповноважений Верховної Ради з прав людини",
    "юридична особа",
    "інше",
]

# What the disciplinary inspector proposed before the palace ruled. The palace
# overriding the inspector is a meaningful accountability signal, so it is
# captured as a facet rather than buried in prose.
INSPECTOR_PROPOSALS = [
    "відкрити дисциплінарну справу",
    "відмовити у відкритті дисциплінарної справи",
    "не зазначено",
]

RULING_OUTCOMES = [
    "відкрито дисциплінарну справу",
    "відмовлено у відкритті дисциплінарної справи",
    "інше",
]

# Види дисциплінарного стягнення, частина перша статті 109 Закону «Про судоустрій
# і статус суддів», in ascending severity. The free-text `sanction` field already
# carries the full wording, but it varies («Сувора догана –» / «Сувора догана з» /
# «попередження» lowercased), and severity is the whole point of the field: догана
# and сувора догана differ by the deprivation attached (one month vs three).
# Normalizing at extraction time makes the distinction filterable and countable
# instead of leaving it to a regex over prose.
SANCTION_TYPES = [
    "попередження",
    "догана",
    "сувора догана",
    "подання про тимчасове відсторонення від здійснення правосуддя",
    "подання про переведення судді до суду нижчого рівня",
    "подання про звільнення судді з посади",
    # Case closed, judge released from liability, or the limitation period expired
    # — an explicit value, so "no sanction imposed" is distinguishable from "this
    # stage did not happen" (null).
    "стягнення не накладено",
]

# What the ВРП did with the palate's decision on review. Per judge, because a
# review can uphold the decision for one judge and quash it for another.
REVIEW_OUTCOMES = [
    "залишено без змін",
    "скасовано повністю",
    "скасовано частково",
    "змінено стягнення",
    "інше",
]

# Who took the palate's decision to the ВРП. The judge appealing a sanction and the
# complainant appealing a refusal are opposite situations with opposite stakes.
APPELLANT_TYPES = [
    "суддя",
    "скаржник",
    "дисциплінарний інспектор",
    "інше",
]

# What the palate decided about this judge. Per judge: one decision routinely
# punishes one judge and refuses to punish another named in the same act.
DECISION_OUTCOMES = [
    "притягнуто до дисциплінарної відповідальності",
    "відмовлено у притягненні",
    "дисциплінарне провадження припинено",
    "інше",
]

# Nullable string (anyOf is the structured-outputs-supported way to express null).
_TEXT = {"anyOf": [{"type": "string"}, {"type": "null"}]}

# Structured outputs cap a schema at 16 union-typed (nullable / anyOf) parameters —
# past that the API rejects the request outright. Nesting per-judge blocks multiplies
# them quickly, so `note` is a plain string ("" when there is nothing to add) rather
# than string|null. The stage objects around it stay nullable, where the difference
# between "absent from the act" and "empty" carries meaning. `assert_union_budget()`
# guards the limit whenever this module is run.
_NOTE = {"type": "string"}

# Per-stage кваліфікація: a list of enum grounds + an optional nuance note.
_STAGE_QUAL = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "grounds": {
            "type": "array",
            "items": {"type": "string", "enum": ART106_GROUNDS},
        },
        "note": _NOTE,
    },
    "required": ["grounds", "note"],
}

_NULLABLE_STAGE_QUAL = {"anyOf": [_STAGE_QUAL, {"type": "null"}]}

# Normalized стягнення; null where none was imposed at this stage.
_SANCTION_TYPE = {"anyOf": [{"type": "string", "enum": SANCTION_TYPES}, {"type": "null"}]}

# ── The judge is the unit of observation ─────────────────────────────────────
# An act is not about one judge. 67 acts in the corpus name several, and the
# outcome then differs *within* one act — one decision punishes судді Підпалого
# and in the same breath refuses to punish two judges of the appellate court.
# Qualification, conduct and sanction therefore hang off the judge, never off the
# act; anything act-level would have to pick a winner and lose the rest.
#
# `name` is recorded as the act writes it. Ukrainian acts decline surnames
# («стосовно судді Козленко Г.О.», «суддів Шкорупеєва Д.А.»), so this string is a
# label, not an identity — matching judges across acts is the merge phase's job
# and needs a normalized key, not this field.
_JUDGE_IDENTITY = {
    "name": {"type": "string"},          # ПІБ, як зазначено в акті
    "court": {"type": "string"},         # суд, де працює суддя
    "position": _TEXT,                   # суддя / слідчий суддя / голова суду
}


def _judge_block(extra: dict, required_extra: list[str]) -> dict:
    """One entry of the per-judge array: identity + whatever this act type records."""
    return {
        "type": "array",
        "items": {
            "type": "object",
            "additionalProperties": False,
            "properties": {**_JUDGE_IDENTITY, **extra},
            "required": [*_JUDGE_IDENTITY, *required_extra],
        },
    }

# ── Рішення дисциплінарної палати (first instance) ───────────────────────────
# What the palate decided, per judge. There is deliberately no ВРП stage here: a
# review is a separate act, numbered `…/0/15-…`, published later, and extracted
# against REVIEW_SCHEMA. Modelling it as a field inside the palate's decision —
# which is what this schema used to do — describes a document that does not exist,
# which is why every «Перегляд від ВРП» column came back empty.
#
# `chamber` is likewise absent: it is stated by the act number (`…/2дп/…` = Друга),
# so act_numbers.chamber_of() derives it and the model is not asked to re-read it.
DECISION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "decision_num": {"type": "string"},
        "date": {"type": "string"},           # дд.мм.рррр
        "short_name": {"type": "string"},     # офіційна назва рішення
        # Joins this decision to the ухвала that opened the case. Narrowed to the
        # numbers stage 14 found in this act — see with_complaint_candidates().
        "complaint_number": _TEXT,
        "related_complaint_numbers": {"type": "array", "items": {"type": "string"}},
        "judges": _judge_block(
            {
                "qualification": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "complaint": _NULLABLE_STAGE_QUAL,   # як кваліфіковано у скарзі
                        "dp": _NULLABLE_STAGE_QUAL,          # як кваліфікувала палата
                    },
                    "required": ["complaint", "dp"],
                },
                "conduct": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"complaint": _TEXT, "dp": _TEXT},
                    "required": ["complaint", "dp"],
                },
                # Full wording of the стягнення as the act phrases it, and the same
                # стягнення normalized to the ст. 109 vocabulary. Both, because the
                # wording carries the deprivation and its term while the enum is
                # what filters and counts.
                "sanction": _TEXT,
                "sanction_type": _SANCTION_TYPE,
                "outcome": {"type": "string", "enum": DECISION_OUTCOMES},
            },
            ["qualification", "conduct", "sanction", "sanction_type", "outcome"],
        ),
        "summary": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "essence": {"type": "string"},   # суть рішення
                "facts": {"type": "string"},     # фабула
                "conclusions": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["essence", "facts", "conclusions"],
        },
    },
    "required": [
        "decision_num", "date", "short_name",
        "complaint_number", "related_complaint_numbers",
        "judges", "summary",
    ],
}

# ── Ухвала про відкриття дисциплінарної справи ───────────────────────────────
# A ruling is not a small decision — it is the other half of the story. It records
# what the complainant asked for, what the inspector proposed, what the palace
# actually opened the case on, and — uniquely — which grounds the palace expressly
# refused to open on. Together with the decision's `qualification.dp`, that is the
# «по чому відкрилися vs по чому реально було притягнуто» comparison.
_GROUNDS_LIST_FIELD = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "grounds": {"type": "array", "items": {"type": "string", "enum": ART106_GROUNDS}},
        "note": _NOTE,
    },
    "required": ["grounds", "note"],
}

_NULLABLE_GROUNDS = {"anyOf": [_GROUNDS_LIST_FIELD, {"type": "null"}]}

RULING_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        # ── the act itself ──
        "ruling_num": {"type": "string"},
        "date": {"type": "string"},           # дд.мм.рррр
        "short_name": {"type": "string"},     # офіційна назва ухвали
        "panel": {                            # головуючий першим у списку
            "type": "array",
            "items": {"type": "string"},
        },
        "inspector": _TEXT,                   # дисциплінарний інспектор — доповідач
        # ── who complained ──
        "complaint_number": _TEXT,            # narrowed per document, see with_complaint_candidates()
        "related_complaint_numbers": {        # other complaints folded into a merged case
            "type": "array",
            "items": {"type": "string"},
        },
        "complaint_date": _TEXT,              # дд.мм.рррр, дата надходження скарги до ВРП
        "complainant_name": _TEXT,            # повне ім'я скаржника (ПІБ), якщо є
        "complainant_organization": _TEXT,    # організація скаржника, якщо скаржиться орган
        "complainant_type": {"anyOf": [{"type": "string", "enum": COMPLAINANT_TYPES}, {"type": "null"}]},
        "court_case_number": _TEXT,           # судова справа, дії в якій оскаржено
        # ── про кого, і що палата вирішила щодо кожного ──
        # Grounds sit inside the judge, not beside them: an ухвала about three
        # judges routinely opens on different grounds for each, and may open
        # against one while refusing against another.
        "judges": _judge_block(
            {
                "grounds": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "requested": _NULLABLE_GROUNDS,  # про що просив скаржник
                        "opened": _NULLABLE_GROUNDS,     # по чому палата відкрила справу
                        "rejected": _NULLABLE_GROUNDS,   # по чому палата ознак НЕ встановила
                    },
                    "required": ["requested", "opened", "rejected"],
                },
                "outcome": {"type": "string", "enum": RULING_OUTCOMES},
                "conduct": _TEXT,             # діяння, як його описано у скарзі
                "judge_position": _TEXT,      # стислий зміст пояснень судді
            },
            ["grounds", "outcome", "conduct", "judge_position"],
        ),
        "inspector_proposal": {"anyOf": [{"type": "string", "enum": INSPECTOR_PROPOSALS}, {"type": "null"}]},
        # ── narrative ──
        "summary": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "essence": {"type": "string"},
                "facts": {"type": "string"},
            },
            "required": ["essence", "facts"],
        },
    },
    "required": [
        "ruling_num", "date", "short_name", "panel", "inspector",
        "complaint_number", "related_complaint_numbers",
        "complaint_date", "complainant_name", "complainant_organization",
        "complainant_type", "court_case_number",
        "judges", "inspector_proposal", "summary",
    ],
}

# ── Рішення ВРП про перегляд рішення дисциплінарної палати ───────────────────
# The third act type, and the one the pipeline had no schema for at all: 125 of
# the 450 «рішення» are these. They are joined to the palate's decision not by the
# complaint number but by the decision number they quote in their own title —
# present in all 112 review acts, which makes it the most reliable edge we have.
REVIEW_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "review_num": {"type": "string"},
        "date": {"type": "string"},           # дд.мм.рррр
        "short_name": {"type": "string"},
        "panel": {"type": "array", "items": {"type": "string"}},
        # The decision under review. Narrowed per document to the numbers found by
        # rule in this act — see with_review_candidates(); never transcribed.
        "reviewed_decision_num": _TEXT,
        "reviewed_decision_date": _TEXT,      # дд.мм.рррр
        # Kept as a cross-check on the join: the same case reached here through a
        # complaint, and the two keys must agree.
        "complaint_number": _TEXT,
        "related_complaint_numbers": {"type": "array", "items": {"type": "string"}},
        # Who appealed, and how the ВРП answered — per judge, because a review can
        # uphold for one judge and quash for another.
        "appellant_type": {"anyOf": [{"type": "string", "enum": APPELLANT_TYPES}, {"type": "null"}]},
        "appellant_name": _TEXT,
        "judges": _judge_block(
            {
                "review_outcome": {"type": "string", "enum": REVIEW_OUTCOMES},
                "qualification": _NULLABLE_STAGE_QUAL,  # як кваліфікувала ВРП
                "conduct": _TEXT,                       # оцінка поведінки судді у ВРП
                # The sanction in force *after* the review: unchanged, changed, or
                # gone. Null when the review left no sanction standing.
                "sanction": _TEXT,
                "sanction_type": _SANCTION_TYPE,
            },
            ["review_outcome", "qualification", "conduct", "sanction", "sanction_type"],
        ),
        "summary": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "essence": {"type": "string"},
                "facts": {"type": "string"},
                "conclusions": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["essence", "facts", "conclusions"],
        },
    },
    "required": [
        "review_num", "date", "short_name", "panel",
        "reviewed_decision_num", "reviewed_decision_date",
        "complaint_number", "related_complaint_numbers",
        "appellant_type", "appellant_name", "judges", "summary",
    ],
}

# Top-level keys, for stable storage/reads across the pipeline.
STRUCTURE_KEYS = tuple(DECISION_SCHEMA["properties"].keys())
RULING_KEYS = tuple(RULING_SCHEMA["properties"].keys())
REVIEW_KEYS = tuple(REVIEW_SCHEMA["properties"].keys())


# ── Complaint numbers: chosen, never typed ───────────────────────────────────
def with_complaint_candidates(schema: dict, candidates: list[str]) -> dict:
    """Constrain the complaint-number fields to numbers stage 14 actually found in the act.

    The complaint number is the key that joins a ухвала to its рішення, so a single
    transposed digit does not look wrong — it silently fails to join, or joins to
    the wrong case. Rather than let the model transcribe it, stage 14 extracts every
    candidate verbatim and this turns them into an enum: because the API enforces
    the schema, the model can only *choose* among real numbers, never invent one.

    Acts where stage 14 found nothing (43 of 935) get a null-only field, so they surface
    as gaps for manual review instead of being filled in by guesswork.
    """
    schema = deepcopy(schema)  # never mutate the module-level schema
    props = schema["properties"]

    if candidates:
        props["complaint_number"] = {
            "anyOf": [{"type": "string", "enum": list(candidates)}, {"type": "null"}]
        }
        props["related_complaint_numbers"] = {
            "type": "array",
            "items": {"type": "string", "enum": list(candidates)},
        }
    else:
        props["complaint_number"] = {"type": "null"}
        # Structured outputs reject `maxItems`, so the array cannot be pinned to
        # empty in the schema — enforce_no_candidates() clears it after the call.
        props["related_complaint_numbers"] = {"type": "array", "items": {"type": "string"}}

    return schema


def with_review_candidates(schema: dict, candidates: list[str]) -> dict:
    """Constrain `reviewed_decision_num` to palate-decision numbers found in the act.

    Same reasoning as the complaint number, and the same failure mode: the reviewed
    decision number is the ДП→ВРП join key, so a transposed digit attaches a review
    to the wrong decision — or to none — with nothing a reader could notice. The
    numbers are found by rule (`act_numbers.find_reviewed_decision_numbers`) and
    offered as an enum, so the model picks which one this act actually reviews.

    A review act quoting no decision number at all does not occur in the corpus, but
    the null-only branch is kept so such an act surfaces as a gap rather than an
    invention.
    """
    schema = deepcopy(schema)
    props = schema["properties"]
    if candidates:
        props["reviewed_decision_num"] = {
            "anyOf": [{"type": "string", "enum": list(candidates)}, {"type": "null"}]
        }
    else:
        props["reviewed_decision_num"] = {"type": "null"}
    return schema


def enforce_no_candidates(result: dict, candidates: list[str]) -> dict:
    """Blank the complaint-number fields when stage 14 found nothing in the act.

    Counterpart to the else-branch above: with no enum to choose from, any number
    in `related_complaint_numbers` can only have been invented, so it is dropped
    and the act surfaces as a gap for manual review.
    """
    if not candidates:
        result["complaint_number"] = None
        result["related_complaint_numbers"] = []
    return result


# ── Guard: the structured-outputs union budget ───────────────────────────────
UNION_LIMIT = 16



def clip_for_model(text: str, max_chars: int, head_share: float = 0.65) -> str:
    """Fit an act into the context window without losing its operative part.

    Cutting the tail is the obvious way to shorten a document and the wrong one
    here. A ВРП act states its outcome last: «вирішила: … застосувати … стягнення
    у виді подання про звільнення судді з посади» is the final paragraph. In act
    617/2дп/15-26 that paragraph begins at character 184 572 of 185 491 — inside
    the last half-percent — so a head-only clip at 160 000 removed the sanction
    and nothing else of consequence. The model reported the operative part as
    missing, which was true of what it was shown, and the record came back with a
    null sanction for a judge the palate had moved to dismiss.

    So keep both ends: the head carries the parties, complaint numbers and the
    grounds argued, the tail carries what was decided.

    At the current limit (500 000 chars against a largest act of ~430 000) nothing
    in the corpus is clipped at all, and that is the intent — the whole act goes to
    the model. This stays as a guard for an act longer than any we have yet seen,
    so that if the limit ever binds again it takes the middle rather than the
    outcome.
    """
    if len(text) <= max_chars:
        return text
    head = int(max_chars * head_share)
    tail = max_chars - head
    return (text[:head]
            + "\n\n[…пропущено середину тексту…]\n\n"
            + text[-tail:])


def count_union_params(schema: dict) -> int:
    """Number of union-typed (anyOf) parameters anywhere in a schema.

    Structured outputs reject a schema with more than UNION_LIMIT of them — the
    compilation cost is exponential — and the failure arrives as a 400 in the
    middle of a paid run, one act at a time. Counting here turns that into an
    error at edit time.
    """
    if not isinstance(schema, dict):
        return 0
    n = 1 if "anyOf" in schema else 0
    for key in ("properties", "items", "additionalProperties"):
        value = schema.get(key)
        if isinstance(value, dict):
            children = value.values() if key == "properties" else [value]
            n += sum(count_union_params(c) for c in children)
    return n


def assert_union_budget() -> None:
    for name, schema in (("DECISION_SCHEMA", DECISION_SCHEMA),
                         ("RULING_SCHEMA", RULING_SCHEMA),
                         ("REVIEW_SCHEMA", REVIEW_SCHEMA)):
        n = count_union_params(schema)
        status = "ok" if n <= UNION_LIMIT else "OVER LIMIT"
        print(f"  {name:16s} {n:2d}/{UNION_LIMIT} union params — {status}")
        if n > UNION_LIMIT:
            raise SystemExit(
                f"{name} has {n} union-typed parameters; the API allows {UNION_LIMIT}. "
                "Make a nullable field required-and-empty instead of string|null."
            )


if __name__ == "__main__":
    # Dump the JSON Schemas alongside this module for reference.
    from pathlib import Path

    assert_union_budget()
    here = Path(__file__).resolve().parent
    for name, schema in (("extraction_schema.json", DECISION_SCHEMA),
                         ("ruling_schema.json", RULING_SCHEMA),
                         ("review_schema.json", REVIEW_SCHEMA)):
        (here / name).write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Wrote {here / name}")
