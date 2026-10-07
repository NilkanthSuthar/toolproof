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


def test_inspect_reports_a_server_that_wont_start(tmp_path):
    script = tmp_path / "broken.py"
    script.write_text("import sys\nsys.exit(3)\n")
    result = runner.invoke(app, ["inspect", "--", sys.executable, str(script)])
    assert result.exit_code == 2
    assert "could not connect" in result.output


def test_only_one_server_source_allowed():
    result = runner.invoke(
        app, ["inspect", "--url", "http://localhost:1/mcp", "--", sys.executable, WEATHER]
    )
    assert result.exit_code == 2
    assert "only one" in result.output


def test_falls_back_to_toolproof_yaml_in_cwd(tmp_path, monkeypatch):
    write_yaml(tmp_path / "toolproof.yaml", WEATHER, [])
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["inspect", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["server"]["name"] == "weather"


def test_no_server_and_no_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["fuzz"])
    assert result.exit_code == 2
    assert "Give a server command" in result.output


def test_run_flag_overrides(tmp_path):
    config = write_yaml(
        tmp_path / "toolproof.yaml",
        WEATHER,
        [
            {
                "name": "atlantis",
                "tool": "get_weather",
                "args": {"city": "Atlantis"},
                "expect": {"is_error": False},
            }
        ],
    )
    json_out = tmp_path / "out.json"
    args = ["run", str(config), "--timeout-ms", "3000", "--retries", "1", "--strict"]
    result = runner.invoke(app, [*args, "--skip-bench", "--json", str(json_out)])
    assert result.exit_code == 1
    assert json.loads(json_out.read_text())["tests"][0]["attempts"] == 2


def test_fuzz_flags_reach_the_config(tmp_path):
    json_out = tmp_path / "fuzz.json"
    args = [
        "fuzz",
        "--tool",
        "list_cities",
        "--examples",
        "3",
        "--timeout-ms",
        "3000",
        "--max-time",
        "30",
        "--seed",
        "7",
        "--include-destructive",
        "--valid-must-succeed",
        "--json",
        str(json_out),
        "--",
        sys.executable,
        WEATHER,
    ]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    data = json.loads(json_out.read_text())
    assert data["fuzz"]["seed"] == 7
    assert [t["tool"] for t in data["fuzz"]["tools"]] == ["list_cities"]


def test_bench_rejects_bad_args_json():
    result = runner.invoke(
        app, ["bench", "--tool", "get_weather", "--args", "{city:", "--", sys.executable, WEATHER]
    )
    assert result.exit_code == 2
    assert "not valid JSON" in result.output


def test_bench_threshold_flags(tmp_path):
    json_out = tmp_path / "bench.json"
    base = ["bench", "--tool", "list_cities", "--calls", "10", "--timeout-ms", "5000"]
    loose = ["--p95-ms", "5000", "--p99-ms", "5000", "--max-error-rate", "0"]
    result = runner.invoke(app, [*base, *loose, "--", sys.executable, WEATHER])
    assert result.exit_code == 0, result.output
    strict = ["--min-throughput", "1000000", "--json", str(json_out)]
    result = runner.invoke(app, [*base, *strict, "--", sys.executable, WEATHER])
    assert result.exit_code == 1
    [b] = json.loads(json_out.read_text())["bench"]
    assert "throughput" in b["failures"][0]


def test_inspect_table_shows_resources_and_prompts():
    result = runner.invoke(app, ["inspect", "--", sys.executable, WEATHER])
    assert result.exit_code == 0, result.output
    assert "Resources (1)" in result.stdout
    assert "Prompts (1)" in result.stdout
    assert "no problems found" in result.stdout
