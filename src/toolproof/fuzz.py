"""Fuzz tools with inputs generated from their JSON Schemas.

For each tool we run two batches through Hypothesis:

- valid inputs: generated from the input schema, plus edge-case strings
  (empty, huge, unicode, control characters) that still match the schema
- invalid inputs: a valid input broken on purpose (missing required field,
  wrong type, null) and confirmed invalid against the schema

A finding is anything a well-behaved server shouldn't do: crash, hang, return
an internal error or a traceback, break its own outputSchema, accept invalid
input, or (optionally) reject valid input. Hypothesis shrinks each failure,
and we keep the smallest input that triggered each kind of finding.
"""

from __future__ import annotations

import json
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any, Literal, cast

import anyio
import anyio.from_thread
import anyio.to_thread
import mcp_types as types
from hypothesis import HealthCheck, Phase, Verbosity, assume, given, settings
from hypothesis import seed as hypothesis_seed
from hypothesis import strategies as st
from hypothesis.errors import HypothesisException
from hypothesis_jsonschema import from_schema
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from mcp_types.jsonrpc import INVALID_PARAMS

from toolproof.assertions import check_expectations
from toolproof.client import CallResult, McpServer
from toolproof.config import Expect, FuzzConfig

Mode = Literal["valid", "invalid"]

# Strings that often break code that only ever saw "normal" input.
# Ordered simplest first, because Hypothesis shrinks toward the start of the list.
EDGE_STRINGS = [
    "",
    " ",
    "0",
    "null",
    "\n\r\t",
    "\x00",
    "😀" * 50,
    "שלום עולם",
    "'; DROP TABLE users; --",
    "../../../../etc/passwd",
    "A" * 100_000,
]

# One value of each JSON type, used to put the wrong type into a field.
ANY_JSON_TYPE: list[Any] = [None, True, 0, 1.5, "x", [], {}]

# How the Python MCP SDK reports an exception the tool didn't handle.
UNHANDLED_SDK_ERROR = re.compile(r"^Error executing tool \S+$")


@dataclass
class FuzzFinding:
    """One kind of bad behaviour, with the smallest input that showed it."""

    kind: str
    mode: Mode
    input: dict[str, Any]
    detail: str

    @property
    def size(self) -> int:
        return len(json.dumps(self.input, default=str))


@dataclass
class FuzzResult:
    """Everything found while fuzzing one tool."""

    tool: str
    calls: int = 0
    findings: list[FuzzFinding] = field(default_factory=list)
    skipped: str | None = None
    duration_s: float = 0.0

    @property
    def passed(self) -> bool:
        return not self.findings


class _FuzzFailure(Exception):
    """Raised inside the Hypothesis test so it shrinks the input."""


# Hypothesis tracks failures by exception type, so a separate subclass per kind
# lets it shrink a crash and an output-schema bug independently.
_FAILURE_TYPES: dict[str, type[_FuzzFailure]] = {}


def _failure_type(kind: str) -> type[_FuzzFailure]:
    if kind not in _FAILURE_TYPES:
        name = "Fuzz_" + kind.replace("-", "_")
        _FAILURE_TYPES[kind] = type(name, (_FuzzFailure,), {})
    return _FAILURE_TYPES[kind]


# ---------- input strategies ----------


def _validator(schema: dict[str, Any]) -> Draft202012Validator:
    return Draft202012Validator(schema)


def _object_inputs(schema: dict[str, Any]) -> st.SearchStrategy[dict[str, Any]]:
    # Don't invent extra keys unless the schema asks for them. They are allowed
    # by default in JSON Schema, but they make failing inputs noisy and rarely
    # find anything.
    properties = schema.get("properties") or {}
    required = schema.get("required") or []
    if "additionalProperties" not in schema and all(r in properties for r in required):
        schema = {**schema, "additionalProperties": False}
    # Tool input schemas are always `type: object`, so every value is a dict.
    return cast("st.SearchStrategy[dict[str, Any]]", from_schema(schema))


