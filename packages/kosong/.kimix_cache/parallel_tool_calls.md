# Parallel Tool Calls Implementation

## Files Modified
- `src/kosong/contrib/chat_provider/anthropic.py`
- `src/kosong/contrib/chat_provider/openai_legacy.py`
- `src/kosong/contrib/chat_provider/openai_responses.py`
- `tests/api_snapshot_tests/test_anthropic.py`
- `tests/api_snapshot_tests/test_openai_legacy.py`
- `tests/api_snapshot_tests/test_openai_responses.py`

## Implementation

### Anthropic
- Added `with_parallel_tool_calls(enabled: bool = True) -> Self`
- When `enabled=False`: sets `tool_choice={"type": "auto", "disable_parallel_tool_use": True}`
- When `enabled=True`: removes any `tool_choice` from generation kwargs

### OpenAI Legacy (Chat Completions)
- Added `with_parallel_tool_calls(enabled: bool = True) -> Self`
- When `enabled=False`: sets `parallel_tool_calls=False`
- When `enabled=True`: removes `parallel_tool_calls` from generation kwargs

### OpenAI Responses
- Added `with_parallel_tool_calls(enabled: bool = True) -> Self`
- When `enabled=False`: sets `max_tool_calls=1` (the Responses API has no explicit `parallel_tool_calls` flag)
- When `enabled=True`: removes `max_tool_calls` from generation kwargs

## Test Results
All new tests pass:
- `test_anthropic_with_parallel_tool_calls_disabled`
- `test_anthropic_with_parallel_tool_calls_enabled`
- `test_anthropic_parallel_tool_calls_last_call_wins`
- `test_openai_legacy_with_parallel_tool_calls_disabled`
- `test_openai_legacy_with_parallel_tool_calls_enabled`
- `test_openai_responses_with_parallel_tool_calls_disabled`
- `test_openai_responses_with_parallel_tool_calls_enabled`

Some pre-existing tests fail due to unrelated `loads_relaxed` behavior changes (parsing previously-invalid JSON).
