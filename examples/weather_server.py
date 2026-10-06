"""A small, well-behaved MCP server used in the toolproof examples and tests.

The weather data is made up, so the server works offline and always gives
the same answers.

Run over stdio (default):     python examples/weather_server.py
Run over streamable HTTP:     python examples/weather_server.py --http --port 8000
"""

import argparse

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel

CITIES = {
    "toronto": {"temp_c": 12.5, "conditions": "cloudy"},
    "montreal": {"temp_c": 9.0, "conditions": "rain"},
    "vancouver": {"temp_c": 14.0, "conditions": "rain"},
    "calgary": {"temp_c": 6.5, "conditions": "sunny"},
}

mcp = MCPServer("weather", version="1.0.0")

# Tools raise ToolError for bad input. The server sends its message back as an
# error result. Any other exception is treated as a crash and the message is hidden.


class Weather(BaseModel):
    city: str
    temp_c: float
    conditions: str


class Forecast(BaseModel):
    city: str
    days: list[Weather]


def _lookup(city: str) -> dict[str, object]:
    city = city.strip()
    if not city:
        raise ToolError("city must not be empty")
    data = CITIES.get(city.lower())
    if data is None:
        raise ToolError(f"unknown city: {city}")
    return data


@mcp.tool()
def get_weather(city: str) -> Weather:
    """Get the current weather for a city."""
    data = _lookup(city)
    return Weather(city=city.strip().title(), **data)  # type: ignore[arg-type]


@mcp.tool()
def get_forecast(city: str, days: int = 3) -> Forecast:
    """Get a simple daily forecast for a city, 1 to 7 days."""
    if not 1 <= days <= 7:
        raise ToolError("days must be between 1 and 7")
    data = _lookup(city)
    name = city.strip().title()
    base = float(data["temp_c"])  # type: ignore[arg-type]
    return Forecast(
        city=name,
        days=[
            Weather(city=name, temp_c=base + i, conditions=str(data["conditions"]))
            for i in range(days)
        ],
    )


@mcp.tool()
def list_cities() -> list[str]:
    """List the cities this server knows about."""
    return sorted(c.title() for c in CITIES)


@mcp.resource("weather://cities")
def cities_resource() -> str:
    """All supported cities, one per line."""
    return "\n".join(sorted(c.title() for c in CITIES))


@mcp.prompt()
def weather_report(city: str) -> str:
    """Ask for a short weather report for a city."""
    return f"Write a two-sentence weather report for {city}."


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--http", action="store_true", help="serve over streamable HTTP")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if args.http:
        mcp.run("streamable-http", port=args.port)
    else:
        mcp.run()
