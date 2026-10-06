"""An MCP server with deliberate bugs, so toolproof has something to catch.

Planted bugs:
  1. get_weather crashes the whole process when `city` is empty.
  2. search_cities has a broken input schema ("strng" is not a JSON Schema type)
     and no description.
  3. slow_report takes 3 seconds to answer.
  4. get_temperature declares an outputSchema with a numeric temp_c
     but returns it as a string.
  5. lookup requires a field that isn't in its properties.

It uses the low-level server API because the high-level one generates
correct schemas for you, which makes bugs 2, 4 and 5 hard to write.
"""

import os

import anyio
import mcp_types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

TOOLS = [
    types.Tool(
        name="get_weather",
        description="Get the current weather for a city.",
        input_schema={
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    ),
    types.Tool(
        name="search_cities",
        description="",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "strng"}},
            "required": ["query"],
        },
    ),
    types.Tool(
        name="slow_report",
        description="Build a weather report. Takes a while.",
        input_schema={
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    ),
    types.Tool(
        name="get_temperature",
        description="Get the temperature for a city in Celsius.",
        input_schema={
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
        output_schema={
            "type": "object",
            "properties": {"city": {"type": "string"}, "temp_c": {"type": "number"}},
            "required": ["city", "temp_c"],
        },
    ),
    types.Tool(
        name="lookup",
        description="Look up a city by id.",
        input_schema={
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["city_id"],
        },
    ),
]


def text(value: str, is_error: bool = False) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(text=value)], is_error=is_error)


async def list_tools(ctx, params) -> types.ListToolsResult:  # type: ignore[no-untyped-def]
    return types.ListToolsResult(tools=TOOLS)


async def call_tool(ctx, params: types.CallToolRequestParams) -> types.CallToolResult:  # type: ignore[no-untyped-def]
    args = params.arguments or {}
    city = str(args.get("city", ""))

    if params.name == "get_weather":
        if city == "":
            os._exit(1)  # bug 1: a crash instead of an error result
        return text(f"{city}: 12C, cloudy")

    if params.name == "search_cities":
        query = str(args.get("query", "")).lower()
        return text(", ".join(c for c in ["Toronto", "Montreal"] if query in c.lower()))

    if params.name == "slow_report":
        await anyio.sleep(3)  # bug 3: too slow
        return text(f"Report for {city}: mild.")

    if params.name == "get_temperature":
        result = {"city": city, "temp_c": "12.5"}  # bug 4: string instead of number
        return types.CallToolResult(
            content=[types.TextContent(text=str(result))], structured_content=result
        )

    if params.name == "lookup":
        return text("not found", is_error=True)

    return text(f"unknown tool: {params.name}", is_error=True)


server = Server("buggy-weather", version="0.0.1", on_list_tools=list_tools, on_call_tool=call_tool)


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    anyio.run(main)
