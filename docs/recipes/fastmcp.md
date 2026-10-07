# Testing a FastMCP server

Servers built with the official Python SDK's high-level API (`MCPServer`, formerly `FastMCP`) generate input and output schemas from type hints, so toolproof has a lot to work with.

## The server

```python title="server.py"
from pydantic import BaseModel

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

mcp = MCPServer("weather")


class Weather(BaseModel):
    city: str
    temp_c: float


@mcp.tool()
def get_weather(city: str) -> Weather:
    """Get the current weather for a city."""
    if not city.strip():
        raise ToolError("city must not be empty")
    return Weather(city=city.title(), temp_c=12.5)


if __name__ == "__main__":
    mcp.run()
```

Because `get_weather` returns a pydantic model, the tool declares an `outputSchema` and returns structured content. toolproof validates every successful result against that schema automatically.

!!! tip "Raise `ToolError` for expected failures"
    The SDK sends a `ToolError`'s message back to the client. Any other exception is treated as a crash in the tool, and the client only sees `Error executing tool get_weather`. toolproof's fuzzer reports that generic message as `unhandled-exception`, so raising `ToolError` for bad input keeps fuzz runs clean and gives clients a useful message.

## The tests

```yaml title="toolproof.yaml"
server:
  command: ["python", "server.py"]

tests:
  - name: toronto
    tool: get_weather
    args: { city: toronto }
    expect:
      jsonpath:
        "$.city": { equals: Toronto }
        "$.temp_c": { type: number }

  - name: empty city is an error with a clear message
    tool: get_weather
    args: { city: " " }
    expect: { is_error: true, contains: "must not be empty" }

fuzz:
  seed: 1
```

```bash
toolproof run toolproof.yaml
```

## Run toolproof from the server's environment

Install toolproof in the same virtual environment as the server, so `python` in `command` can import the server's dependencies:

```bash
pip install -e . mcp-toolproof
toolproof run toolproof.yaml
```

With [uv](https://docs.astral.sh/uv/):

```yaml
server:
  command: ["uv", "run", "server.py"]
```
