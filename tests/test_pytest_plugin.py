"""Run the mcp_server fixture inside a separate pytest session."""

import os
import sys
from pathlib import Path

from tests.conftest import EXAMPLES, WEATHER
from toolproof.pytest_plugin import split_command

TEST_FILE = """
def test_weather(mcp_server):
    r = mcp_server.call("get_weather", city="Toronto")
    assert not r.is_error
    assert r.data["temp_c"] == 12.5

def test_dict_arguments(mcp_server):
    r = mcp_server.call("get_forecast", {"city": "Calgary"}, days=2)
    assert len(r.data["days"]) == 2

def test_error(mcp_server):
    assert mcp_server.call("get_weather", city="").is_error

def test_tools(mcp_server):
    assert "get_weather" in mcp_server.tool_names()
    assert mcp_server.tool("get_weather").input_schema["required"] == ["city"]
"""


def test_fixture_with_command(pytester):
    pytester.makeini(
        f"""
        [pytest]
        toolproof_command = "{sys.executable}" "{WEATHER}"
        """
    )
    pytester.makepyfile(TEST_FILE)
    result = pytester.runpytest()
    result.assert_outcomes(passed=4)


def test_fixture_with_config_file(pytester, monkeypatch):
    pytester.makeini(
        f"""
        [pytest]
        toolproof_config = {EXAMPLES / "toolproof.yaml"}
        """
    )
    pytester.makepyfile(TEST_FILE)
    # The example config runs plain "python"; make sure that is this interpreter.
    python_dir = str(Path(sys.executable).parent)
    monkeypatch.setenv("PATH", python_dir, prepend=os.pathsep)
    result = pytester.runpytest()
    result.assert_outcomes(passed=4)


def test_fixture_not_configured(pytester):
    pytester.makepyfile("def test_x(mcp_server):\n    pass\n")
    result = pytester.runpytest()
    result.stdout.fnmatch_lines(["*mcp_server fixture is not configured*"])


def test_split_command_keeps_quoted_paths():
    assert split_command('python "my server.py" --flag') == ["python", "my server.py", "--flag"]
