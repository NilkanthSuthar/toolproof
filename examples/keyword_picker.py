"""A stand-in "model" for the eval examples: picks a tool by keywords.

toolproof's `command` eval provider runs a program like this one. It reads
a JSON request on stdin:

    {"model": "...", "system": "...", "prompt": "...",
     "tools": [{"name": ..., "description": ..., "input_schema": ...}]}

and prints the choice on stdout:

    {"tool": "get_weather", "args": {"city": "Montreal"}}

Use `"tool": null` for "no tool". A real setup would call a model here;
this one is deterministic so the examples and tests run offline.
"""

import json
import re
import sys

CITIES = ["Toronto", "Montreal", "Vancouver", "Calgary"]


def pick(prompt: str, tools: set[str]) -> dict[str, object]:
    text = prompt.lower()
    city = next((c for c in CITIES if c.lower() in text), None)
    if "cities" in text and "list_cities" in tools:
        return {"tool": "list_cities", "args": {}}
    if city and "forecast" in text and "get_forecast" in tools:
        days = re.search(r"(\d+)\s*day", text)
        args: dict[str, object] = {"city": city}
        if days:
            args["days"] = int(days.group(1))
        return {"tool": "get_forecast", "args": args}
    if city and "get_weather" in tools:
        return {"tool": "get_weather", "args": {"city": city}}
    return {"tool": None, "args": {}}


if __name__ == "__main__":
    request = json.load(sys.stdin)
    names = {t["name"] for t in request["tools"]}
    json.dump(pick(request["prompt"], names), sys.stdout)
