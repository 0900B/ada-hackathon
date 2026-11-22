"""The field-message schema must stay within the Anthropic structured-output limits.

Regression: the severity fields pushed PARSE_SCHEMA to 20 union-typed (nullable/anyOf) parameters and
the API rejected every field message with 400 "too many parameters with union types (limit: 16)".
The fake-client tests could not see it, so count them here. Run: python tests/test_parse_schema.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.messages import MAX_UNION_PARAMS, PARSE_SCHEMA  # noqa: E402


def union_params(node, inside_events_anyof=False) -> int:
    """Parameters whose schema is a union: an anyOf or a list of types (the events' anyOf itself counts once)."""
    n = 0
    if isinstance(node, dict):
        if "anyOf" in node or isinstance(node.get("type"), list):
            n += 1
        for v in node.values():
            n += union_params(v)
    elif isinstance(node, list):
        for v in node:
            n += union_params(v)
    return n


def test_parse_schema_within_union_limit():
    n = union_params(PARSE_SCHEMA)
    assert n <= MAX_UNION_PARAMS, f"{n} union-typed parameters (limit {MAX_UNION_PARAMS})"
    print(f"union-typed parameters: {n} (limit {MAX_UNION_PARAMS})")


def test_objects_are_strict():
    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node.get("additionalProperties") is False, node
                assert set(node.get("properties", {})) == set(node.get("required", [])), node
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(PARSE_SCHEMA)
    from app.agent.triage import TRIAGE_SCHEMA

    walk(TRIAGE_SCHEMA)


def test_triage_schema_within_union_limit():
    """The 112-call triage schema (app/agent/triage.py): plain strings and required booleans only."""
    from app.agent.triage import TRIAGE_SCHEMA

    n = union_params(TRIAGE_SCHEMA)
    assert n <= MAX_UNION_PARAMS, f"{n} union-typed parameters (limit {MAX_UNION_PARAMS})"
    print(f"triage schema union-typed parameters: {n} (limit {MAX_UNION_PARAMS})")


if __name__ == "__main__":
    test_parse_schema_within_union_limit()
    test_objects_are_strict()
    test_triage_schema_within_union_limit()
    print("3/3 passed")
