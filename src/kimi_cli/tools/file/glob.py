"""Glob tool implementation."""

import asyncio
from pathlib import Path
from typing import override

from kaos.path import KaosPath
from kosong.tooling import CallableTool2, ToolError, ToolOk, ToolReturnValue
from pydantic import BaseModel, Field

from kimi_cli.soul.agent import Runtime
from kimi_cli.tools.utils import load_desc
from kimi_cli.utils.logging import logger
from kimi_cli.vfs import VFS
from .utils import resolve_vfs
from kimi_cli.utils.path import (
    is_within_directory,
    is_within_workspace,
    kaos_path_from_user_input,
    list_directory,
)
MAX_MATCHES = 1000
GLOB_DESC_PATH = Path(__file__).parent / "glob.md"
WINDOWS_PATH_HINT = (
    "Windows: `directory` accepts native (`C:\\Users\\foo`) and POSIX-style "
    "(`/c/Users/foo`) paths. Results use backslashes — convert to forward "
    "slashes for shell commands."
)


def _description_for_os(os_kind: str) -> str:
    return load_desc(
        GLOB_DESC_PATH,
        {
            "MAX_MATCHES": str(MAX_MATCHES),
            "WINDOWS_PATH_HINT": WINDOWS_PATH_HINT if os_kind == "Windows" else "",
        },
    )


class Params(BaseModel):
    pattern: str = Field(description="Glob pattern. Never start with `**`.")
    directory: str | None = Field(
        description="Absolute search path. Defaults to working directory.",
        default=None,
    )
    include_dirs: bool = Field(
        description="Include directories in results.",
        default=True,
    )


class Glob(CallableTool2[Params]):
    name: str = "Glob"
    description: str = _description_for_os("")
    params: type[Params] = Params
    def __init__(self, runtime: Runtime, vfs: VFS | None = None) -> None:
        super().__init__(description=_description_for_os(runtime.environment.os_kind))
        self._work_dir = runtime.builtin_args.KIMI_WORK_DIR
        self._additional_dirs = runtime.additional_dirs
        self._skills_dirs = runtime.skills_dirs
        self._vfs = vfs

    async def _validate_pattern(self, pattern: str) -> ToolError | None:
        """Validate that the pattern is safe to use."""
        # Normalize backslashes for consistent cross-platform validation
        norm = pattern.replace("\\", "/")
        if not norm.startswith("**"):
            return None

        ls_result = await list_directory(self._work_dir)

        if norm == "**/**" or norm == "**/*":
            return ToolError(
                output=ls_result,
                message=(
                    f"Pattern `{pattern}` starts with `**`, which is disallowed. "
                    "Use a more specific pattern. Top-level items in working directory:"
                ),
                brief="Unsafe pattern",
            )

        # For **/<file-name>, also check if the file exists at the root directory
        if norm.startswith("**/") and "/" not in norm[3:]:
            file_name = norm[3:]
            root_file = self._work_dir / file_name
            if await root_file.exists():
                rel_path = str(root_file.relative_to(self._work_dir))
                ls_result = f"{ls_result}\n{rel_path}"

        return ToolError(
            output=ls_result,
            message=(
                f"Pattern `{pattern}` starts with `**`, which is disallowed. "
                "Use a more specific pattern. Top-level items in working directory:"
            ),
            brief="Unsafe pattern",
        )

    # async def _validate_directory(self, directory: KaosPath) -> ToolError | None:
    #     """Validate that the directory is safe to search."""
    #     resolved_dir = directory.canonical()

    #     # Allow directories within the workspace (work_dir or additional dirs)
    #     if is_within_workspace(resolved_dir, self._work_dir, self._additional_dirs):
    #         return None

    #     # Allow directories within any discovered skills root
    #     if any(is_within_directory(resolved_dir, d) for d in self._skills_dirs):
    #         return None

    #     return ToolError(
    #         message=(
    #             f"`{directory}` is outside the workspace. "
    #             "You can only search within the working directory, "
    #             "additional directories, and skills directories."
    #         ),
    #         brief="Directory outside workspace",
    #     )

    @override
    async def __call__(self, params: Params) -> ToolReturnValue:
        try:
            # Validate pattern safety
            pattern_error = await self._validate_pattern(params.pattern)
            if pattern_error:
                return pattern_error
            dir_path = KaosPath(str(kaos_path_from_user_input(params.directory)) if params.directory else str(self._work_dir))
            dir_path = await resolve_vfs(str(dir_path), self._vfs, for_write=False)
            if not await dir_path.exists():
                return ToolError(
                    message=f"`{params.directory}` does not exist.",
                    brief="Directory not found",
                )
            if not await dir_path.is_dir():
                return ToolError(
                    message=f"`{params.directory}` is not a directory.",
                    brief="Invalid directory",
                )

            # Perform the glob search - bounded streaming with inline filtering
            matches: list[KaosPath] = []
            truncated = False
            try:
                async with asyncio.timeout(10):
                    async for match in dir_path.glob(params.pattern):
                        if not params.include_dirs and not await match.is_file():
                            continue
                        matches.append(match)
                        if len(matches) > MAX_MATCHES:
                            truncated = True
                            matches.pop()
                            break
            except asyncio.TimeoutError:
                truncated = True

            # Sort for consistent output
            matches.sort()

            # Build message
            if len(matches) > 0:
                message = f"Found {len(matches)} matches for pattern `{params.pattern}`."
            else:
                message = f"No matches found for pattern `{params.pattern}`."

            if truncated:
                message += (
                    f" Showing first {MAX_MATCHES} matches. "
                    "Use a more specific pattern."
                )

            return ToolOk(
                output="\n".join(str(p.relative_to(dir_path)) for p in matches),
                message=message,
            )

        except Exception as e:
            logger.warning(
                "Glob failed: pattern={pattern}: {error}", pattern=params.pattern, error=e
            )
            return ToolError(
                message=f"Glob failed for `{params.pattern}`: {e}",
                brief="Glob failed",
            )
