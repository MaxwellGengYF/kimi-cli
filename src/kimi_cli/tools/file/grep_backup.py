"""Pure-Python backup implementation of the Grep tool."""

import asyncio
import concurrent.futures
import fnmatch
import heapq
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import override

from kosong.tooling import CallableTool2, ToolError, ToolReturnValue
from pydantic import BaseModel, ConfigDict, Field

from kimi_cli.tools.utils import ToolResultBuilder, load_desc
from kimi_cli import logger
from kimi_cli.utils.sensitive import is_sensitive_file, sensitive_file_warning


class Params(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    pattern: str = Field(description="Regex pattern.")
    path: str = Field(
        description="Search target directory or file.",
        default=".",
    )
    glob: str | None = Field(
        description="Glob filter.",
        default=None,
    )
    output_mode: str = Field(
        description="Output format.",
        default="files_with_matches",
    )
    before_context: int | None = Field(
        alias="-B",
        description="Lines before match (content mode only).",
        default=None,
    )
    after_context: int | None = Field(
        alias="-A",
        description="Lines after match (content mode only).",
        default=None,
    )
    context: int | None = Field(
        alias="-C",
        description="Lines around match (content mode only).",
        default=None,
    )
    line_number: bool = Field(
        alias="-n",
        description="Show line numbers (content mode only).",
        default=True,
    )
    ignore_case: bool = Field(
        alias="-i",
        description="Case-insensitive search.",
        default=False,
    )
    type: str | None = Field(
        description="File type filter.",
        default=None,
    )
    head_limit: int | None = Field(
        description="Max results (0 = unlimited).",
        default=250,
        ge=0,
    )
    offset: int = Field(
        description="Skip first N results.",
        default=0,
        ge=0,
    )
    multiline: bool = Field(
        description="Multiline regex mode.",
        default=False,
    )
    include_ignored: bool = Field(
        description="Include .gitignore files.",
        default=False,
    )


# Minimal type-to-extension mapping for common file types.
_TYPE_MAP: dict[str, list[str]] = {
    "py": [".py"],
    "js": [".js", ".jsx", ".mjs", ".cjs"],
    "ts": [".ts", ".tsx", ".mts", ".cts"],
    "rs": [".rs"],
    "go": [".go"],
    "java": [".java"],
    "cpp": [".cpp", ".cc", ".cxx", ".hpp", ".h", ".hh", ".hxx"],
    "c": [".c", ".h"],
    "md": [".md", ".markdown"],
    "json": [".json"],
    "yaml": [".yaml", ".yml"],
    "xml": [".xml"],
    "html": [".html", ".htm", ".xhtml"],
    "css": [".css", ".scss", ".sass", ".less"],
    "sh": [".sh", ".bash", ".zsh", ".fish"],
    "sql": [".sql"],
    "lua": [".lua"],
    "vim": [".vim"],
    "docker": ["Dockerfile"],
    "make": ["Makefile", ".mk"],
    "ruby": [".rb"],
    "php": [".php"],
    "cs": [".cs"],
}

# Directories skipped unconditionally (VCS) or when include_ignored=False.
_VCS_DIRS = {".git", ".svn", ".hg", ".bzr", ".jj", ".sl"}

_IGNORED_DIRS = {
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
    ".tox",
    ".pytest_cache",
    ".mypy_cache",
    ".egg-info",
    ".idea",
    ".vscode",
    "target",
    "out",
    ".next",
    ".nuxt",
}

_MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB
_BINARY_SNIFF_SIZE = 8192


def _is_binary(data: bytes) -> bool:
    return b"\x00" in data


def _should_skip_dir(dirname: str, include_ignored: bool) -> bool:
    if dirname in _VCS_DIRS:
        return True
    if not include_ignored and dirname in _IGNORED_DIRS:
        return True
    return False


def _matches_type(file_path: Path, type_name: str | None) -> bool:
    if type_name is None:
        return True
    extensions = _TYPE_MAP.get(type_name)
    if extensions is None:
        return False
    name = file_path.name
    return any(name.endswith(ext) for ext in extensions)


def _matches_glob(file_path: Path, pattern: str | None) -> bool:
    if pattern is None:
        return True
    return fnmatch.fnmatch(file_path.name, pattern)


def _safe_getmtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except (OSError, ValueError):
        return 0.0


@lru_cache(maxsize=1024)
def _is_sensitive_cached(path: str) -> bool:
    return is_sensitive_file(path)


@lru_cache(maxsize=128)
def _compile_regex_cached(pattern: str, flags: int) -> re.Pattern[str]:
    return re.compile(pattern, flags)


def _read_file_text(file_path: Path) -> str | None:
    """Read a file in a single pass: binary read, null-byte check, then decode."""
    try:
        with open(file_path, "rb") as f:
            data = f.read()
        if _is_binary(data):
            return None
        return data.decode("utf-8", errors="replace")
    except (OSError, UnicodeDecodeError):
        return None


def _merge_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not intervals:
        return []
    sorted_intervals = sorted(intervals, key=lambda x: x[0])
    merged: list[list[int]] = [list(sorted_intervals[0])]
    for start, end in sorted_intervals[1:]:
        if start <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(m[0], m[1]) for m in merged]


