# CLI

```
toolproof [--version] COMMAND [OPTIONS]
```

| Command | What it does |
|---|---|
| [`inspect`](#inspect) | List a server's tools, resources and prompts, and run the static checks. |
| [`run`](#run) | Run everything in a config file: static checks, tests, and bench and fuzz sections if present. |
| [`fuzz`](#fuzz) | Call every tool with generated inputs and report crashes, hangs and bad errors. |
| [`bench`](#bench) | Measure latency percentiles, throughput and error rate. |

## Choosing the server

`inspect`, `fuzz` and `bench` take the server in one of three ways:

```bash
toolproof fuzz -- python server.py          # a command, after --
toolproof fuzz --url http://localhost:8000/mcp
toolproof fuzz --config path/to/toolproof.yaml
```

With none of them, they read `./toolproof.yaml` if it exists. With a config file, its settings (`fuzz:`, `bench:`, `checks:`) are used, and command-line flags override them. `run` always takes a config file.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Everything passed. |
| `1` | A test, error-level static check, benchmark threshold or fuzz finding failed, or the server couldn't be reached during `run`, `fuzz` or `bench`. |
| `2` | Usage or configuration error: bad flags, invalid YAML, a missing environment variable, or no server given. `inspect` also uses `2` when it can't connect. |

## `inspect`

```
toolproof inspect [--url URL | --config FILE | -- COMMAND...] [--json]
```

| Option | Description |
|---|---|
| `--url URL` | Streamable HTTP URL of the server. |
| `-c`, `--config FILE` | Read the server from a toolproof.yaml. |
| `--json` | Print the full tool, resource and prompt definitions and the check results as JSON. |

`inspect` always exits `0` once it has connected, even when static checks find problems. Use `run` to fail on them.

## `run`

```
toolproof run [CONFIG] [OPTIONS]
```

`CONFIG` defaults to `toolproof.yaml`. Phases run in this order: static checks, tests, bench (if the file has a `bench:` section), fuzz (if it has a `fuzz:` section).

| Option | Description |
|---|---|
| `--junit PATH` | Write a JUnit XML report. |
| `--json PATH` | Write a JSON report. |
| `--timeout-ms N` | Default per-test timeout, overriding `timeout_ms`. |
| `--retries N` | Retry failing tests this many times, overriding `retries`. |
| `--strict` | Treat static check warnings as failures. |
| `--no-checks` | Skip the static checks. |
| `--skip-bench` | Skip the `bench:` section. |
| `--skip-fuzz` | Skip the `fuzz:` section. |

## `fuzz`

```
toolproof fuzz [--url URL | --config FILE | -- COMMAND...] [OPTIONS]
```

| Option | Description |
|---|---|
| `--examples N` | Inputs per tool, once for valid and once for invalid inputs. Default 50. |
| `--timeout-ms N` | Timeout per call. Default 2000. |
| `--max-time S` | Time limit per tool in seconds. Default 60. |
| `--seed N` | Random seed, to repeat a run. |
| `--tool NAME` | Only fuzz this tool. Repeat for several. |
| `--include-destructive` | Also fuzz tools annotated `destructiveHint: true`. |
| `--valid-must-succeed` | Report error results for valid inputs. |
| `--junit PATH` | Write a JUnit XML report. |
| `--json PATH` | Write a JSON report. |

See [Fuzzing](../guide/fuzzing.md).

## `bench`

```
toolproof bench [--url URL | --config FILE | -- COMMAND...] [OPTIONS]
```

| Option | Description |
|---|---|
| `--tool NAME` | Benchmark just this tool. |
| `--args JSON` | Arguments for `--tool`, as a JSON object. |
| `--calls N` | Calls per target. Default 100. |
| `--concurrency N` | Calls in flight at once. Default 10. |
| `--timeout-ms N` | Timeout per call. Default 10000. |
| `--p50-ms N`, `--p95-ms N`, `--p99-ms N` | Fail if the percentile is above this. |
| `--max-error-rate R` | Fail if the error rate is above this fraction (`0.01` = 1%). |
| `--min-throughput N` | Fail if calls per second is below this. |
| `--junit PATH` | Write a JUnit XML report. |
| `--json PATH` | Write a JSON report. |

Without `--tool`, `bench` uses `bench.targets` from the config, or every test that expects success. With nothing to benchmark it exits `2`. See [Benchmarks](../guide/benchmarks.md).

## Quoting JSON in shells

`--args` takes JSON, which needs quoting:

=== "bash / zsh"

    ```bash
    toolproof bench --tool get_weather --args '{"city": "Toronto"}' -- python server.py
    ```

=== "PowerShell 7.3+"

    ```powershell
    toolproof bench --tool get_weather --args '{"city": "Toronto"}' -- python server.py
    ```

=== "Windows PowerShell 5.1"

    ```powershell
    toolproof bench --tool get_weather --args '{\"city\": \"Toronto\"}' -- python server.py
    ```

    Older PowerShell strips the inner double quotes when it calls a program, so they must be escaped.

=== "cmd.exe"

    ```bat
    toolproof bench --tool get_weather --args "{\"city\": \"Toronto\"}" -- python server.py
    ```
