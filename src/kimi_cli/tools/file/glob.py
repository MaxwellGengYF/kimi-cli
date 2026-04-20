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
from kimi_cli.utils.path import is_within_directory, is_within_workspace, list_directory

MAX_MATCHES = 1000


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
    description: str = load_desc(
        Path(__file__).parent / "glob.md",
        {
            "MAX_MATCHES": str(MAX_MATCHES),
        },
    )
    params: type[Params] = Params

    def __init__(self, runtime: Runtime) -> None:
        super().__init__()
        self._work_dir = runtime.builtin_args.KIMI_WORK_DIR
        self._additional_dirs = runtime.additional_dirs
        self._skills_dirs = runtime.skills_dirs

    async def _validate_pattern(self, pattern: str) -> ToolError | None:
        """Validate that the pattern is safe to use."""
        if pattern.startswith("**"):
            ls_result = await list_directory(self._work_dir)
            return ToolError(
                output=ls_result,
                message=(
                    f"Pattern `{pattern}` starts with '**', which is not allowed as it "
                    "recursively searches all directories and may include large ones like "
                    "`node_modules`. Use a more specific pattern. Below are the top-level "
                    "files and directories in the working directory."
                ),
                brief="Unsafe pattern",
            )
        return None

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

            dir_path = (
                KaosPath(params.directory).expanduser() if params.directory else self._work_dir
            )

            # if not dir_path.is_absolute():
            #     return ToolError(
            #         message=(
            #             f"`{params.directory}` is not an absolute path. "
            #             "You must provide an absolute path to search."
            #         ),
            #         brief="Invalid directory",
            #     )

            # # Validate directory safety
            # dir_error = await self._validate_directory(dir_path)
            # if dir_error:
            #     return dir_error

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
                    f" Only the first {MAX_MATCHES} matches are returned. "
                    "You may want to use a more specific pattern."
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
                message=f"Failed to search for pattern {params.pattern}. Error: {e}",
                brief="Glob failed",
            )
