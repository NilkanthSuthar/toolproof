"""End-to-end tests: start the example servers and run real test cases against them."""

from tests.conftest import BUGGY, WEATHER
from toolproof.runner import run_config


def by_name(report):
    return {t.name: t for t in report.tests}


def test_weather_server_passes(write_config):
    config = write_config(
        WEATHER,
        [
            {
                "name": "toronto",
                "tool": "get_weather",
                "args": {"city": "Toronto"},
                "expect": {
                    "is_error": False,
                    "contains": "Toronto",
                    "jsonpath": {"$.temp_c": {"type": "number"}},
                    "max_latency_ms": 5000,
                },
            },
            {
                "name": "empty city",
                "tool": "get_weather",
                "args": {"city": ""},
                "expect": {"is_error": True, "contains": "must not be empty"},
            },
        ],
    )
    report = run_config(config)
    assert report.error is None
    assert report.server_name == "weather"
    assert report.checks == []
    assert [t.passed for t in report.tests] == [True, True], report.tests
    assert report.passed


def test_unknown_tool_fails_without_calling(write_config):
    config = write_config(WEATHER, [{"name": "x", "tool": "no_such_tool"}])
    report = run_config(config)
    assert not report.passed
    assert "no tool named 'no_such_tool'" in report.tests[0].failures[0]
    assert report.tests[0].attempts == 0


def test_buggy_server_bugs_are_caught(write_config):
    config = write_config(
        BUGGY,
        [
            {"name": "ok", "tool": "get_weather", "args": {"city": "Toronto"}},
            {
                "name": "crash",
                "tool": "get_weather",
                "args": {"city": ""},
                "expect": {"is_error": True},
            },
            {
                "name": "after crash",
                "tool": "get_weather",
                "args": {"city": "Montreal"},
                "expect": {"contains": "Montreal"},
            },
            {"name": "slow", "tool": "slow_report", "args": {"city": "x"}, "timeout_ms": 500},
            {"name": "schema", "tool": "get_temperature", "args": {"city": "x"}},
        ],
    )
    report = run_config(config)
    tests = by_name(report)

    # Bugs 2 and 5: broken tool definitions are found by the static checks.
    found = {(c.tool, c.check) for c in report.checks}
    assert ("search_cities", "description") in found
    assert ("search_cities", "input-schema") in found
    assert ("lookup", "required-fields") in found

    assert tests["ok"].passed

    # Bug 1: the crash is reported, and the server is restarted for the next test.
    assert not tests["crash"].passed
    assert "connection lost" in tests["crash"].failures[0]
    assert tests["after crash"].passed

    # Bug 3: the slow tool times out.
    assert not tests["slow"].passed
    assert "timed out" in tests["slow"].failures[0]

    # Bug 4: structured output doesn't match the declared outputSchema.
    assert not tests["schema"].passed
    assert "is not of type 'number'" in tests["schema"].failures[0]

    assert not report.passed


def test_retries(write_config):
    config = write_config(
        WEATHER,
        [{"name": "fails", "tool": "get_weather", "args": {"city": "Atlantis"}}],
        retries=2,
    )
    config.tests[0].expect.is_error = False
    report = run_config(config)
    assert report.tests[0].attempts == 3
    assert not report.tests[0].passed


def test_server_that_wont_start(write_config, tmp_path):
    script = tmp_path / "broken.py"
    script.write_text("import sys\nprint('missing dependency', file=sys.stderr)\nsys.exit(1)\n")
    config = write_config(str(script), [])
    config.server.startup_timeout_s = 10
    report = run_config(config)
    assert not report.passed
    assert report.error is not None
    assert "could not connect" in report.error
    # The server's stderr is included so the user can see why it died.
    assert "missing dependency" in report.error
