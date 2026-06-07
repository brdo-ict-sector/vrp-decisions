"""
Single source of truth for the structured-extraction schema.

The schema is enforced two ways that must agree:
  - As a strict tool `input_schema` for the Claude API (stage 2), so the model
    can only emit values the schema allows — in particular, кваліфікація діяння
    grounds are constrained to a fixed enum (ART106_GROUNDS).
  - As documentation: dumped to `extraction_schema.json` for reference and reuse.

Кваліфікація діяння is captured per stage (скарга → ДП → ВРП) as a short list of
enum grounds plus an optional free-text note for nuance. The enum is corpus-only:
it covers the підстави за ст.106 that actually appear in the round-2 batch. Add new
values here (and re-run extraction) when the corpus grows.
"""

# ── Кваліфікація діяння — strict enum (short labels), corpus-only ─────────────
# Format: "106-<пункт><підпункт> <короткий опис>". Keep labels short; the full
# legal wording lives in the decision text, not in the facet value.
ART106_GROUNDS = [
    "106-1а незаконна відмова в доступі до правосуддя / порушення процесуального права",
    "106-1б незазначення мотивів щодо аргументів сторін",
    "106-1в порушення гласності і відкритості процесу",
    "106-1д порушення правил відведення (самовідведення)",
    "106-2 безпідставне затягування розгляду справи",
    "106-3 поведінка, що порочить звання судді",
    "106-4 грубе порушення закону / прав людини",
]

CHAMBERS = ["Перша", "Друга", "Третя"]

# Nullable string (anyOf is the structured-outputs-supported way to express null).
_TEXT = {"anyOf": [{"type": "string"}, {"type": "null"}]}

# Per-stage кваліфікація: a list of enum grounds + an optional nuance note.
_STAGE_QUAL = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "grounds": {
            "type": "array",
            "items": {"type": "string", "enum": ART106_GROUNDS},
        },
        "note": _TEXT,
    },
    "required": ["grounds", "note"],
}

_NULLABLE_STAGE_QUAL = {"anyOf": [_STAGE_QUAL, {"type": "null"}]}

# Top-level extraction schema (the tool's input_schema).
DECISION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "judge_name": {"type": "string"},
        "court": {"type": "string"},
        "decision_num": {"type": "string"},
        "chamber": {"type": "string", "enum": CHAMBERS},
        "date": {"type": "string"},          # дд.мм.рррр
        "short_name": {"type": "string"},     # офіційна назва рішення
        "qualification": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "complaint": _NULLABLE_STAGE_QUAL,
                "dp": _NULLABLE_STAGE_QUAL,
                "vrp": _NULLABLE_STAGE_QUAL,
            },
            "required": ["complaint", "dp", "vrp"],
        },
        "conduct": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"complaint": _TEXT, "dp": _TEXT, "vrp": _TEXT},
            "required": ["complaint", "dp", "vrp"],
        },
        "sanction": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"dp": _TEXT, "vrp": _TEXT},
            "required": ["dp", "vrp"],
        },
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
        "judge_name", "court", "decision_num", "chamber", "date", "short_name",
        "qualification", "conduct", "sanction", "summary",
    ],
}

# Top-level keys, for stable storage/reads across the pipeline.
STRUCTURE_KEYS = tuple(DECISION_SCHEMA["properties"].keys())


if __name__ == "__main__":
    # Dump the JSON Schema alongside this module for reference.
    import json
    from pathlib import Path

    out = Path(__file__).resolve().parent / "extraction_schema.json"
    out.write_text(json.dumps(DECISION_SCHEMA, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {out}")
