from __future__ import annotations

import json
from typing import Any

import orjson


def loads_relaxed(data: str | bytes | bytearray) -> Any:
    """Parse JSON with orjson for speed, fallback to stdlib json with strict=False for leniency.

    LLM-generated JSON may contain unescaped control characters that orjson
    (and json.loads with default strict=True) rejects.  This helper tries the
    fast path first and only falls back to the lenient parser when necessary.
    """
    try:
        return orjson.loads(data)
    except orjson.JSONDecodeError:
        return json.loads(data, strict=False)
