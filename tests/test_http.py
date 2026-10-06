"""Connect over streamable HTTP instead of stdio."""

import socket
import subprocess
import sys
import time

import anyio
import pytest

from tests.conftest import WEATHER
from toolproof.client import McpServer
from toolproof.config import ServerConfig


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def http_url():
    port = free_port()
    proc = subprocess.Popen(
        [sys.executable, WEATHER, "--http", "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
                break
            except OSError:
                time.sleep(0.2)
        else:
            pytest.fail("HTTP server did not start")
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
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
