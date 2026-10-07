"""Command line interface: inspect, run, fuzz and bench."""

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
from toolproof.config import (
    BenchConfig,
    BenchTarget,
    Config,
    ConfigError,
    FuzzConfig,
    ServerConfig,
    load_config,
)
from toolproof.reporters import print_report, write_json, write_junit
from toolproof.runner import RunReport, default_phases, run_config

app = typer.Typer(
    help="Automated tests for MCP servers.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()
err_console = Console(stderr=True)

DEFAULT_CONFIG = Path("toolproof.yaml")

# Options shared by several commands.
CommandArg = Annotated[
    list[str] | None,
    typer.Argument(help="Server command to run over stdio, after `--`."),
]
UrlOpt = Annotated[str | None, typer.Option(help="Streamable HTTP URL of the server.")]
ConfigOpt = Annotated[
    Path | None,
    typer.Option("--config", "-c", help="Read the server and settings from a toolproof.yaml."),
]
JunitOpt = Annotated[Path | None, typer.Option(help="Write a JUnit XML report to this path.")]
JsonOpt = Annotated[Path | None, typer.Option("--json", help="Write a JSON report to this path.")]


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
    command: CommandArg = None,
    url: UrlOpt = None,
    config_path: ConfigOpt = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")] = False,
) -> None:
    """List a server's tools, resources and prompts, and run the static checks.

    Examples:

        toolproof inspect -- python server.py

        toolproof inspect --url http://localhost:8000/mcp
    """
    config = _config_from_args(command, url, config_path)

    async def fetch() -> ServerInfo:
        async with McpServer(config.server, base_dir=config.base_dir) as server:
            return await server.server_info()

    try:
        info = anyio.run(fetch)
    except ServerError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from exc

    problems = run_checks(info.tools, config.checks)
    if as_json:
        print(json.dumps(_info_to_dict(info, problems), indent=2))
    else:
        _print_info(info, problems)


@app.command()
def run(
    config_path: Annotated[
        Path, typer.Argument(metavar="CONFIG", help="Path to the test file.")
    ] = DEFAULT_CONFIG,
    junit: JunitOpt = None,
    json_out: JsonOpt = None,
    timeout_ms: Annotated[
        float | None, typer.Option(help="Default per-test timeout in milliseconds.")
    ] = None,
    retries: Annotated[
        int | None, typer.Option(help="Retry failing tests this many times.")
    ] = None,
    strict: Annotated[bool, typer.Option(help="Treat static check warnings as failures.")] = False,
    checks: Annotated[bool, typer.Option(help="Run the static checks.")] = True,
    skip_bench: Annotated[bool, typer.Option(help="Skip the bench section.")] = False,
    skip_fuzz: Annotated[bool, typer.Option(help="Skip the fuzz section.")] = False,
) -> None:
    """Run everything in CONFIG: static checks, tests, and bench/fuzz if configured.

    Exits 1 if anything fails.
    """
    config = _load(config_path)
    if timeout_ms is not None:
        config.timeout_ms = timeout_ms
    if retries is not None:
        config.retries = retries
    if strict:
        config.checks.strict = True
    if not checks:
        config.checks.enabled = False

    phases = default_phases(config)
    if skip_bench and "bench" in phases:
        phases.remove("bench")
    if skip_fuzz and "fuzz" in phases:
        phases.remove("fuzz")
    _finish(run_config(config, phases), junit, json_out)


@app.command()
def fuzz(
    command: CommandArg = None,
    url: UrlOpt = None,
    config_path: ConfigOpt = None,
    examples: Annotated[
        int | None, typer.Option(help="Inputs per tool, for valid and for invalid inputs.")
    ] = None,
    timeout_ms: Annotated[float | None, typer.Option(help="Timeout per call.")] = None,
    max_time: Annotated[float | None, typer.Option(help="Time limit per tool in seconds.")] = None,
    seed: Annotated[int | None, typer.Option(help="Random seed, to repeat a run.")] = None,
    tool: Annotated[
        list[str] | None, typer.Option(help="Only fuzz this tool. Can be repeated.")
    ] = None,
    include_destructive: Annotated[
        bool, typer.Option(help="Also fuzz tools marked destructive.")
    ] = False,
    valid_must_succeed: Annotated[
        bool, typer.Option(help="Count error results for valid inputs as failures.")
    ] = False,
    junit: JunitOpt = None,
    json_out: JsonOpt = None,
) -> None:
    """Call every tool with generated inputs and report crashes, hangs and bad errors.

    Examples:

        toolproof fuzz -- python server.py

        toolproof fuzz -c toolproof.yaml --examples 200 --seed 42
    """
    config = _config_from_args(command, url, config_path)
    fz = config.fuzz or FuzzConfig()
    if examples is not None:
        fz.max_examples = examples
    if timeout_ms is not None:
        fz.timeout_ms = timeout_ms
    if max_time is not None:
        fz.max_time_s = max_time
    if seed is not None:
        fz.seed = seed
    if tool:
        fz.tools = tool
    if include_destructive:
        fz.include_destructive = True
    if valid_must_succeed:
        fz.valid_must_succeed = True
    config.fuzz = fz
    _finish(run_config(config, ["fuzz"]), junit, json_out)