def valid_inputs(schema: dict[str, Any]) -> st.SearchStrategy[dict[str, Any]]:
    """Inputs that match the schema, mixed with edge-case strings where allowed."""
    base = _object_inputs(schema)
    string_fields = [
        name
        for name, prop in (schema.get("properties") or {}).items()
        if isinstance(prop, dict) and prop.get("type") == "string"
    ]
    if not string_fields:
        return base
    validator = _validator(schema)

    @st.composite
    def with_edge_string(draw: st.DrawFn) -> dict[str, Any]:
        value = dict(draw(base))
        value[draw(st.sampled_from(string_fields))] = draw(st.sampled_from(EDGE_STRINGS))
        assume(validator.is_valid(value))
        return value

    return st.one_of(base, with_edge_string())


def invalid_inputs(schema: dict[str, Any]) -> st.SearchStrategy[dict[str, Any]] | None:
    """Inputs that break the schema in one way. None if the schema accepts anything."""
    properties = schema.get("properties") or {}
    required = [name for name in schema.get("required") or [] if isinstance(name, str)]
    typed = [name for name, prop in properties.items() if isinstance(prop, dict) and "type" in prop]
    if not required and not typed:
        return None
    base = _object_inputs(schema)
    validator = _validator(schema)

    @st.composite
    def broken(draw: st.DrawFn) -> dict[str, Any]:
        value = dict(draw(base))
        ways = (["missing"] if required else []) + (["wrong-type", "null"] if typed else [])
        way = draw(st.sampled_from(ways))
        if way == "missing":
            value.pop(draw(st.sampled_from(required)), None)
        elif way == "null":
            value[draw(st.sampled_from(typed))] = None
        else:
            value[draw(st.sampled_from(typed))] = draw(st.sampled_from(ANY_JSON_TYPE))
        assume(not validator.is_valid(value))
        return value

    return broken()


# ---------- judging a single call ----------


def classify(
    result: CallResult,
    mode: Mode,
    config: FuzzConfig,
    output_schema: dict[str, Any] | None = None,
) -> tuple[str, str] | None:
    """Return (kind, detail) if the result is a problem, else None."""
    if result.timed_out:
        return "hang", result.transport_error or "timed out"
    if result.transport_error:
        return "crash", result.transport_error
    if result.protocol_error:
        if result.error_code == INVALID_PARAMS:
            if mode == "invalid":
                return None  # a proper "invalid params" error
            return "rejected-valid", f"valid input rejected: {result.text}"
        return "internal-error", f"JSON-RPC error {result.error_code}: {result.text}"
    if result.is_error and (
        "Traceback (most recent call last)" in result.text
        or UNHANDLED_SDK_ERROR.match(result.text.strip())
    ):
        return "unhandled-exception", result.text[:300]

    if mode == "invalid":
        if not result.is_error and config.invalid_must_fail:
            return "accepted-invalid", "invalid input returned a success result"
        return None

    if result.is_error:
        if config.valid_must_succeed:
            return "unexpected-error", result.text[:300]
        return None
    failures = check_expectations(result, Expect(), output_schema)
    if failures:
        return "output-schema", failures[0]
    return None


# ---------- running ----------


def should_fuzz(tool: types.Tool, config: FuzzConfig) -> str | None:
    """Return a reason to skip the tool, or None to fuzz it."""
    if config.tools and tool.name not in config.tools:
        return "not in fuzz.tools"
    if tool.name in config.skip:
        return "in fuzz.skip"
    hints = tool.annotations
    if (
        hints is not None
        and hints.destructive_hint is True
        and not hints.read_only_hint
        and not config.include_destructive
    ):
        return "marked destructive (set include_destructive to fuzz it)"
    return None


async def fuzz_tool(
    server: McpServer, tool: types.Tool, config: FuzzConfig, seed: int
) -> FuzzResult:
    """Fuzz one tool with valid and invalid inputs."""
    result = FuzzResult(tool=tool.name)
    started = time.perf_counter()

    try:
        Draft202012Validator.check_schema(tool.input_schema)
    except SchemaError as exc:
        result.findings.append(
            FuzzFinding("bad-schema", "valid", {}, f"can't generate inputs: {exc.message}")
        )
        return result

    batches: list[tuple[Mode, st.SearchStrategy[dict[str, Any]]]] = [
        ("valid", valid_inputs(tool.input_schema))
    ]
    invalid = invalid_inputs(tool.input_schema)
    if invalid is not None:
        batches.append(("invalid", invalid))

    runner = _ToolFuzzer(server, tool, config, result, started)
    for mode, strategy in batches:
        error = await anyio.to_thread.run_sync(runner.run_batch, mode, strategy, seed)
        if error and result.calls == 0:
            result.skipped = f"could not generate inputs: {error}"

    result.findings.sort(key=lambda f: (f.mode != "valid", f.kind))
    result.duration_s = time.perf_counter() - started
    return result


