import json

from toolproof.assertions import check_expectations
from toolproof.client import CallResult
from toolproof.config import Expect


def result(text="", structured=None, is_error=False, latency_ms=5.0, **kwargs):
    return CallResult(
        tool="t",
        arguments={},
        is_error=is_error,
        text=text,
        structured=structured,
        latency_ms=latency_ms,
        **kwargs,
    )


def check(r, **expect):
    return check_expectations(r, Expect.model_validate(expect))


WEATHER = {"city": "Toronto", "temp_c": 12.5, "days": [{"t": 1}, {"t": 2}]}


def test_empty_expect_passes():
    assert check(result("hello")) == []


def test_is_error():
    assert check(result(is_error=True), is_error=True) == []
    assert check(result(is_error=False), is_error=False) == []
    assert "expected an error" in check(result(), is_error=True)[0]
    assert "returned an error" in check(result("boom", is_error=True), is_error=False)[0]


def test_contains_one_or_many():
    r = result("Toronto is cloudy")
    assert check(r, contains="Toronto") == []
    assert check(r, contains=["Toronto", "cloudy"]) == []
    assert len(check(r, contains=["Toronto", "sunny"])) == 1


def test_regex():
    assert check(result("temp 12C"), regex=r"\d+C") == []
    assert check(result("temp"), regex=r"\d+C")


def test_equals_uses_json_when_available():
    assert check(result(json.dumps({"a": 1})), equals={"a": 1}) == []
    assert check(result("plain"), equals="plain") == []
    assert check(result("plain"), equals="other")


def test_jsonpath_type_equals_and_range():
    r = result(structured=WEATHER)
    assert check(r, jsonpath={"$.temp_c": {"type": "number", "min": 0, "max": 40}}) == []
    assert check(r, jsonpath={"$.city": {"equals": "Toronto"}}) == []
    assert check(r, jsonpath={"$.days": {"type": "array"}}) == []
    assert check(r, jsonpath={"$.days[1].t": {"equals": 2}}) == []

    assert "expected type string" in check(r, jsonpath={"$.temp_c": {"type": "string"}})[0]
    assert "above max" in check(r, jsonpath={"$.temp_c": {"max": 10}})[0]
    assert "below min" in check(r, jsonpath={"$.temp_c": {"min": 20}})[0]


def test_jsonpath_reads_json_text():
    r = result(text=json.dumps(WEATHER))
    assert check(r, jsonpath={"$.temp_c": {"type": "number"}}) == []


def test_jsonpath_missing_and_exists_false():
    r = result(structured=WEATHER)
    assert "no match" in check(r, jsonpath={"$.wind": {}})[0]
    assert check(r, jsonpath={"$.wind": {"exists": False}}) == []


def test_jsonpath_on_non_json():
    assert "not JSON" in check(result("plain"), jsonpath={"$.a": {}})[0]


def test_bool_is_not_a_number():
    r = result(structured={"ok": True})
    assert check(r, jsonpath={"$.ok": {"type": "number"}})
    assert check(r, jsonpath={"$.ok": {"type": "boolean"}}) == []


def test_max_latency():
    assert check(result(latency_ms=50), max_latency_ms=100) == []
    assert "limit is 10ms" in check(result(latency_ms=50), max_latency_ms=10)[0]


def test_output_schema():
    schema = {"type": "object", "properties": {"temp_c": {"type": "number"}}}
    good = result(structured={"temp_c": 1.5})
    bad = result(structured={"temp_c": "1.5"})
    assert check_expectations(good, Expect(), schema) == []
    assert "is not of type 'number'" in check_expectations(bad, Expect(), schema)[0]
    assert check_expectations(bad, Expect(output_schema=False), schema) == []
    assert "no structured content" in check_expectations(result("x"), Expect(), schema)[0]


def test_output_schema_skipped_for_errors():
    schema = {"type": "object", "required": ["temp_c"]}
    assert check_expectations(result(is_error=True), Expect(), schema) == []


def test_transport_error_short_circuits():
    r = result(is_error=True, transport_error="connection lost")
    failures = check(r, is_error=True, contains="x")
    assert failures == ["no result from server: connection lost"]
