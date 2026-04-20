import json
import demjson3
from collections.abc import Callable
from pathlib import Path
from typing import Literal, override

from kaos.path import KaosPath
from kosong.tooling import CallableTool2, DisplayBlock, ToolError, ToolReturnValue
from pydantic import BaseModel, Field

from kimi_cli.soul.agent import Runtime
from kimi_cli.soul.approval import Approval
from kimi_cli.tools.display import DiffDisplayBlock
from kimi_cli.tools.file import FileActions
from kimi_cli.tools.file.check_fmt import check_json_text, check_xml_text
from kimi_cli.tools.file.plan_mode import inspect_plan_edit_target
from kimi_cli.utils.diff import build_diff_blocks
from kimi_cli import logger
from kimi_cli.utils.path import is_within_workspace

_BASE_DESCRIPTION = (
    "Write to files. Default `overwrite`—use caution. "
    "For content over 100 lines, split into multiple calls; use `append` after the first write."
)


class Params(BaseModel):
    path: str = Field(
        description="File path. Absolute paths required outside the working directory."
    )
    content: str = Field(description="Content to write.")
    mode: Literal["overwrite", "append"] = Field(
        description="Write mode: overwrite or append.",
        default="overwrite",
    )
    fix_foramt: bool = Field(
        default=True,
        description='Auto fix file format.'
    )


class WriteFile(CallableTool2[Params]):
    name: str = "WriteFile"
    description: str = _BASE_DESCRIPTION
    params: type[Params] = Params

    def __init__(self, runtime: Runtime, approval: Approval):
        super().__init__()
        self._work_dir = runtime.builtin_args.KIMI_WORK_DIR
        self._additional_dirs = runtime.additional_dirs
        self._approval = approval
        self._plan_mode_checker: Callable[[], bool] | None = None
        self._plan_file_path_getter: Callable[[], Path | None] | None = None

    def bind_plan_mode(
        self, checker: Callable[[], bool], path_getter: Callable[[], Path | None]
    ) -> None:
        """Bind plan mode state checker and plan file path getter."""
        self._plan_mode_checker = checker
        self._plan_file_path_getter = path_getter

    async def _validate_path(self, path: KaosPath) -> tuple[ToolError | None, bool]:
        """Validate that the path is safe to write.

        Returns:
            A tuple of (error_or_none, is_inside_workspace).
        """
        resolved_path = path.canonical()

        inside = is_within_workspace(
            resolved_path, self._work_dir, self._additional_dirs
        )
        if not inside and not path.is_absolute():
            return (
                ToolError(
                    message=(
                        f"`{path}` is not an absolute path. "
                        "You must provide an absolute path to write a file "
                        "outside the working directory."
                    ),
                    brief="Invalid path",
                ),
                False,
            )
        return None, inside

    @override
    async def __call__(self, params: Params) -> ToolReturnValue:
        # TODO: checks:
        # - check if the path may contain secrets
        if not params.path:
            return ToolError(
                message="File path cannot be empty.",
                brief="Empty file path",
            )

        try:
            p = KaosPath(params.path).expanduser()

            err, path_is_inside = await self._validate_path(p)
            if err:
                return err
            p = p.canonical()

            if await p.is_dir():
                return ToolError(
                    message=f"`{p}` is a directory, not a file.",
                    brief="Path is a directory",
                )

            plan_target = inspect_plan_edit_target(
                p,
                plan_mode_checker=self._plan_mode_checker,
                plan_file_path_getter=self._plan_file_path_getter,
            )
            if isinstance(plan_target, ToolError):
                return plan_target

            is_plan_file_write = plan_target.is_plan_target
            if is_plan_file_write and plan_target.plan_path is not None:
                plan_target.plan_path.parent.mkdir(parents=True, exist_ok=True)

            try:
                await p.parent.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                return ToolError(
                    message=f"Failed to create parent directory for {p}: {e}",
                    brief="Parent directory not found",
                )

            # Validate mode parameter
            if params.mode not in ["overwrite", "append"]:
                return ToolError(
                    message=(
                        f"Invalid write mode: `{params.mode}`. "
                        "Mode must be either `overwrite` or `append`."
                    ),
                    brief="Invalid write mode",
                )

            old_text = ""
            file_existed = False
            try:
                old_text = await p.read_text(encoding="utf-8", errors="strict")
                file_existed = True
            except FileNotFoundError:
                pass

            if params.mode == "overwrite":
                new_text = params.content
            else:
                new_text = old_text + params.content

            # In-memory format validation & fix (before any write)
            fmt_error = None
            file_path_str = str(p)
            is_json = file_path_str.lower().endswith(".json")
            if is_json:
                fmt_error = check_json_text(new_text)
            elif file_path_str.lower().endswith(".xml"):
                fmt_error = check_xml_text(new_text)

            if fmt_error and is_json and params.fix_foramt:
                try:
                    decoded = demjson3.decode(new_text, encoding="utf-8", strict=False)
                    new_text = json.dumps(decoded)
                    fmt_error = None
                except demjson3.JSONDecodeError as e:
                    fmt_error = f"JSON decode error: {str(e)}"
                except Exception as exc:
                    fmt_error = f"failed to validate JSON file: {str(exc)}"

            if fmt_error:
                return ToolError(
                    message=f"File content invalid: {fmt_error}",
                    brief="Format validation failed",
                )

            # Build diff blocks
            diff_blocks: list[DisplayBlock]
            if params.mode == "append" and file_existed:
                # Fast path: synthetic diff for append
                old_lines = old_text.splitlines()
                old_start = max(1, len(old_lines) - 2)
                old_context = "\n".join(old_lines[old_start - 1 :]) if old_lines else ""
                new_context = (
                    (old_context + "\n" if old_context else "") + params.content
                ).rstrip("\n")
                diff_blocks = [
                    DiffDisplayBlock(
                        path=file_path_str,
                        old_text=old_context,
                        new_text=new_context,
                        old_start=old_start,
                        new_start=old_start,
                    )
                ]
            else:
                diff_blocks = await build_diff_blocks(
                    file_path_str,
                    old_text,
                    new_text,
                )

            # Plan file writes are auto-approved; other writes need approval
            if not is_plan_file_write:
                action = (
                    FileActions.EDIT
                    if path_is_inside
                    else FileActions.EDIT_OUTSIDE
                )

                # Request approval
                result = await self._approval.request(
                    self.name,
                    action,
                    f"Write file `{p}`",
                    display=diff_blocks,
                )
                if not result:
                    return result.rejection_error()

            # Write content to file
            if params.mode == "append" and file_existed:
                await p.append_text(params.content, encoding="utf-8", errors="strict")
            else:
                await p.write_text(new_text, encoding="utf-8", errors="strict")

            # Compute file size in-memory
            file_size = len(new_text.encode("utf-8"))
            action_desc = "overwritten" if params.mode == "overwrite" else "appended to"

            return ToolReturnValue(
                is_error=False,
                output="",
                message=(
                    f"File successfully {action_desc}. Current size: {file_size} bytes."
                ),
                display=diff_blocks,
            )

        except Exception as e:
            logger.warning(
                "WriteFile failed: {path}: {error}", path=params.path, error=e
            )
            return ToolError(
                message=f"Failed to write to {params.path}. Error: {e}",
                brief="Failed to write file",
            )
