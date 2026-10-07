# Python API

Everything below is importable from `toolproof` and covered by the [versioning policy](../about/versioning.md). Other modules are internal and may change in any release.

```python
from toolproof import (
    CallResult,
    Config,
    ConfigError,
    McpServer,
    RunReport,
    ServerConfig,
    ServerError,
    load_config,
    run_config,
    run_config_async,
)
```

## Running a config

### `load_config(path) -> Config`

Reads and validates a `toolproof.yaml`. Relative paths in it resolve from the file's folder, and `${VAR}` in the `server` section is expanded. Raises `ConfigError` with a readable message if the file is missing or invalid.

### `run_config(config, phases=None) -> RunReport`

Runs a config and returns the results. `phases` is any of `"checks"`, `"tests"`, `"bench"`, `"fuzz"`. By default it runs what `toolproof run` would: checks and tests, plus bench and fuzz if the config has those sections. Phases always run in that order.

`run_config` starts its own event loop. From async code, use `await run_config_async(config, phases)` instead.

```python
from toolproof import load_config, run_config

report = run_config(load_config("toolproof.yaml"), phases=["tests"])
for test in report.tests:
    print(test.name, "ok" if test.passed else test.failures)
assert report.passed
```

### `RunReport`

| Attribute | Type | Description |
|---|---|---|
| `passed` | bool | True if there's no connection error, no failing check, test, benchmark or fuzz finding. |
| `error` | str or None | Why the server couldn't be reached, with its stderr. |
| `phases` | list of str | The phases that ran. |
| `server_name`, `server_version` | str or None | From the server's handshake. |
| `tool_names` | list of str | Every tool the server listed. |
| `checks` | list | Static check problems: `tool`, `check`, `severity` (`"error"` or `"warning"`), `message`. |
| `tests` | list | Test results: `name`, `tool`, `passed`, `failures`, `latency_ms`, `attempts`, `result` (a `CallResult`), `server_stderr`. |
| `bench` | list | Benchmark results: `name`, `tool`, `calls`, `concurrency`, `errors`, `error_rate`, `throughput`, `p50_ms`, `p95_ms`, `p99_ms`, `mean_ms`, `max_ms`, `failures`, `passed`. |
| `fuzz` | list | Fuzz results per tool: `tool`, `calls`, `skipped`, `findings` (each with `kind`, `mode`, `input`, `detail`), `passed`. |
| `fuzz_seed` | int or None | The seed the fuzz phase used. |
| `duration_s` | float | Wall-clock time of the run. |

## Talking to a server directly

### `McpServer(config, base_dir=None)` { #mcpserver }

An async context manager holding one connection. For a stdio server it starts the process; leaving the block stops it.

```python
import anyio

from toolproof import McpServer, ServerConfig


async def main() -> None:
    config = ServerConfig(command=["python", "server.py"])
    async with McpServer(config) as server:
        tools = await server.list_tools()
        result = await server.call("get_weather", {"city": "Toronto"}, timeout_s=5)
        print([t.name for t in tools], result.data)


anyio.run(main)
```

| Method | Description |
|---|---|
| `await call(tool, arguments=None, timeout_s=None)` | Call a tool and return a `CallResult`. Never raises for tool errors, timeouts or a lost connection. |
| `await list_tools()` | All tools, following pagination. |
| `await server_info()` | Name, version, tools, resources and prompts. |
| `await is_alive(timeout_s=5)` | Whether the server still answers. |
| `await reconnect()` | Start a fresh connection (and process, for stdio). Safe to call from any task. |
| `stderr_tail(lines=20)` | The last lines a stdio server wrote to stderr. |

`base_dir` is the folder relative paths in `command` and `cwd` resolve from. It defaults to the current directory.

Raises `ServerError` if the server can't be started or the handshake fails. The message includes the server's stderr.

### `ServerConfig`

The `server` section of a config, as a pydantic model: `command`, `url`, `env`, `headers`, `cwd`, `startup_timeout_s`. See [Configuration](../guide/configuration.md#server). `${VAR}` is only expanded by `load_config`, not when you build a `ServerConfig` in code.

### `CallResult`

| Attribute | Type | Description |
|---|---|---|
| `tool`, `arguments` | | What was called. |
| `is_error` | bool | The tool reported an error, the server returned a JSON-RPC error, the call timed out, or the connection was lost. |
| `text` | str | Text content blocks joined with newlines. |
| `structured` | any | Structured content, if the tool returned any. |
| `data` | any | `structured`, or `text` parsed as JSON, or None. |
| `latency_ms` | float | Time the call took. |
| `transport_error` | str or None | Set when no result came back: a timeout or a lost connection. |
| `timed_out` | bool | The call hit its timeout. |
| `protocol_error` | bool | The server answered with a JSON-RPC error instead of a tool result. |
| `error_code` | int or None | The JSON-RPC error code when `protocol_error` is set. |

### Exceptions

| Exception | Raised when |
|---|---|
| `ConfigError` | A config file is missing, isn't valid YAML, fails validation, or uses an unset `${VAR}`. |
| `ServerError` | The server can't be started or reached. |
