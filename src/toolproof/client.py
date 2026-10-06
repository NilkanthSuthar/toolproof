"""A thin wrapper around the MCP SDK client.

It hides transport setup (stdio or streamable HTTP), times every tool call,
and turns the SDK's result objects into a simple `CallResult` that the
assertions can work with.
"""

from __future__ import annotations

import contextlib
import json
import tempfile
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import Any, TextIO, cast

import anyio
import mcp_types as types
from mcp import Client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.shared.exceptions import MCPError

from toolproof.config import ServerConfig


class ServerError(Exception):
    """Raised when the server can't be reached or the connection breaks."""


@dataclass
class CallResult:
    """The outcome of one tool call, flattened for easy assertions."""

    tool: str
    arguments: dict[str, Any]
    is_error: bool
    text: str
    structured: Any
    latency_ms: float
    transport_error: str | None = None
    timed_out: bool = False
    protocol_error: bool = False

    @property
    def data(self) -> Any:
        """Structured content if the server sent any, otherwise the text parsed as JSON.

        Returns None when the text isn't valid JSON.
        """
        if self.structured is not None:
            return self.structured
        try:
            return json.loads(self.text)
        except (ValueError, TypeError):
            return None


@dataclass
class ServerInfo:
    """Everything `inspect` shows about a server."""

    name: str | None
    version: str | None
    tools: list[types.Tool] = field(default_factory=list)
    resources: list[types.Resource] = field(default_factory=list)
    prompts: list[types.Prompt] = field(default_factory=list)


def _content_to_text(blocks: list[types.ContentBlock]) -> str:
    """Join the text parts of a tool result. Non-text blocks are shown as a placeholder."""
    parts = []
    for block in blocks:
        if isinstance(block, types.TextContent):
            parts.append(block.text)
        else:
            parts.append(f"<{block.type}>")
    return "\n".join(parts)


