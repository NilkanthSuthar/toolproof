import json
import sys
import xml.etree.ElementTree as ET

import yaml
from typer.testing import CliRunner

from tests.conftest import BUGGY, WEATHER
from toolproof.cli import app

runner = CliRunner()


def write_yaml(path, script, tests):
    data = {"server": {"command": [sys.executable, script]}, "tests": tests}
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "toolproof" in result.stdout


def test_inspect_json():
    result = runner.invoke(app, ["inspect", "--json", "--", sys.executable, WEATHER])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["server"]["name"] == "weather"
    names = [t["name"] for t in data["tools"]]
    assert names == ["get_weather", "get_forecast", "list_cities"]
    assert "inputSchema" in data["tools"][0]
    assert data["resources"][0]["uri"] == "weather://cities"
    assert data["prompts"][0]["name"] == "weather_report"
    assert data["checks"] == []


def test_inspect_table_shows_check_problems():
    result = runner.invoke(app, ["inspect", "--", sys.executable, BUGGY])
    assert result.exit_code == 0, result.output
    assert "search_cities" in result.stdout
    assert "tool has no description" in result.stdout


def test_inspect_needs_a_server():
    result = runner.invoke(app, ["inspect"])
    assert result.exit_code == 2


def test_run_passing_suite_writes_reports(tmp_path):
    config = write_yaml(
        tmp_path / "toolproof.yaml",
        WEATHER,
        [{"name": "toronto", "tool": "get_weather", "args": {"city": "Toronto"}}],
    )
    junit = tmp_path / "out.xml"
    json_out = tmp_path / "out.json"
    result = runner.invoke(
        app, ["run", str(config), "--junit", str(junit), "--json", str(json_out)]
    )
    assert result.exit_code == 0, result.output
    assert "PASSED" in result.stdout

    root = ET.parse(junit).getroot()
    suites = {s.get("name"): s for s in root.findall("testsuite")}
    assert suites["tests"].get("tests") == "1"
    assert suites["tests"].get("failures") == "0"
    assert suites["static checks"].get("tests") == "3"  # one per tool

    data = json.loads(json_out.read_text())
    assert data["passed"] is True
    assert data["tests"][0]["name"] == "toronto"


def test_run_failing_suite_exits_1(tmp_path):
    config = write_yaml(
        tmp_path / "toolproof.yaml",
        BUGGY,
        [
            {
                "name": "empty city",
                "tool": "get_weather",
                "args": {"city": ""},
                "expect": {"is_error": True},
            }
        ],
    )
    junit = tmp_path / "out.xml"
    result = runner.invoke(app, ["run", str(config), "--junit", str(junit)])
    assert result.exit_code == 1
    assert "FAILED" in result.stdout

    root = ET.parse(junit).getroot()
    failures = root.findall(".//failure")
    messages = " ".join(f.get("message", "") for f in failures)
    assert "connection lost" in messages
    assert "tool has no description" in messages


def test_run_no_checks_ignores_bad_definitions(tmp_path):
    config = write_yaml(
        tmp_path / "toolproof.yaml",
        BUGGY,
        [{"name": "ok", "tool": "get_weather", "args": {"city": "Toronto"}}],
    )
    assert runner.invoke(app, ["run", str(config)]).exit_code == 1
    assert runner.invoke(app, ["run", str(config), "--no-checks"]).exit_code == 0


def test_run_bad_config_exits_2(tmp_path):
    path = tmp_path / "toolproof.yaml"
    path.write_text("tests: []\n")
    result = runner.invoke(app, ["run", str(path)])
    assert result.exit_code == 2