@app.command()
def bench(
    command: CommandArg = None,
    url: UrlOpt = None,
    config_path: ConfigOpt = None,
    tool: Annotated[str | None, typer.Option(help="Benchmark just this tool.")] = None,
    args: Annotated[str | None, typer.Option(help="Arguments for --tool as a JSON object.")] = None,
    calls: Annotated[int | None, typer.Option(help="Calls per target.")] = None,
    concurrency: Annotated[int | None, typer.Option(help="Calls in flight at once.")] = None,
    timeout_ms: Annotated[float | None, typer.Option(help="Timeout per call.")] = None,
    p50_ms: Annotated[float | None, typer.Option(help="Fail if p50 is above this.")] = None,
    p95_ms: Annotated[float | None, typer.Option(help="Fail if p95 is above this.")] = None,
    p99_ms: Annotated[float | None, typer.Option(help="Fail if p99 is above this.")] = None,
    max_error_rate: Annotated[
        float | None, typer.Option(help="Fail if the error rate is above this (0.01 = 1%).")
    ] = None,
    min_throughput: Annotated[
        float | None, typer.Option(help="Fail if calls per second is below this.")
    ] = None,
    junit: JunitOpt = None,
    json_out: JsonOpt = None,
) -> None:
    """Measure latency (p50/p95/p99), throughput and error rate.

    Without --tool, benchmarks the bench targets in the config, or every test
    case that expects success.

    Examples:

        toolproof bench -c toolproof.yaml --calls 500 --concurrency 20

        toolproof bench --tool get_weather --args '{"city": "Toronto"}' -- python server.py
    """
    config = _config_from_args(command, url, config_path)
    bc = config.bench or BenchConfig()
    if tool:
        try:
            parsed = json.loads(args) if args else {}
        except json.JSONDecodeError as exc:
            err_console.print(f"[red]--args is not valid JSON: {exc}[/red]")
            raise typer.Exit(2) from exc
        bc.targets = [BenchTarget(tool=tool, args=parsed)]
    if calls is not None:
        bc.calls = calls
    if concurrency is not None:
        bc.concurrency = concurrency
    if timeout_ms is not None:
        bc.timeout_ms = timeout_ms
    overrides = {
        "p50_ms": p50_ms,
        "p95_ms": p95_ms,
        "p99_ms": p99_ms,
        "max_error_rate": max_error_rate,
        "min_throughput": min_throughput,
    }
    for name, value in overrides.items():
        if value is not None:
            setattr(bc.thresholds, name, value)
    if not bc.targets and not any(t.expect.is_error is not True for t in config.tests):
        err_console.print(
            "[red]Nothing to benchmark. Pass --tool, or add tests or bench targets.[/red]"
        )
        raise typer.Exit(2)
    config.bench = bc
    _finish(run_config(config, ["bench"]), junit, json_out)


def _finish(report: RunReport, junit: Path | None, json_out: Path | None) -> None:
    """Print the report, write report files and exit with the right code."""
    print_report(report, console)
    if junit:
        write_junit(report, junit)
        console.print(f"JUnit report written to {junit}")
    if json_out:
        write_json(report, json_out)
        console.print(f"JSON report written to {json_out}")
    raise typer.Exit(0 if report.passed else 1)


def _load(path: Path) -> Config:
    try:
        return load_config(path)
    except ConfigError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from exc


def _config_from_args(
    command: list[str] | None, url: str | None, config_path: Path | None
) -> Config:
    """Build a config from `-- command`, `--url` or a YAML file.

    With none of them, falls back to ./toolproof.yaml if it exists.
    """
    given = sum(1 for x in (command, url, config_path) if x)
    if given > 1:
        err_console.print("[red]Give only one of: a command after `--`, --url, --config.[/red]")
        raise typer.Exit(2)
    if config_path is not None:
        return _load(config_path)
    if url:
        return Config(server=ServerConfig(url=url))
    if command:
        return Config(server=ServerConfig(command=command))
    if DEFAULT_CONFIG.exists():
        return _load(DEFAULT_CONFIG)
    err_console.print(
        "[red]Give a server command after `--`, or --url, or --config.[/red]\n"
        "Example: toolproof inspect -- python server.py"
    )
    raise typer.Exit(2)


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
