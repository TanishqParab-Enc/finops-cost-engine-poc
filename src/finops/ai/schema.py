"""Structured contract for AI output.

The AI is asked for a JSON object matching this schema. Anything else is
rejected, so a malformed or hallucinated response can never leak into the
report as if it were valid analysis.
"""

from __future__ import annotations

from typing import Any

import jsonschema

from ..errors import AIError

ANALYSIS_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "FinOpsAIAnalysis",
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "reason", "cost_drivers", "recommendation"],
    "properties": {
        "summary": {"type": "string", "minLength": 1, "maxLength": 1200},
        "reason": {"type": "string", "minLength": 1, "maxLength": 1200},
        "cost_drivers": {
            "type": "array",
            "maxItems": 10,
            "items": {"type": "string", "minLength": 1, "maxLength": 400},
        },
        "recommendation": {"type": "string", "maxLength": 1200},
    },
}


def validate_analysis(payload: Any) -> dict[str, Any]:
    """Validate the model's JSON. Numbers are deliberately not accepted here.

    The monetary figures in the final report always come from the deterministic
    estimate, so the schema does not even allow the model to supply them.
    """
    if not isinstance(payload, dict):
        raise AIError("AI response was not a JSON object")
    try:
        jsonschema.validate(payload, ANALYSIS_SCHEMA)
    except jsonschema.ValidationError as exc:
        raise AIError("AI response failed schema validation", detail=exc.message) from exc
    return payload
