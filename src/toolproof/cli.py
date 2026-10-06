"""Command line interface: `toolproof inspect` and `toolproof run`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import anyio
import typer
from rich.console import Console
from rich.table import Table

from toolproof import __version__
from toolproof.checks import CheckResult, run_checks
from toolproof.client import McpServer, ServerError, ServerInfo
from toolproof.config import ChecksConfig, ConfigError, ServerConfig, load_config
from toolproof.reporters import print_report, write_json, write_junit
from toolproof.runner import run_config

app = typer.Typer(
    help="Automated tests for MCP servers.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()
err_console = Console(stderr=True)


def _version(value: bool) -> None:
    if value:
        console.print(f"toolproof {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool | None,
        typer.Option("--version", callback=_version, is_eager=True, help="Show version."),
    ] = None,
) -> None:
    """Automated tests for MCP servers."""


@app.command()
def inspect(
    command: Annotated[
        list[str] | None,
        typer.Argument(help="Server command to run over stdio, after `--`."),
    ] = None,
    url: Annotated[str | None, typer.Option(help="Streamable HTTP URL of the server.")] = None,
    config: Annotated[
        Path | None,
        typer.Option("--config", "-c", help="Read the server from a toolproof.yaml file."),
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """List a server's tools, resources and prompts, and run the static checks.

    Examples:

        toolproof inspect -- python server.py

        toolproof inspect --url http://localhost:8000/mcp
    """
    server_config, base_dir, checks_config = _server_from_args(command, url, config)

    async def fetch() -> ServerInfo:
        async with McpServer(server_config, base_dir=base_dir) as server:
            return await server.server_info()

    try:
        info = anyio.run(fetch)
    except ServerError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from exc

    problems = run_checks(info.tools, checks_config)
    if as_json:
        print(json.dumps(_info_to_dict(info, problems), indent=2))
    else:
        _print_info(info, problems)


@app.command()
def run(
    config_path: Annotated[
        Path, typer.Argument(metavar="CONFIG", help="Path to the test file.")
    ] = Path("toolproof.yaml"),
    junit: Annotated[
        Path | None, typer.Option(help="Write a JUnit XML report to this path.")
    ] = None,
    json_out: Annotated[
        Path | None, typer.Option("--json", help="Write a JSON report to this path.")
    ] = None,
    timeout_ms: Annotated[
        float | None, typer.Option(help="Default per-test timeout in milliseconds.")
    ] = None,
    retries: Annotated[
        int | None, typer.Option(help="Retry failing tests this many times.")
    ] = None,
    strict: Annotated[bool, typer.Option(help="Treat static check warnings as failures.")] = False,
    checks: Annotated[bool, typer.Option(help="Run the static checks.")] = True,
) -> None:
    """Run static checks and the test cases in CONFIG. Exits 1 if anything fails."""
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from exc

    if timeout_ms is not None:
        config.timeout_ms = timeout_ms
    if retries is not None:
        config.retries = retries
    if strict:
        config.checks.strict = True
    if not checks:
        config.checks.enabled = False

    report = run_config(config)
    print_report(report, console)

    if junit:
        write_junit(report, junit)
        console.print(f"JUnit report written to {junit}")
    if json_out:
        write_json(report, json_out)
        console.print(f"JSON report written to {json_out}")

    raise typer.Exit(0 if report.passed else 1)


def _server_from_args(
    command: list[str] | None, url: str | None, config_path: Path | None
) -> tuple[ServerConfig, Path, ChecksConfig]:
    """Work out which server `inspect` should talk to."""
    if config_path is not None:
        try:
            config = load_config(config_path)
        except ConfigError as exc:
            err_console.print(f"[red]{exc}[/red]")
            raise typer.Exit(2) from exc
        return config.server, config.base_dir, config.checks
    if bool(command) == bool(url):
        err_console.print(
            "[red]Give a server command after `--`, or --url, or --config.[/red]\n"
            "Example: toolproof inspect -- python server.py"
        )
        raise typer.Exit(2)
    if url:
        return ServerConfig(url=url), Path.cwd(), ChecksConfig()
    return ServerConfig(command=command), Path.cwd(), ChecksConfig()


def _print_info(info: ServerInfo, problems: list[CheckResult]) -> None:
    title = info.name or "MCP server"
    if info.version:
        title += f" {info.version}"
    console.print(f"[bold]{title}[/bold]\n")

    tools = Table(title=f"Tools ({len(info.tools)})", title_justify="left")
    tools.add_column("Name", style="cyan")
    tools.add_column("Description")
    tools.add_column("Arguments")
    for tool in info.tools:
        tools.add_row(tool.name, tool.description or "", _describe_args(tool.input_schema))
    console.print(tools)

    if info.resources:
        resources = Table(title=f"Resources ({len(info.resources)})", title_justify="left")
        resources.add_column("URI", style="cyan")
        resources.add_column("Name")
        resources.add_column("Description")
        for res in info.resources:
            resources.add_row(str(res.uri), res.name, res.description or "")
        console.print(resources)

    if info.prompts:
        prompts = Table(title=f"Prompts ({len(info.prompts)})", title_justify="left")
        prompts.add_column("Name", style="cyan")
        prompts.add_column("Description")
        prompts.add_column("Arguments")
        for prompt in info.prompts:
            args = ", ".join(a.name + ("" if a.required else "?") for a in (prompt.arguments or []))
            prompts.add_row(prompt.name, prompt.description or "", args)
        console.print(prompts)

    console.print()
    if not problems:
        console.print("[green]Static checks: no problems found[/green]")
        return
    console.print("[bold]Static checks[/bold]")
    for p in problems:
        color = "red" if p.severity == "error" else "yellow"
        console.print(f"  [{color}]{p.severity.upper()}[/{color}] {p.tool}: {p.message}")


def _describe_args(schema: dict[str, Any]) -> str:
    """Render an input schema as `city: string, days?: integer`."""
    properties = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    parts = []
    for name, prop in properties.items():
        kind = prop.get("type", "any") if isinstance(prop, dict) else "any"
        if isinstance(kind, list):
            kind = " | ".join(kind)
        parts.append(f"{name}{'' if name in required else '?'}: {kind}")
    return ", ".join(parts)


def _info_to_dict(info: ServerInfo, problems: list[CheckResult]) -> dict[str, Any]:
    def dump(items: list[Any]) -> list[Any]:
        return [i.model_dump(mode="json", by_alias=True, exclude_none=True) for i in items]

    return {
        "server": {"name": info.name, "version": info.version},
        "tools": dump(info.tools),
        "resources": dump(info.resources),
        "prompts": dump(info.prompts),
        "checks": [
            {"tool": p.tool, "check": p.check, "severity": p.severity, "message": p.message}
            for p in problems
        ],
    }
