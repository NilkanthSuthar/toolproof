# toolproof

[![CI](https://github.com/NilkanthSuthar/toolproof/actions/workflows/ci.yml/badge.svg)](https://github.com/NilkanthSuthar/toolproof/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/toolproof)](https://pypi.org/project/toolproof/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**pytest for MCP servers.** Write repeatable tests for any [Model Context Protocol](https://modelcontextprotocol.io) server's tools and run them in CI.

- **Static checks** on every tool definition: missing descriptions, invalid JSON Schemas, duplicate names, required fields that don't exist
- **YAML test cases**: call a tool and assert on errors, text, regex, JSONPath values, latency and the declared `outputSchema`
- **Crash detection**: if the server dies mid-test, toolproof reports it with the server's stderr, restarts the server and keeps going
- **CI-friendly output**: exit code 0/1, JUnit XML and JSON reports
- **pytest plugin**: an `mcp_server` fixture for tests written in Python
- Works with any server over **stdio** or **streamable HTTP**, in any language

## Install

```bash
pip install toolproof
```

Python 3.11+.

## 30-second quickstart

Look at a server:

```bash
toolproof inspect -- python my_server.py
toolproof inspect --url http://localhost:8000/mcp
```

Write `toolproof.yaml`:

```yaml
server:
  command: ["python", "my_server.py"]

tests:
  - name: toronto weather
    tool: get_weather
    args: { city: Toronto }
    expect:
      is_error: false
      contains: "Toronto"
      jsonpath: { "$.temp_c": { type: number } }
      max_latency_ms: 2000

  - name: rejects empty city
    tool: get_weather
    args: { city: "" }
    expect: { is_error: true }
```

Run it:

```bash
toolproof run toolproof.yaml --junit report.xml
```

## What a failing run looks like

`examples/buggy_server.py` has five planted bugs. Here is `toolproof run examples/buggy.yaml`:

```
toolproof - buggy-weather 0.0.1

Static checks
┌──────┬───────────────┬─────────────────┬──────────────────────────────────────────────────────────────────┐
│      │ Tool          │ Check           │ Problem                                                          │
├──────┼───────────────┼─────────────────┼──────────────────────────────────────────────────────────────────┤
│ FAIL │ search_cities │ description     │ tool has no description                                          │
│ FAIL │ search_cities │ input-schema    │ input schema is not valid JSON Schema: 'strng' is not valid      │
│      │               │                 │ under any of the given schemas                                   │
│ FAIL │ lookup        │ required-fields │ required fields not listed in properties: city_id                │
└──────┴───────────────┴─────────────────┴──────────────────────────────────────────────────────────────────┘

Tests
┌──────┬────────────────────────────────────┬─────────────────┬────────┬────────────────────────────────────┐
│      │ Test                               │ Tool            │   Time │ Details                            │
├──────┼────────────────────────────────────┼─────────────────┼────────┼────────────────────────────────────┤
│ PASS │ weather works for a normal city    │ get_weather     │    5ms │                                    │
│ FAIL │ empty city should be an error, not │ get_weather     │   23ms │ no result from server: connection  │
│      │ a crash                            │                 │        │ lost, server probably crashed      │
│      │                                    │                 │        │ (Connection closed)                │
│ PASS │ server still works after the crash │ get_weather     │    3ms │                                    │
│ FAIL │ report comes back in time          │ slow_report     │ 1001ms │ no result from server: timed out   │
│      │                                    │                 │        │ after 1.0s                         │
│ FAIL │ temperature matches its output     │ get_temperature │    2ms │ output schema: $.temp_c: '12.5' is │
│      │ schema                             │                 │        │ not of type 'number'               │
└──────┴────────────────────────────────────┴─────────────────┴────────┴────────────────────────────────────┘

FAILED  tests: 2 passed, 3 failed  |  checks: 3 errors, 0 warnings  |  7.21s
```

The same run as JUnit XML (`--junit report.xml`), which GitHub, GitLab and Jenkins show as a normal test report:

```xml
<testsuite name="tests" tests="5" failures="3" errors="0" time="1.034">
  <testcase classname="toolproof.get_weather" name="weather works for a normal city" time="0.005" />
  <testcase classname="toolproof.get_weather" name="empty city should be an error, not a crash" time="0.023">
    <failure message="no result from server: connection lost, server probably crashed (Connection closed)">...</failure>
  </testcase>
  ...
</testsuite>
```

## YAML reference

```yaml
server:
  command: ["python", "server.py"]   # start the server over stdio...
  # url: http://localhost:8000/mcp   # ...or connect over streamable HTTP (exactly one)
  env: { API_KEY: test }             # extra environment variables (stdio only)
  cwd: .                             # working directory, relative to this file (default: this file's folder)
  startup_timeout_s: 30

timeout_ms: 10000        # default per-test timeout
retries: 0               # retry failing tests this many times

checks:
  enabled: true
  max_description_length: 1024
  strict: false          # treat warnings as failures

tests:
  - name: a readable name
    tool: tool_name
    args: { any: json }
    timeout_ms: 2000     # optional override
    retries: 1           # optional override
    expect:
      is_error: false
      equals: { result: 42 }         # whole result: structured content, JSON text, or plain text
      contains: "Toronto"            # or a list: ["Toronto", "cloudy"]
      regex: "\\d+ C"
      jsonpath:
        "$.temp_c": { type: number, min: -50, max: 50 }
        "$.city": { equals: Toronto }
        "$.wind": { exists: false }
      max_latency_ms: 2000
      output_schema: true            # validate against the tool's outputSchema (default on)
```

Notes:

- `jsonpath` looks at the tool's structured content if it returned any, otherwise at its text parsed as JSON.
- `type` is a JSON Schema type: `string`, `number`, `integer`, `boolean`, `array`, `object`, `null`.
- If a tool declares an `outputSchema`, every successful call is validated against it automatically.
- Paths in `command` and `cwd` are relative to the YAML file, so `toolproof run path/to/toolproof.yaml` works from anywhere.

### Static checks

| Check | Severity | What it catches |
|---|---|---|
| `name` | error | tool with an empty name |
| `duplicate-name` | error | two tools with the same name |
| `description` | error | tool with no description |
| `description-length` | warning | description longer than `max_description_length` |
| `input-schema` | error | input schema that isn't valid JSON Schema, or whose root isn't `type: object` |
| `required-fields` | error | `required` lists a field that isn't in `properties` |
| `required-fields` | warning | tool has properties but none are marked required |
| `output-schema` | error | `outputSchema` that isn't valid JSON Schema |

Errors fail the run. Warnings only fail it with `--strict`.

## CLI reference

```
toolproof inspect [--url URL | --config FILE | -- COMMAND...] [--json]
toolproof run [CONFIG] [--junit PATH] [--json PATH] [--timeout-ms N] [--retries N] [--strict] [--no-checks]
```

Exit codes for `run`: `0` all passed, `1` a test or check failed, `2` bad config or usage.

## pytest plugin

Installing toolproof registers a pytest plugin with an `mcp_server` fixture. Point it at your server in `pyproject.toml`:

```toml
[tool.pytest.ini_options]
toolproof_command = "python my_server.py"
# toolproof_url = "http://localhost:8000/mcp"
# toolproof_config = "toolproof.yaml"
# toolproof_timeout = "30"
```

Then write normal tests:

```python
def test_weather(mcp_server):
    r = mcp_server.call("get_weather", city="Toronto")
    assert not r.is_error
    assert r.data["temp_c"] > -50


def test_forecast_length(mcp_server):
    r = mcp_server.call("get_forecast", {"city": "Calgary", "days": 5})
    assert len(r.data["days"]) == 5


def test_schema(mcp_server):
    assert mcp_server.tool("get_weather").input_schema["required"] == ["city"]
```

`call()` returns a `CallResult` with `is_error`, `text`, `data` (structured content or parsed JSON), `latency_ms` and `transport_error`. The server starts once per test session.

To set the server up in code, override the `mcp_server_config` fixture in `conftest.py`:

```python
import pytest
from pathlib import Path
from toolproof import ServerConfig

@pytest.fixture(scope="session")
def mcp_server_config():
    return ServerConfig(command=["python", "my_server.py"], env={"MODE": "test"}), Path.cwd()
```

## Using it in GitHub Actions

```yaml
- run: pip install toolproof
- run: toolproof run toolproof.yaml --junit report.xml
- uses: actions/upload-artifact@v4
  if: always()
  with:
    name: toolproof-report
    path: report.xml
```

## How is this different from MCP Inspector?

[MCP Inspector](https://github.com/modelcontextprotocol/inspector) is an interactive debugger: you open a UI, click a tool, type arguments and look at the result. It's great while building a server.

toolproof is for what comes after: tests you write once, keep in the repo and run on every pull request. It has no UI. It gives you assertions, an exit code and a JUnit report, so a broken tool fails the build instead of being found by a user.

## Try it on the examples

```bash
git clone https://github.com/NilkanthSuthar/toolproof
cd toolproof
pip install -e .
toolproof run examples/toolproof.yaml   # passes
toolproof run examples/buggy.yaml       # fails, on purpose
```

## Roadmap

- **v0.1**: inspect, static checks, YAML tests, console/JUnit/JSON reports, pytest plugin
- **v0.2**: `toolproof fuzz` (schema-based fuzzing with Hypothesis) and `toolproof bench` (p50/p95/p99 latency, throughput)
- **v0.3**: LLM tool-selection evals, a reusable GitHub Action, an HTML report, docs site

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check . && ruff format --check .
mypy
```

The test suite starts the example servers for real, over stdio and HTTP.

## License

MIT