class McpServer:
    """An open connection to one MCP server.

    Use it as an async context manager:

        async with McpServer(config) as server:
            tools = await server.list_tools()
            result = await server.call("get_weather", {"city": "Toronto"})
    """

    def __init__(self, config: ServerConfig, base_dir: Path | None = None) -> None:
        self.config = config
        self.base_dir = base_dir or Path.cwd()
        self._stack: AsyncExitStack | None = None
        self._client: Client | None = None
        self._stderr: TextIO | None = None

    async def __aenter__(self) -> McpServer:
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()

    async def connect(self) -> None:
        """Start the server (for stdio) and run the MCP handshake."""
        self._stack = AsyncExitStack()
        # Used for the handshake and listing calls. Tool calls pass their own timeout.
        timeout = self.config.startup_timeout_s
        try:
            if self.config.url:
                client = Client(self.config.url, cache=None, read_timeout_seconds=timeout)
            else:
                # Server logs go to a temp file so they don't clutter our output.
                # We show the tail of it if the server dies.
                log_file = tempfile.TemporaryFile("w+", encoding="utf-8", errors="replace")  # noqa: SIM115
                self._stderr = cast(TextIO, self._stack.enter_context(log_file))
                command = self.config.command or []
                params = StdioServerParameters(
                    command=command[0],
                    args=command[1:],
                    env=self.config.env or None,
                    cwd=self._resolve_cwd(),
                )
                client = Client(
                    stdio_client(params, errlog=self._stderr),
                    cache=None,
                    read_timeout_seconds=timeout,
                )
            self._client = await self._stack.enter_async_context(client)
            # The SDK raises RuntimeError when structured output doesn't match the
            # tool's outputSchema. We check that ourselves and report it as a test
            # failure (with the actual output), so switch the SDK check off.
            self._client.session.validate_tool_result = _skip_validation  # type: ignore[method-assign]
        except Exception as exc:
            stderr = self.stderr_tail()
            await self.close()
            message = f"could not connect to server: {_describe(exc)}"
            if stderr:
                message += f"\nserver stderr:\n{stderr}"
            raise ServerError(message) from exc

    async def close(self) -> None:
        """Close the connection and stop the server process."""
        stack, self._stack, self._client = self._stack, None, None
        if stack is not None:
            # The server may already be dead; nothing useful to do if closing fails.
            with contextlib.suppress(Exception):
                await stack.aclose()

    async def reconnect(self) -> None:
        """Restart the connection, e.g. after the server crashed."""
        await self.close()
        await self.connect()

    @property
    def client(self) -> Client:
        if self._client is None:
            raise ServerError("not connected")
        return self._client

    def _resolve_cwd(self) -> Path:
        if self.config.cwd:
            return (self.base_dir / self.config.cwd).resolve()
        return self.base_dir

    def stderr_tail(self, lines: int = 20) -> str:
        """Return the last few lines the server wrote to stderr (stdio only)."""
        if self._stderr is None or self._stderr.closed:
            return ""
        self._stderr.flush()
        self._stderr.seek(0)
        text = self._stderr.read()
        self._stderr.seek(0, 2)
        return "\n".join(text.strip().splitlines()[-lines:])

    async def server_info(self) -> ServerInfo:
        """List tools, resources and prompts. Missing capabilities give empty lists."""
        client = self.client
        info = client.server_info
        caps = client.server_capabilities
        result = ServerInfo(
            name=info.name if info else None,
            version=info.version if info else None,
        )
        if caps.tools is not None:
            result.tools = await self.list_tools()
        if caps.resources is not None:
            result.resources = (await client.list_resources()).resources
        if caps.prompts is not None:
            result.prompts = (await client.list_prompts()).prompts
        return result

    async def list_tools(self) -> list[types.Tool]:
        """Return every tool, following pagination cursors."""
        tools: list[types.Tool] = []
        cursor: str | None = None
        while True:
            page = await self.client.list_tools(cursor=cursor)
            tools.extend(page.tools)
            cursor = page.next_cursor
            if not cursor:
                return tools

    async def call(
        self,
        tool: str,
        arguments: dict[str, Any] | None = None,
        timeout_s: float | None = None,
    ) -> CallResult:
        """Call a tool and time it.

        This never raises for tool errors, timeouts or a dead server. Those are
        reported on the returned `CallResult` so a test can assert on them.
        """
        arguments = arguments or {}
        start = time.perf_counter()
        try:
            with anyio.fail_after(timeout_s):
                result = await self.client.call_tool(tool, arguments)
        except TimeoutError:
            failed = self._failed(
                tool, arguments, _ms_since(start), f"timed out after {timeout_s}s"
            )
            failed.timed_out = True
            return failed
        except MCPError as exc:
            latency = _ms_since(start)
            if await self.is_alive():
                # The server answered with a JSON-RPC error instead of a tool result.
                # That's still an error response, not a crash.
                return CallResult(
                    tool=tool,
                    arguments=arguments,
                    is_error=True,
                    text=exc.error.message,
                    structured=None,
                    latency_ms=latency,
                    protocol_error=True,
                )
            return self._failed(tool, arguments, latency, f"connection lost: {exc.error.message}")
        except Exception as exc:
            return self._failed(tool, arguments, _ms_since(start), _describe(exc))
        return CallResult(
            tool=tool,
            arguments=arguments,
            is_error=result.is_error,
            text=_content_to_text(result.content),
            structured=result.structured_content,
            latency_ms=_ms_since(start),
        )

    async def is_alive(self, timeout_s: float = 5) -> bool:
        """Check the server still answers, e.g. after a failed call.

        Uses tools/list rather than ping, because ping is gone in newer protocol versions.
        """
        try:
            with anyio.fail_after(timeout_s):
                await self.client.list_tools()
        except Exception:
            return False
        return True

    @staticmethod
    def _failed(tool: str, arguments: dict[str, Any], latency_ms: float, error: str) -> CallResult:
        return CallResult(
            tool=tool,
            arguments=arguments,
            is_error=True,
            text="",
            structured=None,
            latency_ms=latency_ms,
            transport_error=error,
        )


async def _skip_validation(name: str, result: types.CallToolResult) -> None:
    return None


def _describe(exc: BaseException) -> str:
    """A short message for an exception, unwrapping the task-group wrappers anyio adds."""
    while isinstance(exc, BaseExceptionGroup) and len(exc.exceptions) == 1:
        exc = exc.exceptions[0]
    if isinstance(exc, MCPError):
        return exc.error.message
    return str(exc) or exc.__class__.__name__


def _ms_since(start: float) -> float:
    return (time.perf_counter() - start) * 1000
