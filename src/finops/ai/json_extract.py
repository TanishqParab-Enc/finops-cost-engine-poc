"""Robust JSON extraction from LLM text output.

Even when explicitly instructed to return JSON only, models frequently wrap it
in a markdown code fence (```json ... ```) or add a leading/trailing sentence.
Every AI provider funnels its raw text response through this helper.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..errors import AIError

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


def extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()

    fence_match = _FENCE_RE.search(stripped)
    candidate = fence_match.group(1) if fence_match else stripped

    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    # Fall back to the first balanced {...} span, in case of surrounding prose.
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start != -1 and end > start:
        try:
            parsed = json.loads(candidate[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    raise AIError("AI did not return valid JSON", detail=text[:300])
