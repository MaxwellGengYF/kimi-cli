"""Tests for StepMemory tool."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import pytest

from kosong.tooling import ToolError, ToolOk
from kimi_cli.soul.agent import Runtime
from kimi_cli.tools.step_mem import Params, StepMemory


@pytest.fixture
def step_memory_tool(runtime: Runtime) -> StepMemory:
    """Create a StepMemory tool instance with runtime."""
    return StepMemory(runtime)


class TestStepMemorySave:
    """Test StepMemory save action."""

    async def test_save_basic(self, step_memory_tool: StepMemory, runtime: Runtime):
        """Save a basic step and verify it is persisted."""
        params = Params(action="save", step="Created user model")
        result = await step_memory_tool(params)

        assert not result.is_error
        assert result.message == "Step recorded"
        assert "Step #1 saved" in result.output
        assert "Created user model" in result.output

        # Verify on disk
        path = step_memory_tool._storage_path()
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["seq"] == 1
        assert data[0]["step"] == "Created user model"
        assert data[0]["result"] == ""
        assert data[0]["files"] == []
        assert data[0]["brief"] == "Created user model"
        assert "time" in data[0]

    async def test_save_with_all_fields(self, step_memory_tool: StepMemory):
        """Save with all optional fields provided."""
        params = Params(
            action="save",
            step="Defined SQLAlchemy User model with id/name/email",
            result="Success",
            files=["models/user.py", "models/__init__.py"],
            brief="Create User model",
        )
        result = await step_memory_tool(params)

        assert not result.is_error
        assert "Step #1 saved" in result.output
        assert "Create User model" in result.output

        steps = step_memory_tool._load_steps()
        assert len(steps) == 1
        assert steps[0]["step"] == "Defined SQLAlchemy User model with id/name/email"
        assert steps[0]["result"] == "Success"
        assert steps[0]["files"] == ["models/user.py", "models/__init__.py"]
        assert steps[0]["brief"] == "Create User model"

    async def test_save_missing_step_returns_error(self, step_memory_tool: StepMemory):
        """Save without step field should return ToolError."""
        params = Params(action="save")
        result = await step_memory_tool(params)

        assert result.is_error
        assert isinstance(result, ToolError)
        assert "Field 'step' is required" in result.message
        assert result.brief == "Missing step description"

    async def test_save_empty_step_returns_error(self, step_memory_tool: StepMemory):
        """Save with empty step string should return ToolError."""
        params = Params(action="save", step="")
        result = await step_memory_tool(params)

        assert result.is_error
        assert "Field 'step' is required" in result.message

    async def test_save_seq_increments(self, step_memory_tool: StepMemory):
        """Sequential saves should increment seq."""
        for i in range(1, 4):
            params = Params(action="save", step=f"Step {i}")
            result = await step_memory_tool(params)
            assert not result.is_error
            assert f"Step #{i} saved" in result.output

        steps = step_memory_tool._load_steps()
        assert len(steps) == 3
        assert steps[0]["seq"] == 1
        assert steps[1]["seq"] == 2
        assert steps[2]["seq"] == 3

    async def test_save_brief_fallback_to_step_truncation(self, step_memory_tool: StepMemory):
        """If brief is not provided, it should fallback to step[:50]."""
        long_step = "A" * 100
        params = Params(action="save", step=long_step)
        result = await step_memory_tool(params)

        assert not result.is_error
        steps = step_memory_tool._load_steps()
        assert steps[0]["brief"] == "A" * 50

    async def test_save_result_defaults_to_empty_string(self, step_memory_tool: StepMemory):
        """If result is not provided, it should default to empty string."""
        params = Params(action="save", step="Do something")
        result = await step_memory_tool(params)

        steps = step_memory_tool._load_steps()
        assert steps[0]["result"] == ""

    async def test_save_files_defaults_to_empty_list(self, step_memory_tool: StepMemory):
        """If files is not provided, it should default to empty list."""
        params = Params(action="save", step="Do something")
        result = await step_memory_tool(params)

        steps = step_memory_tool._load_steps()
        assert steps[0]["files"] == []

    async def test_save_persists_across_instances(self, runtime: Runtime):
        """Steps should persist when read by a new StepMemory instance."""
        tool1 = StepMemory(runtime)
        await tool1(Params(action="save", step="First step"))

        tool2 = StepMemory(runtime)
        result = await tool2(Params(action="load"))
        assert not result.is_error
        assert "First step" in result.output

    async def test_save_with_files_none(self, step_memory_tool: StepMemory):
        """Save with explicit files=None should work."""
        params = Params(action="save", step="Do something", files=None)
        result = await step_memory_tool(params)

        assert not result.is_error
        steps = step_memory_tool._load_steps()
        assert steps[0]["files"] == []

    async def test_save_with_result_none(self, step_memory_tool: StepMemory):
        """Save with explicit result=None should work."""
        params = Params(action="save", step="Do something", result=None)
        result = await step_memory_tool(params)

        assert not result.is_error
        steps = step_memory_tool._load_steps()
        assert steps[0]["result"] == ""

    async def test_save_with_brief_none(self, step_memory_tool: StepMemory):
        """Save with explicit brief=None should fallback to step[:50]."""
        params = Params(action="save", step="Short step", brief=None)
        result = await step_memory_tool(params)

        assert not result.is_error
        steps = step_memory_tool._load_steps()
        assert steps[0]["brief"] == "Short step"


class TestStepMemoryLoad:
    """Test StepMemory load action."""

    async def test_load_empty_history(self, step_memory_tool: StepMemory):
        """Load with no history should return empty message."""
        params = Params(action="load")
        result = await step_memory_tool(params)

        assert not result.is_error
        assert isinstance(result, ToolOk)
        assert "No step history found" in result.output
        assert result.message == "Empty history"

    async def test_load_returns_formatted_history(self, step_memory_tool: StepMemory):
        """Load should return formatted step history."""
        await step_memory_tool(
            Params(
                action="save",
                step="Created model",
                result="Success",
                files=["a.py"],
                brief="Create model",
            )
        )

        params = Params(action="load")
        result = await step_memory_tool(params)

        assert not result.is_error
        assert "Step history (1 entries)" in result.output
        assert "#1" in result.output
        assert "Create model" in result.output
        assert "Created model" in result.output
        assert "Success" in result.output
        assert "a.py" in result.output
        assert result.message == "Loaded 1 steps"

    async def test_load_multiple_entries(self, step_memory_tool: StepMemory):
        """Load should format multiple entries with separators."""
        await step_memory_tool(Params(action="save", step="Step one"))
        await step_memory_tool(Params(action="save", step="Step two"))

        result = await step_memory_tool(Params(action="load"))
        assert not result.is_error
        assert "Step history (2 entries)" in result.output
        assert "Step one" in result.output
        assert "Step two" in result.output

    async def test_load_omits_files_when_empty(self, step_memory_tool: StepMemory):
        """Load should not show files section when files list is empty."""
        await step_memory_tool(Params(action="save", step="No files step"))

        result = await step_memory_tool(Params(action="load"))
        assert not result.is_error
        assert "files:" not in result.output

    async def test_load_shows_files_when_present(self, step_memory_tool: StepMemory):
        """Load should show files section when files are present."""
        await step_memory_tool(
            Params(action="save", step="With files", files=["x.py", "y.py"])
        )

        result = await step_memory_tool(Params(action="load"))
        assert not result.is_error
        assert "files: x.py, y.py" in result.output


class TestStepMemoryCompaction:
    """Test automatic compaction of old steps."""

    async def test_no_compaction_under_limit(self, step_memory_tool: StepMemory):
        """Steps at or under _MAX_ENTRIES should not be compacted."""
        for i in range(5):
            await step_memory_tool(Params(action="save", step=f"Step {i}"))

        steps = step_memory_tool._load_steps()
        assert len(steps) == 5
        for s in steps:
            assert "[compacted]" not in s["step"]

    async def test_maybe_compact_at_exact_limit(self, step_memory_tool: StepMemory):
        """Steps exactly at _MAX_ENTRIES should not be compacted."""
        # Temporarily lower MAX_ENTRIES for test speed
        original_max = step_memory_tool._MAX_ENTRIES
        step_memory_tool._MAX_ENTRIES = 10
        try:
            for i in range(10):
                await step_memory_tool(Params(action="save", step=f"Step {i}"))

            steps = step_memory_tool._load_steps()
            assert len(steps) == 10
            for s in steps:
                assert "[compacted]" not in s["step"]
        finally:
            step_memory_tool._MAX_ENTRIES = original_max

    async def test_maybe_compact_over_limit(self, step_memory_tool: StepMemory):
        """Steps over _MAX_ENTRIES should compact the oldest half."""
        original_max = step_memory_tool._MAX_ENTRIES
        step_memory_tool._MAX_ENTRIES = 10
        try:
            for i in range(11):
                await step_memory_tool(
                    Params(action="save", step=f"Step {i}", result=f"Result {i}", brief=f"Brief {i}")
                )

            steps = step_memory_tool._load_steps()
            assert len(steps) == 11
            # Oldest 5 should be compacted
            for s in steps[:5]:
                assert s["step"].startswith("[compacted]")
                assert s["result"] == "[compacted]"
                assert s["files"] == []
                assert "brief" in s  # brief preserved for indexing
            # Newer half should remain intact
            for s in steps[5:]:
                assert "[compacted]" not in s["step"]
                assert "[compacted]" not in s["result"]
        finally:
            step_memory_tool._MAX_ENTRIES = original_max

    async def test_compaction_preserves_brief(self, step_memory_tool: StepMemory):
        """Compacted entries should preserve brief for indexing."""
        original_max = step_memory_tool._MAX_ENTRIES
        step_memory_tool._MAX_ENTRIES = 4
        try:
            for i in range(5):
                await step_memory_tool(
                    Params(action="save", step=f"Step {i}", brief=f"Brief{i}")
                )

            steps = step_memory_tool._load_steps()
            assert steps[0]["brief"] == "Brief0"
            assert steps[0]["step"].startswith("[compacted]")
        finally:
            step_memory_tool._MAX_ENTRIES = original_max

    async def test_compaction_truncates_long_steps(self, step_memory_tool: StepMemory):
        """Compacted step text should be truncated to 100 chars."""
        original_max = step_memory_tool._MAX_ENTRIES
        step_memory_tool._MAX_ENTRIES = 4
        try:
            long_step = "A" * 200
            await step_memory_tool(Params(action="save", step=long_step))
            for i in range(4):
                await step_memory_tool(Params(action="save", step=f"Filler {i}"))

            steps = step_memory_tool._load_steps()
            compacted_step = steps[0]["step"]
            assert compacted_step.startswith("[compacted]")
            # "[compacted] " prefix is 12 chars, plus 100 chars = 112 total
            assert len(compacted_step) == 12 + 100
        finally:
            step_memory_tool._MAX_ENTRIES = original_max

    def test_maybe_compact_direct_under_limit(self, step_memory_tool: StepMemory):
        """Direct call to _maybe_compact with under-limit steps returns unchanged."""
        steps = [{"seq": i, "step": f"s{i}"} for i in range(5)]
        result = step_memory_tool._maybe_compact(steps)
        assert result == steps

    def test_maybe_compact_direct_over_limit(self, step_memory_tool: StepMemory):
        """Direct call to _maybe_compact with over-limit steps compacts oldest half."""
        original_max = step_memory_tool._MAX_ENTRIES
        step_memory_tool._MAX_ENTRIES = 10
        try:
            steps = [
                {
                    "seq": i,
                    "time": "2025-01-01T00:00:00",
                    "brief": f"b{i}",
                    "step": f"step{i}",
                    "result": f"result{i}",
                    "files": [f"f{i}.py"],
                }
                for i in range(11)
            ]
            result = step_memory_tool._maybe_compact(steps)
            assert len(result) == 11
            for s in result[:5]:
                assert s["step"].startswith("[compacted]")
                assert s["result"] == "[compacted]"
                assert s["files"] == []
                assert s["brief"] == f"b{ s['seq'] }"
            for s in result[5:]:
                assert s["step"] == f"step{s['seq']}"
                assert s["result"] == f"result{s['seq']}"
        finally:
            step_memory_tool._MAX_ENTRIES = original_max

    def test_maybe_compact_preserves_seq_and_time(self, step_memory_tool: StepMemory):
        """_maybe_compact should preserve seq and time fields."""
        original_max = step_memory_tool._MAX_ENTRIES
        step_memory_tool._MAX_ENTRIES = 4
        try:
            steps = [
                {"seq": 1, "time": "T1", "brief": "b", "step": "s", "result": "r", "files": []},
                {"seq": 2, "time": "T2", "brief": "b", "step": "s", "result": "r", "files": []},
                {"seq": 3, "time": "T3", "brief": "b", "step": "s", "result": "r", "files": []},
                {"seq": 4, "time": "T4", "brief": "b", "step": "s", "result": "r", "files": []},
                {"seq": 5, "time": "T5", "brief": "b", "step": "s", "result": "r", "files": []},
            ]
            result = step_memory_tool._maybe_compact(steps)
            assert result[0]["seq"] == 1
            assert result[0]["time"] == "T1"
            assert result[4]["seq"] == 5
            assert result[4]["time"] == "T5"
        finally:
            step_memory_tool._MAX_ENTRIES = original_max


class TestStepMemoryLoadSteps:
    """Test _load_steps internal method."""

    async def test_load_steps_empty_file(self, step_memory_tool: StepMemory):
        """_load_steps returns empty list when file does not exist."""
        steps = step_memory_tool._load_steps()
        assert steps == []

    async def test_load_steps_valid_list(self, step_memory_tool: StepMemory):
        """_load_steps returns list when file contains valid JSON list."""
        path = step_memory_tool._storage_path()
        path.write_text(json.dumps([{"seq": 1, "step": "test"}]), encoding="utf-8")

        steps = step_memory_tool._load_steps()
        assert steps == [{"seq": 1, "step": "test"}]

    async def test_load_steps_not_a_list(self, step_memory_tool: StepMemory):
        """_load_steps returns empty list when JSON is not a list."""
        path = step_memory_tool._storage_path()
        path.write_text(json.dumps({"not": "a list"}), encoding="utf-8")

        steps = step_memory_tool._load_steps()
        assert steps == []

    async def test_load_steps_corrupted_json(self, step_memory_tool: StepMemory, monkeypatch):
        """_load_steps returns empty list and logs warning for corrupted JSON."""
        path = step_memory_tool._storage_path()
        path.write_text("not valid json {{{", encoding="utf-8")

        warnings: list[str] = []
        from kimi_cli.tools.step_mem import logger as step_logger

        original_warning = step_logger.warning

        def capture_warning(msg: str, **kwargs: Any):
            warnings.append(msg.format(**kwargs))
            original_warning(msg, **kwargs)

        monkeypatch.setattr(step_logger, "warning", capture_warning)

        steps = step_memory_tool._load_steps()
        assert steps == []
        assert any("Corrupted step memory file" in w for w in warnings)

    async def test_load_steps_unicode_decode_error(self, step_memory_tool: StepMemory, monkeypatch):
        """_load_steps handles UnicodeDecodeError gracefully."""
        path = step_memory_tool._storage_path()
        # Write invalid UTF-8 bytes
        path.write_bytes(b"\xff\xfe")

        warnings: list[str] = []
        from kimi_cli.tools.step_mem import logger as step_logger

        original_warning = step_logger.warning

        def capture_warning(msg: str, **kwargs: Any):
            warnings.append(msg.format(**kwargs))
            original_warning(msg, **kwargs)

        monkeypatch.setattr(step_logger, "warning", capture_warning)

        steps = step_memory_tool._load_steps()
        assert steps == []
        assert any("Corrupted step memory file" in w for w in warnings)

    async def test_load_steps_os_error(self, step_memory_tool: StepMemory, monkeypatch):
        """_load_steps handles OSError gracefully."""
        path = step_memory_tool._storage_path()
        path.write_text(json.dumps([{"seq": 1}]), encoding="utf-8")

        def raise_oserror(*args, **kwargs):
            raise OSError("permission denied")

        monkeypatch.setattr(Path, "read_text", raise_oserror)

        warnings: list[str] = []
        from kimi_cli.tools.step_mem import logger as step_logger

        original_warning = step_logger.warning

        def capture_warning(msg: str, **kwargs: Any):
            warnings.append(msg.format(**kwargs))
            original_warning(msg, **kwargs)

        monkeypatch.setattr(step_logger, "warning", capture_warning)

        steps = step_memory_tool._load_steps()
        assert steps == []
        assert any("Corrupted step memory file" in w for w in warnings)


class TestStepMemoryStoragePath:
    """Test _storage_path method."""

    async def test_storage_path_structure(self, step_memory_tool: StepMemory, runtime: Runtime):
        """_storage_path should follow .kimix_cache/steps/{session_id}.json."""
        path = step_memory_tool._storage_path()
        parts = path.parts
        assert ".kimix_cache" in parts
        assert "steps" in parts
        assert path.name == f"{runtime.session.id}.json"

    async def test_storage_path_creates_parent_dirs(self, step_memory_tool: StepMemory):
        """_storage_path should create parent directories."""
        path = step_memory_tool._storage_path()
        assert path.parent.exists()


class TestStepMemoryRouting:
    """Test __call__ action routing."""

    async def test_call_routes_to_save(self, step_memory_tool: StepMemory):
        """__call__ with action='save' routes to _save."""
        params = Params(action="save", step="Test")
        result = await step_memory_tool(params)
        assert not result.is_error
        assert "Step #1 saved" in result.output

    async def test_call_routes_to_load(self, step_memory_tool: StepMemory):
        """__call__ with action='load' routes to _load."""
        params = Params(action="load")
        result = await step_memory_tool(params)
        assert not result.is_error
        assert "No step history found" in result.output


class TestStepMemoryConcurrency:
    """Test thread safety."""

    async def test_concurrent_saves_do_not_corrupt(self, step_memory_tool: StepMemory):
        """Multiple concurrent saves should not lose data."""
        import asyncio

        async def save_step(i: int):
            return await step_memory_tool(Params(action="save", step=f"Concurrent step {i}"))

        results = await asyncio.gather(*[save_step(i) for i in range(20)])
        assert all(not r.is_error for r in results)

        steps = step_memory_tool._load_steps()
        assert len(steps) == 20
        # All seq values should be unique
        seqs = [s["seq"] for s in steps]
        assert len(set(seqs)) == 20
        assert sorted(seqs) == list(range(1, 21))

    def test_lock_is_threading_lock(self, step_memory_tool: StepMemory):
        """StepMemory should use threading.Lock for concurrency."""
        assert isinstance(step_memory_tool._lock, type(threading.Lock()))


class TestStepMemoryEdgeCases:
    """Test edge cases."""

    async def test_load_with_missing_fields(self, step_memory_tool: StepMemory):
        """Load should handle steps with missing fields gracefully."""
        path = step_memory_tool._storage_path()
        path.write_text(
            json.dumps([{"seq": 1}, {"seq": 2, "time": "T"}]),
            encoding="utf-8",
        )

        result = await step_memory_tool(Params(action="load"))
        assert not result.is_error
        assert "#1" in result.output
        assert "#2" in result.output
        assert "step:" in result.output
        assert "result:" in result.output

    async def test_load_with_non_string_files(self, step_memory_tool: StepMemory):
        """Load should handle non-list files gracefully."""
        path = step_memory_tool._storage_path()
        path.write_text(
            json.dumps([{"seq": 1, "files": None}]),
            encoding="utf-8",
        )

        result = await step_memory_tool(Params(action="load"))
        assert not result.is_error
        # files=None is falsy so files_str should be empty
        assert "files:" not in result.output

    async def test_save_after_compaction_continues_seq(self, step_memory_tool: StepMemory):
        """After compaction, seq should continue from highest existing."""
        original_max = step_memory_tool._MAX_ENTRIES
        step_memory_tool._MAX_ENTRIES = 4
        try:
            for i in range(5):
                await step_memory_tool(Params(action="save", step=f"Step {i}"))

            steps = step_memory_tool._load_steps()
            max_seq = max(s["seq"] for s in steps)
            assert max_seq == 5

            await step_memory_tool(Params(action="save", step="Next"))
            steps = step_memory_tool._load_steps()
            seqs = [s["seq"] for s in steps]
            assert 6 in seqs
        finally:
            step_memory_tool._MAX_ENTRIES = original_max

    async def test_time_is_iso_format(self, step_memory_tool: StepMemory):
        """Saved time should be ISO 8601 format."""
        await step_memory_tool(Params(action="save", step="Test"))
        steps = step_memory_tool._load_steps()
        time_str = steps[0]["time"]
        assert "T" in time_str
        assert time_str.endswith("+00:00")

    async def test_save_and_load_cycle(self, step_memory_tool: StepMemory):
        """Save multiple steps and load them back correctly."""
        await step_memory_tool(
            Params(action="save", step="Step 1", result="OK", files=["a.py"], brief="B1")
        )
        await step_memory_tool(
            Params(action="save", step="Step 2", result="FAIL", files=["b.py"], brief="B2")
        )

        result = await step_memory_tool(Params(action="load"))
        assert not result.is_error
        assert "B1" in result.output
        assert "B2" in result.output
        assert "Step 1" in result.output
        assert "Step 2" in result.output
        assert "OK" in result.output
        assert "FAIL" in result.output
        assert "a.py" in result.output
        assert "b.py" in result.output


class TestStepMemoryPlanRequirements:
    """Tests verifying all plan.md requirements are implemented."""

    async def test_storage_location_matches_plan(self, step_memory_tool: StepMemory, runtime: Runtime):
        """Storage path must be .kimix_cache/steps/{session_id}.json per plan.md."""
        path = step_memory_tool._storage_path()
        parts = Path(path).parts
        assert ".kimix_cache" in parts
        assert "steps" in parts
        assert path.name == f"{runtime.session.id}.json"

    async def test_structured_format_matches_plan(self, step_memory_tool: StepMemory):
        """Stored JSON must match the structured format in plan.md."""
        await step_memory_tool(
            Params(
                action="save",
                step="使用 SQLAlchemy 定义 User 模型，包含 id/name/email 字段",
                result="成功创建 models/user.py，语法检查通过",
                files=["models/user.py", "models/__init__.py"],
                brief="创建 User 模型",
            )
        )

        steps = step_memory_tool._load_steps()
        assert len(steps) == 1
        entry = steps[0]
        assert "seq" in entry and isinstance(entry["seq"], int)
        assert "time" in entry and isinstance(entry["time"], str)
        assert "brief" in entry and isinstance(entry["brief"], str)
        assert "step" in entry and isinstance(entry["step"], str)
        assert "result" in entry and isinstance(entry["result"], str)
        assert "files" in entry and isinstance(entry["files"], list)

    async def test_action_literal_save_load(self):
        """Params.action must only accept 'save' or 'load'."""
        from pydantic import ValidationError

        Params(action="save", step="x")
        Params(action="load")
        with pytest.raises(ValidationError):
            Params(action="invalid", step="x")

    async def test_both_actions_implemented(self, step_memory_tool: StepMemory):
        """Both save and load actions must be implemented and functional."""
        save_result = await step_memory_tool(Params(action="save", step="Test"))
        assert not save_result.is_error

        load_result = await step_memory_tool(Params(action="load"))
        assert not load_result.is_error
        assert "Test" in load_result.output
