# toolproof

[![PyPI](https://img.shields.io/pypi/v/mcp-toolproof)](https://pypi.org/project/mcp-toolproof/)
[![Python](https://img.shields.io/pypi/pyversions/mcp-toolproof)](https://pypi.org/project/mcp-toolproof/)
[![CI](https://github.com/NilkanthSuthar/toolproof/actions/workflows/ci.yml/badge.svg)](https://github.com/NilkanthSuthar/toolproof/actions/workflows/ci.yml)
[![Docs](https://img.shields.io/badge/docs-online-blue)](https://nilkanthsuthar.github.io/toolproof/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/NilkanthSuthar/toolproof/blob/main/LICENSE)

**Automated tests for [Model Context Protocol](https://modelcontextprotocol.io) servers.** Check tool definitions, write YAML or pytest tests, fuzz every tool from its schema, benchmark latency, and fail the build when something breaks.

```bash
pip install mcp-toolproof
toolproof fuzz -- python my_server.py
```

**[Documentation](https://nilkanthsuthar.github.io/toolproof/)** · [Getting started](https://nilkanthsuthar.github.io/toolproof/getting-started/) · [Configuration](https://nilkanthsuthar.github.io/toolproof/guide/configuration/) · [CLI](https://nilkanthsuthar.github.io/toolproof/reference/cli/) · [Changelog](https://github.com/NilkanthSuthar/toolproof/blob/main/CHANGELOG.md)

## Features

- **Static checks**: every tool needs a name, a description, a valid JSON Schema and required fields that exist
- **YAML tests**: assert on errors, text, regex, JSONPath values, latency and the tool's own `outputSchema`
- **Fuzzing**: valid and invalid inputs generated from each tool's schema with Hypothesis; crashes, hangs, internal errors and leaked tracebacks, each shrunk to the smallest failing input
- **Benchmarks**: p50/p95/p99 latency, throughput and error rate under concurrency, with thresholds
- **pytest plugin**: an `mcp_server` fixture for tests written in Python
- **Built for CI**: exit codes, JUnit XML and JSON reports, a fixed seed for repeatable fuzz runs, `${VAR}` secrets
- **Any server**: stdio or streamable HTTP, written in Python, TypeScript, Go or anything else; crashed servers are restarted and their stderr is shown

## Quick start

See what a server offers and whether its tool definitions are sound:

```bash
toolproof inspect -- python my_server.py
toolproof inspect --url http://localhost:8000/mcp
```

Write tests in `toolproof.yaml`:

```yaml
server:
  command: ["python", "my_server.py"]

tests:
  - name: toronto weather
    tool: get_weather
    args: { city: Toronto }
    expect:
      is_error: false
      jsonpath: { "$.temp_c": { type: number, min: -60, max: 60 } }
      max_latency_ms: 2000

  - name: rejects empty city
    tool: get_weather
    args: { city: "" }
    expect: { is_error: true }

bench:
  thresholds: { p95_ms: 200 }

fuzz:
  seed: 1
```

```bash
toolproof run toolproof.yaml --junit report.xml
```

Or in Python, with the pytest plugin:

```python
def test_weather(mcp_server):
    r = mcp_server.call("get_weather", city="Toronto")
    assert not r.is_error
    assert r.data["temp_c"] > -60
```

## Fuzzing finds bugs without writing tests

[`examples/buggy_server.py`](https://github.com/NilkanthSuthar/toolproof/blob/main/examples/buggy_server.py) has five planted bugs. `toolproof fuzz` finds all of them on its own:

```
$ toolproof fuzz --seed 3 -- python examples/buggy_server.py

Fuzz (seed 3)
┌──────┬─────────────────┬───────┬────────────────────────────┬─────────────────┬─────────────────────────────────────────────┐
│      │ Tool            │ Calls │ Finding                    │ Smallest input  │ Details                                     │
├──────┼─────────────────┼───────┼────────────────────────────┼─────────────────┼─────────────────────────────────────────────┤
│ FAIL │ get_weather     │    21 │ crash (valid)              │ {"city": ""}    │ connection lost, server probably crashed    │
│      │                 │       │                            │                 │ (Connection closed)                         │
│      │                 │       │ accepted-invalid (invalid) │ {"city": []}    │ invalid input returned a success result     │
│      │                 │       │ crash (invalid)            │ {}              │ connection lost, server probably crashed    │
│      │                 │       │                            │                 │ (Connection closed)                         │
│ FAIL │ search_cities   │     0 │ bad-schema (valid)         │ {}              │ can't generate inputs: 'strng' is not valid │
│      │                 │       │                            │                 │ under any of the given schemas              │
│ FAIL │ slow_report     │     1 │ hang (valid)               │ {"city": ""}    │ timed out after 1.0s                        │
│ FAIL │ get_temperature │    24 │ output-schema (valid)      │ {"city": ""}    │ output schema: $.temp_c: '12.5' is not of   │
│      │                 │       │                            │                 │ type 'number'                               │
│      │                 │       │ accepted-invalid (invalid) │ {}              │ invalid input returned a success result     │
│ FAIL │ lookup          │    15 │ internal-error (valid)     │ {"city_id": {}} │ JSON-RPC error -32603: Internal server      │
│      │                 │       │                            │                 │ error                                       │
│      │                 │       │ internal-error (invalid)   │ {}              │ JSON-RPC error -32603: Internal server      │
│      │                 │       │                            │                 │ error                                       │
└──────┴─────────────────┴───────┴────────────────────────────┴─────────────────┴─────────────────────────────────────────────┘
Repeat this run with --seed 3

FAILED  |  fuzz: 9 findings in 5 tools  |  24.33s
```

> **Warning:** fuzzing calls your tools for real, many times, with odd arguments. Point it at a test instance, and skip tools that send, delete or spend. See the [fuzzing guide](https://nilkanthsuthar.github.io/toolproof/guide/fuzzing/).

## Tested on

toolproof is run against the official [MCP reference servers](https://github.com/modelcontextprotocol/servers): everything, filesystem, git, memory, sequential-thinking, time and fetch. In October 2026 that was about 3,000 fuzz calls, 15 [security boundary tests](https://nilkanthsuthar.github.io/toolproof/recipes/security-boundaries/) and benchmarks. All of them held up; the reference servers validate their input well.

## How it compares

[MCP Inspector](https://github.com/modelcontextprotocol/inspector) is for exploring a server by hand; toolproof is for tests that run unattended in CI. Other projects cover declarative YAML tests, snapshot regression gates, agent evaluations and security scanning. toolproof's focus is behaviour testing with schema-driven fuzzing and benchmarks, offline and without an LLM. See the [comparison](https://nilkanthsuthar.github.io/toolproof/about/comparison/) for details.

## Requirements

- Python 3.11 to 3.14 on Linux, macOS or Windows
- The server can be written in any language

## Contributing

Bug reports, fixes and new checks are welcome. See [CONTRIBUTING.md](https://github.com/NilkanthSuthar/toolproof/blob/main/CONTRIBUTING.md) for the development setup, and [SECURITY.md](https://github.com/NilkanthSuthar/toolproof/blob/main/SECURITY.md) to report a security problem privately.

## License

[MIT](https://github.com/NilkanthSuthar/toolproof/blob/main/LICENSE)
