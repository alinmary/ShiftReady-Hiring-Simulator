"""Reading text and JSON out of Claude responses, in one place."""
from __future__ import annotations

import json
import re
from typing import Any

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", flags=re.I)


class AIResponseError(ValueError):
    """The model's reply could not be used; the message is safe to show users."""


def response_text(response: Any) -> str:
    """Join the text blocks of a Messages API response."""
    return "".join(block.text for block in response.content if getattr(block, "type", "") == "text")


def parse_json(text: str) -> Any:
    """Parse JSON that may be wrapped in a Markdown code fence."""
    return json.loads(_FENCE.sub("", text.strip()))


def parse_json_object(text: str) -> dict[str, Any]:
    try:
        result = parse_json(text)
    except json.JSONDecodeError as error:
        raise AIResponseError("The AI response could not be read. Please retry.") from error
    if not isinstance(result, dict):
        raise AIResponseError("The AI returned an invalid response. Please retry.")
    return result
