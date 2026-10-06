import mcp_types as types

from toolproof.checks import has_failures, run_checks
from toolproof.config import ChecksConfig


def tool(name="get_weather", description="Get the weather.", schema=None, output_schema=None):
    if schema is None:
        schema = {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        }
    return types.Tool(
        name=name, description=description, input_schema=schema, output_schema=output_schema
    )


def checks_for(*tools, **config):
    return {(p.tool, p.check, p.severity) for p in run_checks(list(tools), ChecksConfig(**config))}


def test_good_tool_has_no_problems():
    assert run_checks([tool()]) == []


def test_missing_description():
    assert ("get_weather", "description", "error") in checks_for(tool(description=None))
    assert ("get_weather", "description", "error") in checks_for(tool(description="   "))


def test_long_description_is_a_warning():
    found = checks_for(tool(description="x" * 50), max_description_length=10)
    assert found == {("get_weather", "description-length", "warning")}


def test_duplicate_names():
    assert ("get_weather", "duplicate-name", "error") in checks_for(tool(), tool())


def test_invalid_schema():
    bad = tool(schema={"type": "object", "properties": {"q": {"type": "strng"}}})
    assert ("get_weather", "input-schema", "error") in checks_for(bad)


def test_schema_root_must_be_object():
    assert ("get_weather", "input-schema", "error") in checks_for(tool(schema={"type": "string"}))


def test_required_field_missing_from_properties():
    bad = tool(schema={"type": "object", "properties": {}, "required": ["city"]})
    assert ("get_weather", "required-fields", "error") in checks_for(bad)


def test_no_required_fields_is_a_warning():
    loose = tool(schema={"type": "object", "properties": {"city": {"type": "string"}}})
    assert checks_for(loose) == {("get_weather", "required-fields", "warning")}


def test_tool_without_arguments_is_fine():
    assert run_checks([tool(schema={"type": "object"})]) == []


def test_invalid_output_schema():
    bad = tool(output_schema={"type": "object", "properties": {"t": {"type": 5}}})
    assert ("get_weather", "output-schema", "error") in checks_for(bad)


def test_warnings_only_fail_in_strict_mode():
    loose = tool(schema={"type": "object", "properties": {"city": {"type": "string"}}})
    problems = run_checks([loose])
    assert not has_failures(problems)
    assert has_failures(problems, strict=True)
