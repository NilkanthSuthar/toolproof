# toolproof

**Automated tests for [Model Context Protocol](https://modelcontextprotocol.io) servers.**

toolproof connects to any MCP server, over stdio or streamable HTTP, and checks that its tools behave. You write the checks once, keep them in the repo, and run them on every pull request.

```bash
pip install mcp-toolproof
toolproof inspect -- python my_server.py
```

## What it does

| Feature | What it does |
|---|---|
| **[Static checks](guide/static-checks.md)** | Every tool definition is checked for a name, a description, a valid input/output JSON Schema and consistent required fields. |
| **[YAML tests](guide/assertions.md)** | Call a tool and assert on errors, text, regex, JSONPath values, latency and the tool's own `outputSchema`. |
| **[Fuzzing](guide/fuzzing.md)** | Generate valid and invalid inputs from each tool's schema, find crashes, hangs and leaked tracebacks, and shrink each one to the smallest failing input. |
| **[Benchmarks](guide/benchmarks.md)** | Measure p50/p95/p99 latency, throughput and error rate under concurrency, and fail the build on a slow tool. |
| **[pytest plugin](guide/pytest-plugin.md)** | An `mcp_server` fixture for tests written in Python. |
| **[CI output](guide/ci.md)** | Exit codes, JUnit XML and JSON reports. |

It works with servers written in any language. The server is a black box: toolproof only talks MCP to it.

## A first run

```yaml title="toolproof.yaml"
server:
  command: ["python", "my_server.py"]

tests:
  - name: toronto weather
    tool: get_weather
    args: { city: Toronto }
    expect:
      is_error: false
      jsonpath: { "$.temp_c": { type: number } }

  - name: rejects empty city
    tool: get_weather
    args: { city: "" }
    expect: { is_error: true }
```

```bash
toolproof run toolproof.yaml --junit report.xml
toolproof fuzz -- python my_server.py
```

Continue with [Getting started](getting-started.md).

## Where it fits

[MCP Inspector](https://github.com/modelcontextprotocol/inspector) is the tool for poking at a server by hand while you build it. toolproof covers what comes after: repeatable tests that run unattended and fail the build. See [Comparison with other tools](about/comparison.md) for how it relates to other MCP testing projects.
