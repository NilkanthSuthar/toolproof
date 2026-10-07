"""HTTP MCP server that rejects requests without `Authorization: Bearer secret`.

Used to check that `headers:` in the server config reaches the server.
Usage: python token_server.py PORT
"""

import sys

import uvicorn
from mcp.server.mcpserver import MCPServer

mcp = MCPServer("token-check")


@mcp.tool()
def whoami() -> str:
    """Say hello to an authenticated caller."""
    return "authenticated"


app = mcp.streamable_http_app()


async def require_token(scope, receive, send):  # type: ignore[no-untyped-def]
    if scope["type"] == "http":
        headers = dict(scope.get("headers") or [])
        if headers.get(b"authorization") != b"Bearer secret":
            await send({"type": "http.response.start", "status": 401, "headers": []})
            await send({"type": "http.response.body", "body": b"unauthorized"})
            return
    await app(scope, receive, send)


if __name__ == "__main__":
    uvicorn.run(require_token, host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
