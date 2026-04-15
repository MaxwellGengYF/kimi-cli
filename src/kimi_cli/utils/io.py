from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

_global_io_lock = threading.Lock()


def atomic_json_write(data: Any, path: Path) -> None:
    """Write JSON data to a file directly (non-atomic).

    Note: This overwrites the file in-place. A crash during write may leave
    the file in a partially written/corrupted state.
    """
    with _global_io_lock:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
