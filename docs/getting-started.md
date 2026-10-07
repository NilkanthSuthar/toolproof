# Getting started

## Install

```bash
pip install mcp-toolproof
```

toolproof needs Python 3.11 or newer. The package is called `mcp-toolproof` on PyPI; the command and the Python import are both `toolproof`.

```bash
toolproof --version
```

!!! tip "Install it next to your server"
    If your server is written in Python, install toolproof into the same virtual environment, so that `python my_server.py` inside toolproof finds your server's dependencies. For servers in other languages it doesn't matter; see [Servers in other languages](recipes/other-languages.md).

## 1. Look at your server

```bash
toolproof inspect -- python my_server.py
```

Everything after `--` is the command that starts your server. toolproof starts it, runs the MCP handshake, lists the tools, resources and prompts, and runs the [static checks](guide/static-checks.md). For a server that is already running over HTTP:

```bash
toolproof inspect --url http://localhost:8000/mcp
```

Add `--json` to get the full tool definitions, including input schemas, as JSON.

## 2. Fuzz it

Before writing any tests, let toolproof try to break the server:

```bash
toolproof fuzz -- python my_server.py
```

This calls every tool with generated inputs, both valid and invalid, and reports crashes, hangs, internal errors and similar problems. See [Fuzzing](guide/fuzzing.md) before running it against a server whose tools change real data.

## 3. Write tests

Create `toolproof.yaml` next to your server:

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
      jsonpath:
        "$.temp_c": { type: number, min: -60, max: 60 }
      max_latency_ms: 2000

  - name: rejects empty city
    tool: get_weather
    args: { city: "" }
    expect: { is_error: true }
```

Run it:

```bash
toolproof run toolproof.yaml
```

`run` exits with `0` when everything passes and `1` when anything fails, so it works as a CI step as is. See [Configuration](guide/configuration.md) for every option and [Assertions](guide/assertions.md) for what `expect` can check.

## 4. Add it to CI

```yaml title=".github/workflows/toolproof.yml"
name: toolproof
on: [push, pull_request]
jobs:
  toolproof:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v7
        with:
          python-version: "3.12"
      - run: pip install -e . mcp-toolproof
      - run: toolproof run toolproof.yaml --junit report.xml
      - uses: actions/upload-artifact@v7
        if: always()
        with:
          name: toolproof-report
          path: report.xml
```

More in [Running in CI](guide/ci.md).

## Try it on the examples

The repository ships a working server and a deliberately broken one:

```bash
git clone https://github.com/NilkanthSuthar/toolproof
cd toolproof
pip install -e .
toolproof run examples/toolproof.yaml              # passes: tests, bench and fuzz
toolproof run examples/buggy.yaml                  # fails, on purpose
toolproof fuzz -- python examples/buggy_server.py  # finds all five planted bugs
```