class _ToolFuzzer:
    """Runs Hypothesis batches for one tool. Lives in a worker thread."""

    def __init__(
        self,
        server: McpServer,
        tool: types.Tool,
        config: FuzzConfig,
        result: FuzzResult,
        started: float,
    ) -> None:
        self.server = server
        self.tool = tool
        self.config = config
        self.result = result
        self.started = started
        self.hung = False

    def out_of_time(self) -> bool:
        return time.perf_counter() - self.started > self.config.max_time_s

    def record(self, kind: str, mode: Mode, args: dict[str, Any], detail: str) -> None:
        """Keep the smallest input seen for each (kind, mode)."""
        finding = FuzzFinding(kind, mode, args, detail)
        for i, old in enumerate(self.result.findings):
            if old.kind == kind and old.mode == mode:
                if finding.size < old.size:
                    self.result.findings[i] = finding
                return
        self.result.findings.append(finding)

    def call_once(self, mode: Mode, args: dict[str, Any]) -> None:
        # Once a tool has hung or used up its time, stop calling it. Hypothesis
        # will then fail to reproduce the failure, which we ignore below.
        if self.hung or self.out_of_time():
            return
        self.result.calls += 1
        timeout_s = self.config.timeout_ms / 1000
        call = anyio.from_thread.run(self.server.call, self.tool.name, args, timeout_s)
        problem = classify(call, mode, self.config, self.tool.output_schema)

        if call.timed_out:
            self.hung = True
        if call.transport_error and not anyio.from_thread.run(self.server.is_alive):
            # Restart the server so fuzzing (and anything after it) can continue.
            anyio.from_thread.run(self.server.reconnect)

        if problem:
            kind, detail = problem
            self.record(kind, mode, args, detail)
            raise _failure_type(kind)(detail)

    def run_batch(
        self, mode: Mode, strategy: st.SearchStrategy[dict[str, Any]], seed: int
    ) -> str | None:
        """Run one Hypothesis batch. Returns an error message if inputs couldn't be generated."""

        @hypothesis_seed(seed)
        @settings(
            max_examples=self.config.max_examples,
            deadline=None,
            database=None,
            derandomize=False,
            print_blob=False,
            verbosity=Verbosity.quiet,
            suppress_health_check=list(HealthCheck),
            phases=[Phase.generate, Phase.shrink],
        )
        @given(strategy)
        def check(args: dict[str, Any]) -> None:
            self.call_once(mode, args)

        try:
            check()
        except _FuzzFailure:
            pass
        except BaseExceptionGroup as group:
            # Several kinds of failure at once; we already recorded them all.
            _, rest = group.split((_FuzzFailure, HypothesisException))
            if rest is not None:
                raise rest from None
        except HypothesisException as exc:
            # Usually "flaky": we stopped calling a hung tool, so Hypothesis
            # couldn't replay the failure. Our own records are still correct.
            if self.result.calls == 0:
                message = str(exc).split(". ")[0].strip() or exc.__class__.__name__
                return message
        return None


async def run_fuzz(
    server: McpServer, tools: list[types.Tool], config: FuzzConfig
) -> tuple[list[FuzzResult], int]:
    """Fuzz every selected tool. Returns the results and the seed used."""
    seed = config.seed if config.seed is not None else random.randrange(1_000_000)
    results = []
    for tool in tools:
        reason = should_fuzz(tool, config)
        if reason == "not in fuzz.tools":
            continue
        if reason:
            results.append(FuzzResult(tool=tool.name, skipped=reason))
            continue
        results.append(await fuzz_tool(server, tool, config, seed))
    return results, seed
