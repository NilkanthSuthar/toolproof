"""Static checks on a server's tool list.

These run before any tool is called. They catch problems that make a tool
hard for a client to use: missing descriptions, broken input schemas,
duplicate names, and so on.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Literal

import mcp_types as types
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from toolproof.config import ChecksConfig

Severity = Literal["error", "warning"]


@dataclass
class CheckResult:
    """One problem found by a static check."""

    check: str
    tool: str
    severity: Severity
    message: str


def run_checks(tools: list[types.Tool], config: ChecksConfig | None = None) -> list[CheckResult]:
    """Run every static check and return the problems found (empty list means all good)."""
    config = config or ChecksConfig()
    problems: list[CheckResult] = []

    counts = Counter(tool.name for tool in tools)
    for name, count in counts.items():
        if count > 1:
            problems.append(
                CheckResult("duplicate-name", name, "error", f"tool name is used {count} times")
            )

    for tool in tools:
        problems.extend(_check_tool(tool, config))
    return problems


def _check_tool(tool: types.Tool, config: ChecksConfig) -> list[CheckResult]:
    name = tool.name or "<unnamed>"
    problems: list[CheckResult] = []

    def add(check: str, severity: Severity, message: str) -> None:
        problems.append(CheckResult(check, name, severity, message))

    if not tool.name or not tool.name.strip():
        add("name", "error", "tool has no name")

    description = (tool.description or "").strip()
    if not description:
        add("description", "error", "tool has no description")
    elif len(description) > config.max_description_length:
        add(
            "description-length",
            "warning",
            f"description is {len(description)} characters (limit {config.max_description_length})",
        )

    schema = tool.input_schema
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        add("input-schema", "error", f"input schema is not valid JSON Schema: {exc.message}")
        return problems

    if schema.get("type") != "object":
        add("input-schema", "error", "input schema must have type 'object' at the root")
        return problems

    properties = schema.get("properties") or {}
    required = schema.get("required") or []
    missing = [field for field in required if field not in properties]
    if missing:
        add(
            "required-fields",
            "error",
            f"required fields not listed in properties: {', '.join(missing)}",
        )
    if properties and not required:
        add(
            "required-fields",
            "warning",
            "input schema has properties but none are marked required",
        )

    if tool.output_schema is not None:
        try:
            Draft202012Validator.check_schema(tool.output_schema)
        except SchemaError as exc:
            add("output-schema", "error", f"output schema is not valid JSON Schema: {exc.message}")

    return problems


def has_failures(problems: list[CheckResult], strict: bool = False) -> bool:
    """True if any problem should fail the run. Warnings only count in strict mode."""
    return any(p.severity == "error" or strict for p in problems)
