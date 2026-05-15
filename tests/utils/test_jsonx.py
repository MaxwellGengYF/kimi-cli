"""Tests for kosong.utils.jsonx.loads_relaxed."""

from __future__ import annotations

import json

import dirtyjson
import orjson
import pytest

from kosong.utils.jsonx import loads_relaxed


class TestLoadsRelaxed:
    def test_valid_strict_json(self):
        """Standard JSON should parse via the orjson fast path."""
        data = '{"name": "Alice", "age": 30, "active": true}'
        result = loads_relaxed(data)
        assert result == {"name": "Alice", "age": 30, "active": True}

    def test_valid_json_bytes(self):
        """Bytes input should work the same as str input."""
        data = b'{"name": "Alice", "age": 30}'
        result = loads_relaxed(data)
        assert result == {"name": "Alice", "age": 30}

    def test_valid_json_bytearray(self):
        """Bytearray input should work the same as str input."""
        data = bytearray(b'{"name": "Alice", "age": 30}')
        result = loads_relaxed(data)
        assert result == {"name": "Alice", "age": 30}

    def test_nested_structures(self):
        """Deeply nested objects and arrays should parse correctly."""
        data = '{"a": {"b": {"c": [1, 2, {"d": "e"}]}}}'
        result = loads_relaxed(data)
        assert result == {"a": {"b": {"c": [1, 2, {"d": "e"}]}}}

    def test_unescaped_control_characters(self):
        """JSON with unescaped control chars falls back to json strict=False."""
        # Newline inside a string without being escaped
        data = '{"message": "Hello\nWorld"}'
        # orjson rejects raw newlines in strings by default
        with pytest.raises(orjson.JSONDecodeError):
            orjson.loads(data)
        # stdlib json with strict=False accepts it
        result = loads_relaxed(data)
        assert result == {"message": "Hello\nWorld"}

    def test_trailing_commas(self):
        """JSON with trailing commas falls back to dirtyjson."""
        data = '{"a": 1, "b": 2,}'
        # orjson rejects trailing commas
        with pytest.raises(orjson.JSONDecodeError):
            orjson.loads(data)
        # stdlib json also rejects trailing commas
        with pytest.raises(json.JSONDecodeError):
            json.loads(data, strict=False)
        result = loads_relaxed(data)
        assert result == {"a": 1, "b": 2}

    def test_single_quoted_strings(self):
        """JSON with single-quoted strings falls back to dirtyjson."""
        data = "{'name': 'Alice', 'age': 30}"
        with pytest.raises(orjson.JSONDecodeError):
            orjson.loads(data)
        with pytest.raises(json.JSONDecodeError):
            json.loads(data, strict=False)
        result = loads_relaxed(data)
        assert result == {"name": "Alice", "age": 30}

    def test_unquoted_keys(self):
        """JSON with unquoted object keys falls back to dirtyjson."""
        data = '{name: "Alice", age: 30}'
        with pytest.raises(orjson.JSONDecodeError):
            orjson.loads(data)
        with pytest.raises(json.JSONDecodeError):
            json.loads(data, strict=False)
        result = loads_relaxed(data)
        assert result == {"name": "Alice", "age": 30}

    def test_comments(self):
        """JSON with comments falls back to dirtyjson."""
        data = '\n'.join([
            '{',
            '  // this is a comment',
            '  "a": 1,',
            '  /* block comment */',
            '  "b": 2',
            '}',
        ])
        with pytest.raises(orjson.JSONDecodeError):
            orjson.loads(data)
        with pytest.raises(json.JSONDecodeError):
            json.loads(data, strict=False)
        result = loads_relaxed(data)
        assert result == {"a": 1, "b": 2}

    def test_combined_relaxed_features(self):
        """Multiple relaxations at once: single quotes, trailing comma, comments."""
        data = '\n'.join([
            '{',
            "  'items': [1, 2, 3,],  // trailing comma in array",
            "  'meta': {enabled: true},  /* unquoted key */",
            '}',
        ])
        result = loads_relaxed(data)
        assert result == {
            "items": [1, 2, 3],
            "meta": {"enabled": True},
        }

    def test_empty_object_and_array(self):
        """Edge case: empty structures."""
        assert loads_relaxed('{}') == {}
        assert loads_relaxed('[]') == []

    def test_primitives(self):
        """Edge case: primitive values."""
        assert loads_relaxed('42') == 42
        assert loads_relaxed('"hello"') == "hello"
        assert loads_relaxed('true') is True
        assert loads_relaxed('false') is False
        assert loads_relaxed('null') is None

    def test_unicode_content(self):
        """Unicode characters should survive all parsing paths."""
        data = '{"emoji": "🚀", "cjk": "你好世界"}'
        result = loads_relaxed(data)
        assert result == {"emoji": "🚀", "cjk": "你好世界"}

    def test_invalid_json_raises(self):
        """Truly invalid input should raise json.JSONDecodeError."""
        data = '{this is not json at all'
        with pytest.raises(json.JSONDecodeError):
            loads_relaxed(data)

    def test_orjson_rejection_json_accepts(self):
        """Ensure the json strict=False fallback is actually exercised."""
        # Tab character inside string – orjson rejects, json strict=False accepts
        data = '{"text": "a\tb"}'
        with pytest.raises(orjson.JSONDecodeError):
            orjson.loads(data)
        result = loads_relaxed(data)
        assert result == {"text": "a\tb"}

    def test_relaxed_json_bytes(self):
        """Bytes input with relaxed JSON (trailing comma) falls back to dirtyjson."""
        data = b'{"a": 1, "b": 2,}'
        result = loads_relaxed(data)
        assert result == {"a": 1, "b": 2}
