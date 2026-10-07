"""Connect over streamable HTTP instead of stdio."""

import socket
import subprocess
import sys
import time
from pathlib import Path

import anyio
import pytest

from tests.conftest import WEATHER
from toolproof.client import McpServer, ServerError
from toolproof.config import ServerConfig


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


TOKEN_SERVER = str(Path(__file__).parent / "servers" / "token_server.py")


def start_server(args: list[str], port: int):
    proc = subprocess.Popen(
        [sys.executable, *args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
            return proc
        except OSError:
            time.sleep(0.2)
    proc.terminate()
    pytest.fail("HTTP server did not start")


@pytest.fixture(scope="module")
def http_url():
    port = free_port()
    proc = start_server([WEATHER, "--http", "--port", str(port)], port)
    yield f"http://127.0.0.1:{port}/mcp"
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture(scope="module")
def token_url():
    port = free_port()
    proc = start_server([TOKEN_SERVER, str(port)], port)
    yield f"http://127.0.0.1:{port}/mcp"
    proc.terminate()
    proc.wait(timeout=10)


def test_call_over_http(http_url):
    async def go():
        async with McpServer(ServerConfig(url=http_url)) as server:
            tools = await server.list_tools()
            result = await server.call("get_weather", {"city": "Vancouver"}, timeout_s=10)
            return tools, result

    tools, result = anyio.run(go)
    assert "get_weather" in [t.name for t in tools]
    assert not result.is_error
    assert result.data["city"] == "Vancouver"


def test_headers_are_sent(token_url):
    async def go():
        config = ServerConfig(url=token_url, headers={"Authorization": "Bearer secret"})
        async with McpServer(config) as server:
            return await server.call("whoami", timeout_s=10)

    result = anyio.run(go)
    assert result.text == "authenticated"


def test_missing_header_is_a_connection_error(token_url):
    async def go():
        async with McpServer(ServerConfig(url=token_url, startup_timeout_s=10)):
            pass

    with pytest.raises(ServerError, match="could not connect"):
        anyio.run(go)
