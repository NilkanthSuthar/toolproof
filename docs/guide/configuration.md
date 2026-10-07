# Configuration

toolproof reads a YAML file, by default `toolproof.yaml` in the current directory. Every key is optional except `server`. Unknown keys are errors, so a typo like `is_eror` fails loudly instead of being ignored.

## Full example

```yaml
server:
  command: ["python", "server.py"]
  env: { API_KEY: "${API_KEY}" }
  cwd: .
  startup_timeout_s: 30

timeout_ms: 10000
retries: 0

checks:
  enabled: true
  max_description_length: 1024
  strict: false

tests:
  - name: toronto weather
    tool: get_weather
    args: { city: Toronto }
    timeout_ms: 2000
    retries: 1
    expect:
      is_error: false
      contains: Toronto
      jsonpath:
        "$.temp_c": { type: number, min: -60, max: 60 }

bench:
  calls: 100
  concurrency: 10
  thresholds: { p95_ms: 200, max_error_rate: 0.01 }

fuzz:
  max_examples: 50
  seed: 1
  skip: [send_email]
```

## `server`

How to reach the server. Set exactly one of `command` or `url`.

| Key | Type | Default | Description |
|---|---|---|---|
| `command` | list of strings | | Command that starts the server over stdio, e.g. `["python", "server.py"]` or `["node", "dist/index.js"]`. |
| `url` | string | | Streamable HTTP endpoint, e.g. `http://localhost:8000/mcp`. |
| `env` | map | `{}` | Extra environment variables for a stdio server. |
| `headers` | map | `{}` | HTTP headers sent with every request to a `url` server, e.g. `Authorization`. |
| `cwd` | string | the YAML file's folder | Working directory for a stdio server, relative to the YAML file. |
| `startup_timeout_s` | number | `30` | How long to wait for the server to start and finish the MCP handshake. Also used for listing tools. |

!!! warning "A stdio server does not inherit your whole environment"
    For safety, the MCP SDK passes only a small set of variables to the server process: `PATH`, `HOME`, `USER`, `SHELL`, `TERM` and `LOGNAME` on Linux and macOS, and the Windows equivalents (`APPDATA`, `PATH`, `TEMP`, `USERPROFILE` and a few more). Anything else your server needs, such as API keys, must be listed under `env`.

### Secrets and environment variables

In the `server` section, `${NAME}` is replaced with the environment variable `NAME` when the file is loaded. Use it to keep secrets out of the repository:

```yaml
server:
  url: https://api.example.com/mcp
  headers:
    Authorization: "Bearer ${EXAMPLE_TOKEN}"
```

If the variable isn't set, loading fails with an error that names it. Expansion only happens in `server`; test arguments and expectations are used exactly as written.

### Relative paths

Paths in `command` and `cwd` are resolved from the folder that contains the YAML file. `toolproof run path/to/toolproof.yaml` therefore works from any directory.

The first item of `command` is looked up on `PATH` like any other program. For a Python server, make sure `python` on `PATH` is the environment where the server's dependencies are installed, or give the full path to that interpreter.

## Top-level settings

| Key | Type | Default | Description |
|---|---|---|---|
| `timeout_ms` | number | `10000` | Default timeout for each test call. |
| `retries` | integer | `0` | Retry a failing test this many times before reporting it. |

## `checks`

Settings for the [static checks](static-checks.md).

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | bool | `true` | Run the static checks as part of `toolproof run`. |
| `max_description_length` | integer | `1024` | Descriptions longer than this produce a warning. |
| `strict` | bool | `false` | Treat warnings as failures. |

## `tests`

A list of test cases, run in order against one server process.

| Key | Type | Default | Description |
|---|---|---|---|
| `name` | string | required | Shown in reports. |
| `tool` | string | required | The tool to call. A test for a tool the server doesn't have fails. |
| `args` | map | `{}` | Arguments for the tool. |
| `expect` | map | `{}` | What the result must look like. See [Assertions](assertions.md). |
| `timeout_ms` | number | top-level `timeout_ms` | Override for this test. |
| `retries` | integer | top-level `retries` | Override for this test. |

If a call crashes the server, the test fails with the server's last stderr lines, and toolproof starts a fresh server for the remaining tests.

## `bench`

Optional. When present, `toolproof run` benchmarks after the tests. See [Benchmarks](benchmarks.md).

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | bool | `true` | Include the section in `toolproof run`. |
| `calls` | integer | `100` | Calls per target. |
| `concurrency` | integer | `10` | Calls in flight at once. |
| `warmup` | integer | `3` | Calls made before measuring. |
| `timeout_ms` | number | `10000` | Timeout per call. A timed-out call counts as an error. |
| `thresholds` | map | none | Limits for every target; see below. |
| `targets` | list | every test expecting success | What to benchmark: `tool`, `args`, optional `name` and `thresholds`. |

`thresholds` keys, all optional: `p50_ms`, `p95_ms`, `p99_ms`, `max_error_rate` (a fraction, `0.01` is 1%) and `min_throughput` (calls per second). A target's own `thresholds` replace the section-wide ones.

## `fuzz`

Optional. When present, `toolproof run` fuzzes after the tests and benchmarks. See [Fuzzing](fuzzing.md).

| Key | Type | Default | Description |
|---|---|---|---|
| `enabled` | bool | `true` | Include the section in `toolproof run`. |
| `max_examples` | integer | `50` | Inputs per tool, once for valid and once for invalid inputs. |
| `timeout_ms` | number | `2000` | Timeout per call. A timeout is reported as a `hang`. |
| `max_time_s` | number | `60` | Time limit per tool. |
| `seed` | integer | random | Fix it for repeatable runs. Every report prints the seed it used. |
| `tools` | list | all tools | Fuzz only these tools. |
| `skip` | list | `[]` | Never fuzz these tools. |
| `include_destructive` | bool | `false` | Also fuzz tools annotated `destructiveHint: true`. |
| `valid_must_succeed` | bool | `false` | Report any error result for a valid input. |
| `invalid_must_fail` | bool | `true` | Report a success result for an invalid input. |
