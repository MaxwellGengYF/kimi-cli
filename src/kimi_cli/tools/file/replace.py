import asyncio
from collections.abc import Callable
from pathlib import Path
from stat import S_ISREG
from typing import override

from kaos.path import KaosPath
from kosong.tooling import CallableTool2, ToolError, ToolReturnValue
from pydantic import BaseModel, Field

from kimi_cli.soul.agent import Runtime
from kimi_cli.soul.approval import Approval
from kimi_cli.tools.display import DisplayBlock
from kimi_cli.tools.file import FileActions
from kimi_cli.tools.file.check_fmt import check_json_text, check_xml_text
from kimi_cli.tools.file.plan_mode import inspect_plan_edit_target
from kimi_cli.tools.utils import load_desc
from kimi_cli.utils.diff import build_diff_blocks
from kimi_cli.utils.logging import logger
from kimi_cli.utils.path import is_within_workspace, kaos_path_from_user_input
from kimi_cli.vfs import VFS
from .utils import resolve_vfs

_BASE_DESCRIPTION = load_desc(Path(__file__).parent / "replace.md")


class Edit(BaseModel):
    old: str = Field(description="String to replace.")
    new: str = Field(description="Replacement string.")
    replace_all: bool = Field(description="Replace all occurrences.", default=False)


class Params(BaseModel):
    path: str = Field(
        description="File path. Absolute path required outside working directory."
    )
    edit: Edit | list[Edit] = Field(
        description="One or more edits."
    )


class StrReplaceFile(CallableTool2[Params]):
    name: str = "StrReplaceFile"
    description: str = _BASE_DESCRIPTION
    params: type[Params] = Params

    def __init__(self, runtime: Runtime, approval: Approval, vfs: VFS | None = None):
        super().__init__()
        self._work_dir = runtime.builtin_args.KIMI_WORK_DIR
        self._additional_dirs = runtime.additional_dirs
        self._approval = approval
        self._vfs = vfs
        self._plan_mode_checker: Callable[[], bool] | None = None
        self._plan_file_path_getter: Callable[[], Path | None] | None = None

    def bind_plan_mode(
        self, checker: Callable[[], bool], path_getter: Callable[[], Path | None]
    ) -> None:
        """Bind plan mode state checker and plan file path getter."""
        self._plan_mode_checker = checker
        self._plan_file_path_getter = path_getter

    async def _validate_path(self, path: KaosPath) -> tuple[ToolError | None, bool]:
        """Validate that the path is safe to edit.

        Returns:
            A tuple of (error_or_none, is_inside_workspace).
        """
        resolved_path = path.canonical()

        inside = is_within_workspace(resolved_path, self._work_dir, self._additional_dirs)
        if not inside and not path.is_absolute():
            return (
                ToolError(
                    message=(
                        f"`{path}` is not an absolute path. "
                        "You must provide an absolute path to edit a file "
                        "outside the working directory."
                    ),
                    brief="Invalid path",
                ),
                False,
            )
        return None, inside

    def _apply_edit(self, content: str, edit: Edit) -> tuple[str, int]:
        """Apply a single edit to the content and return (new_content, replacements_made)."""
        if not edit.old or edit.old == edit.new:
            return content, 0

        if edit.replace_all:
            count = content.count(edit.old)
            if count == 0:
                return content, 0
            return content.replace(edit.old, edit.new), count

        # Single replacement
        idx = content.find(edit.old)
        if idx == -1:
            return content, 0
        return content.replace(edit.old, edit.new, 1), 1

    @override
    async def __call__(self, params: Params) -> ToolReturnValue:
        if not params.path:
            return ToolError(
                message="File path cannot be empty.",
                brief="Empty file path",
            )

        try:
            p = kaos_path_from_user_input(params.path)
            logical_path = p
            err, _ = await self._validate_path(p)
            if err:
                return err

            p = await resolve_vfs(params.path, self._vfs, for_write=True)

            plan_target = inspect_plan_edit_target(
                logical_path,
                plan_mode_checker=self._plan_mode_checker,
                plan_file_path_getter=self._plan_file_path_getter,
            )
            if isinstance(plan_target, ToolError):
                return plan_target

            is_plan_file_edit = plan_target.is_plan_target

            try:
                st = await p.stat()
                if not S_ISREG(st.st_mode):
                    return ToolError(
                        message=f"`{logical_path}` is not a file.",
                        brief="Invalid path",
                    )
            except FileNotFoundError:
                if is_plan_file_edit:
                    return ToolError(
                        message=(
                            "The current plan file does not exist yet. "
                            "Use WriteFile to create it before calling StrReplaceFile."
                        ),
                        brief="Plan file not created",
                    )
                return ToolError(
                    message=f"`{logical_path}` does not exist.",
                    brief="File not found",
                )

            # Read the file content
            content = await p.read_text(errors="replace")

            original_content = content
            edits = [params.edit] if isinstance(params.edit, Edit) else params.edit

            def _work() -> tuple[str, int]:
                text = content
                total = 0
                for edit in edits:
                    text, n = self._apply_edit(text, edit)
                    total += n
                return text, total

            new_content, total_replacements = await asyncio.to_thread(_work)

            # Check if any changes were made
            if new_content == original_content:
                return ToolError(
                    message="No replacements were made. The old string was not found in the file.",
                    brief="No replacements made",
                )

            diff_blocks: list[DisplayBlock] = await build_diff_blocks(
                str(logical_path), original_content, new_content
            )

            action = (
                FileActions.EDIT
                if is_within_workspace(p, self._work_dir, self._additional_dirs)
                else FileActions.EDIT_OUTSIDE
            )

            # Plan file edits are auto-approved; all other edits need approval.
            if not is_plan_file_edit:
                result = await self._approval.request(
                    self.name,
                    action,
                    f"Edit file `{logical_path}`",
                    display=diff_blocks,
                )
                if not result:
                    return result.rejection_error()

            # Fix JSON format before writing if needed
            file_path_str = str(logical_path)
            fmt_error = None
            suffix = Path(file_path_str).suffix.lower()
            is_json = suffix == ".json"
            if is_json:
                fmt_error = check_json_text(new_content)
            elif suffix == ".xml":
                fmt_error = check_xml_text(new_content)

            # Write the modified content back to the file
            await p.write_text(new_content, errors="replace")

            if fmt_error:
                return ToolError(
                    message=f"File successfully edited, but {fmt_error}",
                    brief="Format validation failed",
                )

            return ToolReturnValue(
                is_error=False,
                output="",
                message=(
                    f"File successfully edited. "
                    f"Applied {len(edits)} edit(s) with {total_replacements} total replacement(s)."
                ),
                display=diff_blocks,
            )

        except (OSError, ValueError, RuntimeError) as e:
            logger.warning("StrReplaceFile failed: {path}: {error}", path=params.path, error=e)
            return ToolError(
                message=f"Failed to edit. Error: {e}",
                brief="Failed to edit file",
            )
        except MemoryError:
            raise
