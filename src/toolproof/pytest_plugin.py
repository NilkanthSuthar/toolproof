"""pytest plugin: an `mcp_server` fixture for writing MCP tests in plain Python.

Configure the server in pytest.ini or pyproject.toml:

    [tool.pytest.ini_options]
    toolproof_command = "python examples/weather_server.py"
    # or: toolproof_url = "http://localhost:8000/mcp"
    # or: toolproof_config = "toolproof.yaml"

Then:

    def test_weather(mcp_server):
        r = mcp_server.call("get_weather", city="Toronto")
        assert not r.is_error
        assert r.data["temp_c"] > -50

To configure it in code instead, override the `mcp_server_config` fixture in
your conftest.py and return a `toolproof.ServerConfig`.
"""

from __future__ import annotations

import os
import shlex
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import mcp_types as types
import pytest
from anyio.from_thread import BlockingPortal, start_blocking_portal

from toolproof.client import CallResult, McpServer
from toolproof.config import ServerConfig, load_config


class SyncMcpServer:
    """A blocking wrapper around `McpServer`, so tests don't need to be async."""

    def __init__(self, server: McpServer, portal: BlockingPortal, timeout_s: float) -> None:
        self._server = server
        self._portal = portal
        self.timeout_s = timeout_s

    def call(
        self, tool: str, arguments: dict[str, Any] | None = None, /, **kwargs: Any
    ) -> CallResult:
        """Call a tool. Pass arguments as a dict, as keywords, or both.

        mcp_server.call("get_weather", city="Toronto")
        mcp_server.call("get_weather", {"city": "Toronto"})
        """
        args = {**(arguments or {}), **kwargs}
        result: CallResult = self._portal.call(self._server.call, tool, args, self.timeout_s)
        return result

    def list_tools(self) -> list[types.Tool]:
        tools: list[types.Tool] = self._portal.call(self._server.list_tools)
        return tools

    def tool_names(self) -> list[str]:
        return [tool.name for tool in self.list_tools()]

    def tool(self, name: str) -> types.Tool:
        """Return one tool definition, or raise KeyError."""
        for tool in self.list_tools():
            if tool.name == name:
                return tool
        raise KeyError(name)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addini("toolproof_command", "Command that starts the MCP server over stdio.")
    parser.addini("toolproof_url", "Streamable HTTP URL of the MCP server.")
    parser.addini("toolproof_config", "Path to a toolproof.yaml to read the server from.")
    parser.addini("toolproof_timeout", "Per-call timeout in seconds (default 30).", default="30")


@pytest.fixture(scope="session")
def mcp_server_config(pytestconfig: pytest.Config) -> tuple[ServerConfig, Path]:
    """The server to connect to, read from the ini options.

    Returns the config and the directory relative paths are resolved from.
    Override this fixture to set the server up in code.
    """
    root = pytestconfig.rootpath
    command = str(pytestconfig.getini("toolproof_command") or "").strip()
    url = str(pytestconfig.getini("toolproof_url") or "").strip()
    config_file = str(pytestconfig.getini("toolproof_config") or "").strip()

    if config_file:
        config = load_config(root / config_file)
        return config.server, config.base_dir
    if url:
        return ServerConfig(url=url), root
    if command:
        return ServerConfig(command=split_command(command)), root
    raise pytest.UsageError(
        "mcp_server fixture is not configured. Set toolproof_command, toolproof_url "
        "or toolproof_config in pytest.ini / pyproject.toml, or override the "
        "mcp_server_config fixture."
    )


def split_command(command: str) -> list[str]:
    """Split a command string into arguments. Keeps Windows backslashes intact."""
    if os.name == "nt":
        return [part.strip('"') for part in shlex.split(command, posix=False)]
    return shlex.split(command)


@pytest.fixture(scope="session")
def mcp_server(
    pytestconfig: pytest.Config, mcp_server_config: tuple[ServerConfig, Path]
) -> Iterator[SyncMcpServer]:
    """A connected MCP server, shared by every test in the session."""
    config, base_dir = mcp_server_config
    timeout_s = float(pytestconfig.getini("toolproof_timeout") or 30)
    with (
        start_blocking_portal() as portal,
        portal.wrap_async_context_manager(McpServer(config, base_dir=base_dir)) as server,
    ):
        yield SyncMcpServer(server, portal, timeout_s)
