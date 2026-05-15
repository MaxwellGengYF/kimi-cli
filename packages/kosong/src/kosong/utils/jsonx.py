from __future__ import annotations

import json
from typing import Any

import dirtyjson
import orjson


def loads_relaxed(data: str | bytes | bytearray) -> Any:
    """Parse JSON with orjson for speed, fallback to dirtyjson for leniency.

    LLM-generated JSON may contain unescaped control characters, trailing
    commas, single-quoted strings, comments, and other relaxations that
    orjson (and stdlib json with strict=False) rejects.  This helper tries
    the fast path first and falls back to dirtyjson when necessary.
    """
    try:
        return orjson.loads(data)
    except orjson.JSONDecodeError:
        pass
    if isinstance(data, (bytes, bytearray)):
        data = data.decode("utf-8", errors="ignore")
    return dirtyjson.loads(data)
