"""Tool call reason tracker.

Records why each tool was called by capturing the `reason` field from tool
parameters together with the tool name.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from kosong.tooling import CallableTool2
from pydantic import BaseModel


class ToolCallReason:
    """Tracks reasons for tool invocations.

    Each entry stores the tool name and the human-readable reason provided
    in the tool parameters, keyed by file path.
    """

    def __init__(self) -> None:
        self._records: dict[str, list[dict[str, str]]] = {}

    def add_tool_call_reason(self, params: BaseModel, tool: CallableTool2[Any]) -> None:
        """Record a tool call reason for WriteFile or EditFile.

        Args:
            params: Validated parameters for the tool call. Expected to contain
                a ``reason`` attribute of type ``str``.
            tool: The tool instance that was invoked. Must be WriteFile or EditFile.

        Raises:
            ValueError: If ``tool`` is not WriteFile or EditFile.
        """
        if tool.name not in ("WriteFile", "EditFile"):
            raise ValueError(f"Expected WriteFile or EditFile, got {tool.name}")

        reason: str = getattr(params, "reason", "")
        raw_path: str = getattr(params, "path", "")
        if not raw_path:
            raise ValueError("params must contain a non-empty 'path' attribute.")
        path: str = str(Path(raw_path).resolve())
        record: dict[str, str] = {"tool_name": tool.name, "reason": reason}

        if tool.name == "WriteFile":
            record["content"] = getattr(params, "content", "")
        elif tool.name == "EditFile":
            edit: Any | None = getattr(params, "edit", None)
            if isinstance(edit, list):
                record["old"] = "\n".join(
                    getattr(item, "old", "") for item in edit
                )
                record["content"] = "\n".join(
                    getattr(item, "new", "") for item in edit
                )
            elif edit is not None:
                record["old"] = getattr(edit, "old", "")
                record["content"] = getattr(edit, "new", "")
            else:
                record["old"] = ""
                record["content"] = ""
        self._records.setdefault(path, []).append(record)

    @staticmethod
    def _truncate_text(text: str, max_lines: int = 24, edge_lines: int = 12, max_chars: int = 1500) -> str:
        if not text:
            return text

        lines = text.splitlines()

        # Line-based truncation for long multi-line text
        if len(lines) > max_lines:
            omitted = len(lines) - 2 * edge_lines
            head = "\n".join(lines[:edge_lines])
            tail = "\n".join(lines[-edge_lines:])
            return f"{head}\n... ({omitted} lines omitted) ...\n{tail}"

        # Character-based truncation for long compact text
        if len(text) > max_chars:
            edge = max_chars // 2
            omitted = len(text) - 2 * edge
            return f"{text[:edge]}\n... ({omitted} characters omitted) ...\n{text[-edge:]}"

        return text

    def formatted_print(self, paths: list[str]) -> str:
        """Find the paths' changes and return them as a formatted string.

        Args:
            paths: The file paths to look up. Each will be resolved to an absolute path.

        Returns:
            A formatted string containing all changes for the given paths.
        """
        lines: list[str] = []
        for path in paths:
            abs_path = str(Path(path).resolve())
            records = self._records.get(abs_path)
            if not records:
                lines.append(f"No record found for: {abs_path}")
                continue

            lines.append(f"File: {abs_path}")
            for idx, record in enumerate(records, start=1):
                tool_name = record.get("tool_name", "Unknown")
                reason = record.get("reason", "")
                content = record.get("content", "")

                lines.append(f"\n[Change #{idx}] Tool: {tool_name}")
                if reason:
                    lines.append(f"Reason: {reason}")
                if "old" in record:
                    old = record["old"]
                    lines.append("--- old ---")
                    lines.append(self._truncate_text(old))
                    lines.append("--- new ---")
                lines.append(self._truncate_text(content))

        return "\n".join(lines)

    def clear(self) -> None:
        """Remove all recorded reasons."""
        self._records.clear()

    def __len__(self) -> int:
        return sum(len(records) for records in self._records.values())

    def __bool__(self) -> bool:
        return bool(self._records)
