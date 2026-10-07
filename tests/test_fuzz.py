import json

import mcp_types as types
import pytest
from hypothesis import given, settings
from jsonschema import Draft202012Validator

from tests.conftest import BUGGY, WEATHER
from toolproof.client import CallResult
from toolproof.config import FuzzConfig
from toolproof.fuzz import classify, invalid_inputs, should_fuzz, valid_inputs
from toolproof.runner import run_config

SCHEMA = {
    "type": "object",
    "properties": {"city": {"type": "string"}, "days": {"type": "integer", "minimum": 1}},
    "required": ["city"],
}


# ---------- input generation ----------


@settings(max_examples=100, database=None)
@given(valid_inputs(SCHEMA))
def test_valid_inputs_match_the_schema(value):
    assert Draft202012Validator(SCHEMA).is_valid(value)


@settings(max_examples=100, database=None)
@given(invalid_inputs(SCHEMA))
def test_invalid_inputs_break_the_schema(value):
    assert not Draft202012Validator(SCHEMA).is_valid(value)


def test_no_invalid_inputs_for_a_schema_that_accepts_anything():
    assert invalid_inputs({"type": "object"}) is None


# ---------- judging results ----------


def result(**kwargs):
    defaults = dict(
        tool="t", arguments={}, is_error=False, text="ok", structured=None, latency_ms=1
    )
    return CallResult(**{**defaults, **kwargs})


CONFIG = FuzzConfig()


@pytest.mark.parametrize(
    ("call", "mode", "expected"),
    [
        (result(), "valid", None),
        (result(is_error=True, text="unknown city"), "valid", None),
        (result(is_error=True, text="bad input"), "invalid", None),
        (result(timed_out=True, transport_error="timed out", is_error=True), "valid", "hang"),
        (result(transport_error="connection lost", is_error=True), "valid", "crash"),
        (result(protocol_error=True, error_code=-32603, is_error=True), "valid", "internal-error"),
        (result(protocol_error=True, error_code=-32602, is_error=True), "invalid", None),
        (result(protocol_error=True, error_code=-32602, is_error=True), "valid", "rejected-valid"),
        (result(is_error=True, text="Error executing tool t"), "valid", "unhandled-exception"),
        (
            result(is_error=True, text="Traceback (most recent call last):\n  ..."),
            "invalid",
            "unhandled-exception",
        ),
        (result(), "invalid", "accepted-invalid"),
    ],
)
def test_classify(call, mode, expected):
    problem = classify(call, mode, CONFIG)
    assert (problem[0] if problem else None) == expected


def test_classify_options():
    error = result(is_error=True, text="unknown city")
    assert classify(error, "valid", FuzzConfig(valid_must_succeed=True))[0] == "unexpected-error"
    assert classify(result(), "invalid", FuzzConfig(invalid_must_fail=False)) is None


def test_classify_checks_output_schema():
    schema = {"type": "object", "properties": {"t": {"type": "number"}}}
    assert classify(result(structured={"t": "1"}), "valid", CONFIG, schema)[0] == "output-schema"
    assert classify(result(structured={"t": 1}), "valid", CONFIG, schema) is None


def test_destructive_tools_are_skipped_unless_asked():
    tool = types.Tool(
        name="delete_everything",
        description="x",
        input_schema={"type": "object"},
        annotations=types.ToolAnnotations(destructive_hint=True),
    )
    assert "destructive" in should_fuzz(tool, FuzzConfig())
    assert should_fuzz(tool, FuzzConfig(include_destructive=True)) is None
    assert should_fuzz(tool, FuzzConfig(skip=["delete_everything"])) == "in fuzz.skip"


# ---------- against real servers ----------


def fuzz(write_config, script, **options):
    config = write_config(script, [], fuzz={"max_examples": 25, "seed": 1, **options})
    return run_config(config, ["fuzz"])


def test_weather_server_survives_fuzzing(write_config):
    report = fuzz(write_config, WEATHER)
    assert report.error is None
    assert {f.tool for f in report.fuzz} == {"get_weather", "get_forecast", "list_cities"}
    assert all(f.calls > 0 for f in report.fuzz)
    assert [f.findings for f in report.fuzz] == [[], [], []]
    assert report.passed


def test_fuzz_finds_every_planted_bug(write_config):
    report = fuzz(write_config, BUGGY, timeout_ms=1000, max_time_s=20)
    found = {f.tool: {(x.kind, x.mode): x for x in f.findings} for f in report.fuzz}

    # Bug 1: crash on an empty city, shrunk to the smallest input.
    crash = found["get_weather"][("crash", "valid")]
    assert crash.input == {"city": ""}
    # get_weather also accepts a non-string city without complaint.
    assert ("accepted-invalid", "invalid") in found["get_weather"]

    # Bug 2: broken input schema.
    assert ("bad-schema", "valid") in found["search_cities"]

    # Bug 3: slow tool.
    assert ("hang", "valid") in found["slow_report"]

    # Bug 4: output doesn't match the declared outputSchema.
    assert "not of type 'number'" in found["get_temperature"][("output-schema", "valid")].detail

    # Bug 5: valid input (per the schema) makes the handler raise.
    assert ("internal-error", "valid") in found["lookup"]

    assert not report.passed
    assert report.fuzz_seed == 1
    json.dumps([f.input for t in found.values() for f in t.values()])  # inputs are plain JSON


def test_only_selected_tools(write_config):
    report = fuzz(write_config, WEATHER, tools=["list_cities"])
    assert [f.tool for f in report.fuzz] == ["list_cities"]
