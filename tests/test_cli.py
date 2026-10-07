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


def test_fuzz_command_reports_crash(tmp_path):
    junit = tmp_path / "fuzz.xml"
    result = runner.invoke(
        app,
        [
            "fuzz",
            "--tool",
            "get_weather",
            "--examples",
            "15",
            "--seed",
            "1",
            "--junit",
            str(junit),
            "--",
            sys.executable,
            BUGGY,
        ],
    )
    assert result.exit_code == 1, result.output
    assert "crash (valid)" in result.stdout
    assert "--seed 1" in result.stdout

    suites = {s.get("name"): s for s in ET.parse(junit).getroot().findall("testsuite")}
    assert list(suites) == ["fuzz"]  # only the phase that ran
    assert suites["fuzz"].get("failures") == "1"


def test_fuzz_command_passes_on_good_server():
    result = runner.invoke(app, ["fuzz", "--examples", "10", "--", sys.executable, WEATHER])
    assert result.exit_code == 0, result.output


def test_bench_command(tmp_path):
    json_out = tmp_path / "bench.json"
    args = [
        "bench",
        "--tool",
        "get_weather",
        "--args",
        '{"city": "Toronto"}',
        "--calls",
        "20",
        "--concurrency",
        "4",
        "--json",
        str(json_out),
        "--",
        sys.executable,
        WEATHER,
    ]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    [b] = json.loads(json_out.read_text())["bench"]
    assert b["calls"] == 20 and b["errors"] == 0

    result = runner.invoke(app, [*args[:-2], "--p50-ms", "0.001", "--", sys.executable, WEATHER])
    assert result.exit_code == 1


def test_bench_needs_something_to_run():
    result = runner.invoke(app, ["bench", "--", sys.executable, WEATHER])
    assert result.exit_code == 2


def test_run_includes_bench_and_fuzz_sections(tmp_path):
    path = tmp_path / "toolproof.yaml"
    data = {
        "server": {"command": [sys.executable, WEATHER]},
        "tests": [{"name": "toronto", "tool": "get_weather", "args": {"city": "Toronto"}}],
        "bench": {"calls": 10},
        "fuzz": {"max_examples": 5, "seed": 1},
    }
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    junit = tmp_path / "out.xml"

    result = runner.invoke(app, ["run", str(path), "--junit", str(junit)])
    assert result.exit_code == 0, result.output
    names = [s.get("name") for s in ET.parse(junit).getroot().findall("testsuite")]
    assert names == ["static checks", "tests", "bench", "fuzz"]

    result = runner.invoke(app, ["run", str(path), "--skip-fuzz", "--junit", str(junit)])
    names = [s.get("name") for s in ET.parse(junit).getroot().findall("testsuite")]
    assert names == ["static checks", "tests", "bench"]
