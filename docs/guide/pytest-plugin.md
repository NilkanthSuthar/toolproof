# pytest plugin

Installing toolproof registers a pytest plugin. It adds an `mcp_server` fixture for writing tests in Python, for anything YAML can't express comfortably: loops, shared setup, multi-step flows.

## Configure the server

In `pyproject.toml`:

```toml
[tool.pytest.ini_options]
toolproof_command = "python my_server.py"
```

or `pytest.ini`:

```ini
[pytest]
toolproof_command = python my_server.py
```

| Option | Description |
|---|---|
| `toolproof_command` | Command that starts the server over stdio. Quote paths that contain spaces. |
| `toolproof_url` | Streamable HTTP URL of a running server. |
| `toolproof_config` | Path to a `toolproof.yaml`; its `server` section is used, including `env`, `headers` and `${VAR}` expansion. |
| `toolproof_timeout` | Per-call timeout in seconds. Default `30`. |

Relative paths are resolved from the pytest root directory.

## Write tests

```python
def test_weather(mcp_server):
    r = mcp_server.call("get_weather", city="Toronto")
    assert not r.is_error
    assert r.data["temp_c"] > -60


def test_dict_arguments(mcp_server):
    r = mcp_server.call("get_forecast", {"city": "Calgary"}, days=5)
    assert len(r.data["days"]) == 5


def test_rejects_empty_city(mcp_server):
    assert mcp_server.call("get_weather", city="").is_error


def test_schema(mcp_server):
    assert "get_weather" in mcp_server.tool_names()
    assert mcp_server.tool("get_weather").input_schema["required"] == ["city"]
```

The server starts once per test session and is shared by every test.

## The fixture

`mcp_server` is a `SyncMcpServer`, a blocking wrapper, so tests don't need to be async.

| Method | Returns |
|---|---|
| `call(tool, arguments=None, /, **kwargs)` | A [`CallResult`](../reference/python-api.md#callresult). Arguments can be a dict, keywords, or both. It never raises for tool errors, timeouts or a dead server; check `is_error` and `transport_error`. |
| `list_tools()` | The tool definitions (`mcp.types.Tool`). |
| `tool_names()` | Tool names. |
| `tool(name)` | One tool definition. Raises `KeyError` if missing. |

## Configure the server in code

Override the `mcp_server_config` fixture in `conftest.py`. It returns the server config and the folder relative paths are resolved from:

```python
from pathlib import Path

import pytest

from toolproof import ServerConfig


@pytest.fixture(scope="session")
def mcp_server_config():
    config = ServerConfig(command=["python", "my_server.py"], env={"MODE": "test"})
    return config, Path(__file__).parent
```

## Async tests

If your tests are async (with `pytest-anyio` or `pytest-asyncio`), use [`McpServer`](../reference/python-api.md#mcpserver) directly:

```python
import pytest

from toolproof import McpServer, ServerConfig


@pytest.mark.anyio
async def test_weather():
    async with McpServer(ServerConfig(command=["python", "my_server.py"])) as server:
        result = await server.call("get_weather", {"city": "Toronto"}, timeout_s=10)
        assert not result.is_error
```
