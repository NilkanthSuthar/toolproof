"""Turn a test's `expect:` block into pass/fail messages."""

from __future__ import annotations

import json
import re
from typing import Any

from jsonpath_ng.ext import parse as parse_jsonpath  # type: ignore[attr-defined]
from jsonschema import Draft202012Validator

from toolproof.client import CallResult
from toolproof.config import Expect, JsonPathCheck

# JSON Schema type names mapped to the Python types json.loads produces.
_JSON_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "number": (int, float),
    "integer": (int,),
    "boolean": (bool,),
    "array": (list,),
    "object": (dict,),
    "null": (type(None),),
}


def check_expectations(
    result: CallResult,
    expect: Expect,
    output_schema: dict[str, Any] | None = None,
) -> list[str]:
    """Return a list of failure messages. An empty list means the test passed."""
    if result.transport_error:
        # Nothing else is meaningful if we never got a result back.
        return [f"no result from server: {result.transport_error}"]

    failures: list[str] = []

    if expect.is_error is not None and result.is_error != expect.is_error:
        if result.is_error:
            failures.append(f"expected success but tool returned an error: {_short(result.text)}")
        else:
            failures.append("expected an error but the tool succeeded")

    if expect.has_equals:
        actual = result.data if result.data is not None else result.text
        if actual != expect.equals:
            failures.append(f"expected result {expect.equals!r}, got {_short(actual)!r}")

    if expect.contains is not None:
        needles = [expect.contains] if isinstance(expect.contains, str) else expect.contains
        for needle in needles:
            if needle not in result.text:
                failures.append(f"result does not contain {needle!r}: {_short(result.text)}")

    if expect.regex is not None and not re.search(expect.regex, result.text):
        failures.append(f"result does not match /{expect.regex}/: {_short(result.text)}")

    for path, check in expect.jsonpath.items():
        failures.extend(_check_jsonpath(result.data, path, check))

    if expect.max_latency_ms is not None and result.latency_ms > expect.max_latency_ms:
        failures.append(f"took {result.latency_ms:.0f}ms, limit is {expect.max_latency_ms:.0f}ms")

    if expect.output_schema and output_schema is not None and not result.is_error:
        failures.extend(_check_output_schema(result, output_schema))

    return failures


def _check_jsonpath(data: Any, path: str, check: JsonPathCheck) -> list[str]:
    if data is None:
        return [f"{path}: result is not JSON, can't apply jsonpath"]
    try:
        expr = parse_jsonpath(path)  # type: ignore[no-untyped-call]
    except Exception as exc:  # jsonpath_ng raises several exception types
        return [f"{path}: invalid jsonpath ({exc})"]

    matches = [m.value for m in expr.find(data)]
    if not matches:
        return [f"{path}: no match in result"] if check.exists else []
    if not check.exists:
        return [f"{path}: expected no match, found {_short(matches[0])!r}"]

    # A path like $.days[*].temp_c can match several values; check them as a list.
    value: Any = matches[0] if len(matches) == 1 else matches
    failures = []

    if check.type is not None and not _is_json_type(value, check.type):
        failures.append(f"{path}: expected type {check.type}, got {_json_type_name(value)}")

    if "equals" in check.model_fields_set and value != check.equals:
        failures.append(f"{path}: expected {check.equals!r}, got {_short(value)!r}")

    if check.min is not None or check.max is not None:
        if not _is_json_type(value, "number"):
            failures.append(f"{path}: range check needs a number, got {_json_type_name(value)}")
        else:
            if check.min is not None and value < check.min:
                failures.append(f"{path}: {value} is below min {check.min}")
            if check.max is not None and value > check.max:
                failures.append(f"{path}: {value} is above max {check.max}")

    return failures


def _check_output_schema(result: CallResult, schema: dict[str, Any]) -> list[str]:
    if result.structured is None:
        return ["tool declares an outputSchema but returned no structured content"]
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(result.structured), key=lambda e: list(e.path))
    return [f"output schema: {_error_location(e.path)}{e.message}" for e in errors]


def _error_location(path: Any) -> str:
    parts = list(path)
    return ("$." + ".".join(str(p) for p in parts) + ": ") if parts else ""


def _is_json_type(value: Any, name: str) -> bool:
    # bool is a subclass of int in Python, but not a number in JSON.
    if isinstance(value, bool) and name in ("number", "integer"):
        return False
    if name == "integer" and isinstance(value, float):
        return value.is_integer()
    return isinstance(value, _JSON_TYPES[name])


def _json_type_name(value: Any) -> str:
    for name in ("null", "boolean", "integer", "number", "string", "array", "object"):
        if _is_json_type(value, name):
            return name
    return type(value).__name__


def _short(value: Any, limit: int = 200) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if len(text) <= limit else text[:limit] + "..."