class Grep(CallableTool2[Params]):
    name: str = "Grep"
    description: str = load_desc(Path(__file__).parent / "grep.md")
    params: type[Params] = Params

    @override
    async def __call__(self, params: Params) -> ToolReturnValue:
        try:
            if not params.pattern:
                return ToolError(
                    message="Pattern cannot be empty.",
                    brief="Empty pattern",
                )

            flags = 0
            if params.ignore_case:
                flags |= re.IGNORECASE
            if params.multiline:
                flags |= re.DOTALL

            try:
                regex = _compile_regex_cached(params.pattern, flags)
            except re.error as e:
                return ToolError(
                    message=f"Invalid regex pattern: {e}",
                    brief="Invalid pattern",
                )

            search_path = Path(os.path.expanduser(params.path)).resolve()
            if not search_path.exists():
                return ToolError(
                    message=f"`{params.path}` does not exist.",
                    brief="Path not found",
                )

            output_mode = params.output_mode

            # Collect candidate files.
            files = self._collect_files(search_path, params)

            # Execute search in parallel across files.
            loop = asyncio.get_running_loop()
            max_workers = min(32, (os.cpu_count() or 1) + 4)

            def _process_one(file_path: Path) -> list[str]:
                text = _read_file_text(file_path)
                if text is None:
                    return []

                if output_mode == "files_with_matches":
                    if regex.search(text):
                        return [str(file_path)]
                    return []

                if output_mode == "count_matches":
                    count = len(list(regex.finditer(text)))
                    if count > 0:
                        return [f"{file_path}:{count}"]
                    return []

                # content mode
                return self._search_content_single(file_path, text, regex, params)

            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = [
                    loop.run_in_executor(executor, _process_one, f) for f in files
                ]
                results = await asyncio.gather(*futures)
                raw_lines = [line for r in results for line in r]

            # Filter sensitive files from output.
            filtered_paths: list[str] = []
            sensitive_path_set: set[str] = set()
            kept_lines: list[str] = []
            for line in raw_lines:
                file_path = self._extract_path(line, output_mode)
                if file_path and _is_sensitive_cached(file_path):
                    if file_path not in sensitive_path_set:
                        sensitive_path_set.add(file_path)
                        filtered_paths.append(file_path)
                else:
                    kept_lines.append(line)

            message = ""
            if filtered_paths:
                warning = sensitive_file_warning(filtered_paths)
                message = warning

            lines = kept_lines
            total_raw = 0
            files_truncated_early = False

            # Post-processing specific to output mode.
            if output_mode == "files_with_matches":
                total_raw = len(lines)
                lines_with_mtime = [(p, _safe_getmtime(p)) for p in lines]

                k = params.offset + (params.head_limit or 0)
                if k and len(lines) > k:
                    lines = [
                        p
                        for p, _ in heapq.nlargest(
                            k, lines_with_mtime, key=lambda x: x[1]
                        )
                    ]
                    files_truncated_early = True
                else:
                    lines_with_mtime.sort(key=lambda x: x[1], reverse=True)
                    lines = [p for p, _ in lines_with_mtime]

            elif output_mode == "count_matches":
                total_matches = 0
                total_files = 0
                for line in lines:
                    idx = line.rfind(":")
                    if idx > 0:
                        try:
                            total_matches += int(line[idx + 1 :])
                            total_files += 1
                        except ValueError:
                            pass
                count_summary = (
                    f"Found {total_matches} total occurrences across {total_files} files."
                )
                message = f"{message} {count_summary}" if message else count_summary

            # Strip search-base prefix for relative paths.
            search_base = str(search_path)
            if search_path.is_file():
                search_base = str(search_path.parent)
            lines = self._strip_path_prefix(lines, search_base)

            # Offset + head_limit pagination.
            if output_mode == "files_with_matches":
                if params.offset > 0:
                    lines = lines[params.offset:]

                effective_limit = params.head_limit
                if effective_limit and len(lines) > effective_limit:
                    total = len(lines) + params.offset
                    lines = lines[:effective_limit]
                    truncation_msg = (
                        f"Results truncated to {effective_limit} lines (total: {total}). "
                        f"Use offset={params.offset + effective_limit} to see more."
                    )
                    message = f"{message} {truncation_msg}" if message else truncation_msg
                elif (
                    effective_limit
                    and files_truncated_early
                    and len(lines) == effective_limit
                ):
                    truncation_msg = (
                        f"Results truncated to {effective_limit} lines (total: {total_raw}). "
                        f"Use offset={params.offset + effective_limit} to see more."
                    )
                    message = f"{message} {truncation_msg}" if message else truncation_msg
            else:
                if params.offset > 0:
                    lines = lines[params.offset:]

                effective_limit = params.head_limit
                if effective_limit and len(lines) > effective_limit:
                    total = len(lines) + params.offset
                    lines = lines[:effective_limit]
                    truncation_msg = (
                        f"Results truncated to {effective_limit} lines (total: {total}). "
                        f"Use offset={params.offset + effective_limit} to see more."
                    )
                    message = f"{message} {truncation_msg}" if message else truncation_msg

            builder = ToolResultBuilder()
            output = "\n".join(lines)

            if not output:
                no_match_msg = "No matches found"
                if message:
                    no_match_msg = f"{no_match_msg}. {message}"
                return builder.ok(message=no_match_msg)

            builder.write(output)
            return builder.ok(message=message)

        except Exception as e:
            logger.warning(
                "Grep backup failed: pattern={pattern}, path={path}: {error}",
                pattern=params.pattern,
                path=params.path,
                error=e,
            )
            return ToolError(
                message=f"Failed to grep. Error: {str(e)}",
                brief="Failed to grep",
            )

    def _collect_files(self, search_path: Path, params: Params) -> list[Path]:
        files: list[Path] = []
        if search_path.is_file():
            if self._is_valid_file(search_path, params):
                files.append(search_path)
        else:
            for root, dirs, filenames in os.walk(search_path):
                dirs[:] = [
                    d for d in dirs
                    if not _should_skip_dir(d, params.include_ignored)
                ]
                for filename in filenames:
                    file_path = Path(root) / filename
                    if self._is_valid_file(file_path, params):
                        files.append(file_path)
        return files

    def _is_valid_file(self, file_path: Path, params: Params) -> bool:
        if not file_path.is_file():
            return False
        try:
            if file_path.stat().st_size > _MAX_FILE_SIZE:
                return False
        except OSError:
            return False
        if not _matches_glob(file_path, params.glob):
            return False
        if not _matches_type(file_path, params.type):
            return False
        return True

    def _search_content_single(
        self, file_path: Path, content: str, regex: re.Pattern[str], params: Params
    ) -> list[str]:
        before = params.before_context or 0
        after = params.after_context or 0
        if params.context is not None:
            before = after = params.context

        if not content:
            return []

        lines = content.splitlines()
        match_line_nums: set[int] = set()

        if params.multiline:
            for m in regex.finditer(content):
                start_line = content.count("\n", 0, m.start()) + 1
                end_line = content.count("\n", 0, m.end()) + 1
                for ln in range(start_line, end_line + 1):
                    match_line_nums.add(ln)
        else:
            for i, line in enumerate(lines, 1):
                if regex.search(line):
                    match_line_nums.add(i)

        if not match_line_nums:
            return []

        intervals = [(ln - before, ln + after) for ln in match_line_nums]
        merged = _merge_intervals(intervals)

        results: list[str] = []
        for i, (start, end) in enumerate(merged):
            if i > 0:
                results.append("--")
            for ln in range(max(1, start), min(len(lines), end) + 1):
                text = lines[ln - 1]
                if ln in match_line_nums:
                    if params.line_number:
                        results.append(f"{file_path}:{ln}:{text}")
                    else:
                        results.append(f"{file_path}:{text}")
                else:
                    if params.line_number:
                        results.append(f"{file_path}-{ln}-{text}")
                    else:
                        results.append(f"{file_path}-{text}")

        return results

    def _extract_path(self, line: str, output_mode: str) -> str | None:
        if output_mode == "files_with_matches":
            return line
        if output_mode == "count_matches":
            idx = line.rfind(":")
            return line[:idx] if idx > 0 else line
        # content mode
        if line == "--":
            return None
        for i, ch in enumerate(line):
            if ch in (":", "-"):
                return line[:i]
        return line

    def _strip_path_prefix(self, lines: list[str], search_base: str) -> list[str]:
        prefix = search_base.rstrip("/\\")
        prefix_slash = prefix + "/"
        prefix_backslash = prefix + "\\"
        return [
            line[len(prefix_slash) :]
            if line.startswith(prefix_slash)
            else line[len(prefix_backslash) :]
            if line.startswith(prefix_backslash)
            else line
            for line in lines
        ]
