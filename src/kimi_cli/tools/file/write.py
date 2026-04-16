import json
import demjson3
from collections.abc import Callable
from pathlib import Path
from typing import Literal, override

from kaos.path import KaosPath
from kosong.tooling import CallableTool2, ToolError, ToolReturnValue
from pydantic import BaseModel, Field

from kimi_cli.soul.agent import Runtime
from kimi_cli.soul.approval import Approval
from kimi_cli.tools.display import DisplayBlock
from kimi_cli.tools.file import FileActions
from kimi_cli.tools.file.check_fmt import check_json, check_xml
from kimi_cli.tools.file.plan_mode import inspect_plan_edit_target
from kimi_cli.utils.diff import build_diff_blocks
from kimi_cli.utils.logging import logger
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

    async def _validate_path(self, path: KaosPath) -> ToolError | None:
        """Validate that the path is safe to write."""
        resolved_path = path.canonical()

        if (
            not is_within_workspace(
                resolved_path, self._work_dir, self._additional_dirs)
            and not path.is_absolute()
        ):
            return ToolError(
                message=(
                    f"`{path}` is not an absolute path. "
                    "You must provide an absolute path to write a file "
                    "outside the working directory."
                ),
                brief="Invalid path",
            )
        return None

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

            if err := await self._validate_path(p):
                return err
            p = p.canonical()

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

            if not await p.parent.exists():
                try:
                    await p.parent.mkdir(parents=True)
                except:
                    return ToolError(
                        message=f"`{params.path}` parent directory does not exist.",
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

            file_existed = await p.exists()
            old_text = None
            if file_existed:
                old_text = await p.read_text(errors="replace")

            new_text = (
                params.content if params.mode == "overwrite" else (
                    old_text or "") + params.content
            )
            diff_blocks: list[DisplayBlock] = await build_diff_blocks(
                str(p),
                old_text or "",
                new_text,
            )

            # Plan file writes are auto-approved; other writes need approval
            if not is_plan_file_write:
                action = (
                    FileActions.EDIT
                    if is_within_workspace(p, self._work_dir, self._additional_dirs)
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
            match params.mode:
                case "overwrite":
                    await p.write_text(params.content)
                case "append":
                    await p.append_text(params.content)

            # Get file info for success message
            file_size = (await p.stat()).st_size
            action = "overwritten" if params.mode == "overwrite" else "appended to"

            # Check file format for JSON/XML files
            fmt_error = None
            file_path_str = str(p)
            is_json = file_path_str.lower().endswith(".json")
            if is_json:
                fmt_error = await check_json(file_path_str)
            elif file_path_str.lower().endswith(".xml"):
                fmt_error = await check_xml(file_path_str)
            if fmt_error and is_json and params.fix_foramt:
                try:
                    current_text:str = await p.read_text(encoding="utf-8")
                    decoded = demjson3.decode(current_text, encoding='utf-8', strict=False)
                    fixed_text: str = json.dumps(decoded)
                    await p.write_text(fixed_text)
                    fmt_error = None # Dump success, no need to check
                except demjson3.JSONDecodeError as e:
                    fmt_error = f"JSON decode error: {str(e)}"
                except Exception as exc:
                    fmt_error = f"failed to validate JSON file: {str(exc)}"
            if fmt_error:
                return ToolError(
                    message=f"File successfully {action}, but {fmt_error}",
                    brief="Format validation failed",
                )

            return ToolReturnValue(
                is_error=False,
                output="",
                message=(
                    f"File successfully {action}. Current size: {file_size} bytes."),
                display=diff_blocks,
            )

        except Exception as e:
            logger.warning(
                "WriteFile failed: {path}: {error}", path=params.path, error=e)
            return ToolError(
                message=f"Failed to write to {params.path}. Error: {e}",
                brief="Failed to write file",
            )
