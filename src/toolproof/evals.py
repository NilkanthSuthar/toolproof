"""Tool-selection evals: does a model pick the right tool for a prompt?

For each eval case we send the prompt and the server's tool list to a model,
read back which tool it chose and with which arguments, and compare that with
what the case expects. No tool is actually called.

Providers:

- ``anthropic``: the Anthropic Messages API (``pip install "mcp-toolproof[anthropic]"``)
- ``openai``: the OpenAI Chat Completions API, or any compatible API through
  ``OPENAI_BASE_URL`` (``pip install "mcp-toolproof[openai]"``)
- ``command``: your own program, which reads a JSON request on stdin and
  writes ``{"tool": ..., "args": {...}}`` on stdout

Responses are cached on disk, keyed by everything that affects the answer, so
re-runs are free and give the same result. ``--no-cache`` asks again.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import anyio
import anyio.to_thread
import mcp_types as types
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from toolproof.config import EvalCase, EvalConfig

CACHE_VERSION = 1

# Characters both providers accept in tool names. MCP allows more (dots,
# slashes), so names are mapped to safe ones and back.
_SAFE_NAME = re.compile(r"[^A-Za-z0-9_-]")


class EvalError(Exception):
    """A problem that stops the whole eval run, such as a missing API key or SDK."""


@dataclass
class Choice:
    """What the model did with a prompt."""

    tool: str | None
    args: dict[str, Any] = field(default_factory=dict)
    text: str = ""


@dataclass
class EvalCaseResult:
    """The outcome of one eval case."""

    name: str
    prompt: str
    expect_tool: str | None
    expect_args: dict[str, Any]
    picked_tool: str | None = None
    picked_args: dict[str, Any] = field(default_factory=dict)
    text: str = ""
    failures: list[str] = field(default_factory=list)
    cached: bool = False

    @property
    def passed(self) -> bool:
        return not self.failures


@dataclass
class EvalReport:
    """All eval results for one run."""

    provider: str
    model: str
    min_accuracy: float
    cases: list[EvalCaseResult] = field(default_factory=list)
    error: str | None = None
    skipped_tools: list[str] = field(default_factory=list)  # left out: invalid input schema

    @property
    def correct(self) -> int:
        return sum(1 for c in self.cases if c.passed)

    @property
    def accuracy(self) -> float:
        return self.correct / len(self.cases) if self.cases else 0.0

    @property
    def passed(self) -> bool:
        return self.error is None and bool(self.cases) and self.accuracy >= self.min_accuracy


# ---------- providers ----------


def _api_tools(tools: list[types.Tool]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Tool definitions with API-safe names, and a map from safe name back to MCP name."""
    defs: list[dict[str, Any]] = []
    back: dict[str, str] = {}
    for tool in tools:
        safe = _SAFE_NAME.sub("_", tool.name)[:64] or "tool"
        while safe in back:  # two names that sanitize to the same string
            safe = (safe[:60] + "_" + str(len(back)))[:64]
        back[safe] = tool.name
        defs.append(
            {
                "name": safe,
                "description": tool.description or "",
                "input_schema": tool.input_schema,
            }
        )
    return defs, back


def _ask_anthropic(
    model: str, system: str | None, prompt: str, tools: list[dict[str, Any]], params: dict[str, Any]
) -> Choice:
    try:
        import anthropic
    except ImportError as exc:
        raise EvalError(
            'the anthropic provider needs the SDK: pip install "mcp-toolproof[anthropic]"'
        ) from exc

    request: dict[str, Any] = {
        "model": model,
        # Leave room for thinking, which is on by default on current models.
        "max_tokens": 16000,
        "messages": [{"role": "user", "content": prompt}],
        "tools": tools,
        "tool_choice": {"type": "auto"},
        **params,
    }
    if system:
        request["system"] = system
    try:
        response = anthropic.Anthropic().messages.create(**request)
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
        raise EvalError(f"anthropic: {exc}") from exc
    except anthropic.NotFoundError as exc:
        raise EvalError(f"anthropic: unknown model {model!r}: {exc}") from exc
    except anthropic.BadRequestError as exc:
        # The request itself is wrong (a bad `params` value, a schema the API
        # won't accept), so every case would fail the same way.
        raise EvalError(f"anthropic rejected the request: {exc}") from exc

    if response.stop_reason == "refusal":
        return Choice(tool=None, text="(the model declined to answer)")
    text = " ".join(b.text for b in response.content if b.type == "text")
    for block in response.content:
        if block.type == "tool_use":
            return Choice(tool=block.name, args=dict(block.input), text=text)
    return Choice(tool=None, text=text)


def _ask_openai(
    model: str, system: str | None, prompt: str, tools: list[dict[str, Any]], params: dict[str, Any]
) -> Choice:
    try:
        import openai
    except ImportError as exc:
        raise EvalError(
            'the openai provider needs the SDK: pip install "mcp-toolproof[openai]"'
        ) from exc

    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    functions = [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in tools
    ]
    request: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "tools": functions,
        "tool_choice": "auto",
        **params,
    }
    try:
        response = openai.OpenAI().chat.completions.create(**request)
    except (openai.AuthenticationError, openai.PermissionDeniedError) as exc:
        raise EvalError(f"openai: {exc}") from exc
    except openai.NotFoundError as exc:
        raise EvalError(f"openai: unknown model {model!r}: {exc}") from exc
    except (openai.BadRequestError, openai.UnprocessableEntityError) as exc:
        # The request itself is wrong, so every case would fail the same way.
        raise EvalError(f"openai rejected the request: {exc}") from exc

    message = response.choices[0].message
    for call in message.tool_calls or []:
        if call.type == "function":
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {"_unparsed": call.function.arguments}
            return Choice(tool=call.function.name, args=args, text=message.content or "")
    return Choice(tool=None, text=message.content or "")


def _ask_command(
    command: list[str],
    cwd: Path,
    timeout_s: float,
    model: str,
    system: str | None,
    prompt: str,
    tools: list[dict[str, Any]],
) -> Choice:
    request = {"model": model, "system": system, "prompt": prompt, "tools": tools}
    try:
        proc = subprocess.run(
            command,
            input=json.dumps(request),
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=cwd,
            timeout=timeout_s,
            check=False,
        )
    except FileNotFoundError as exc:
        raise EvalError(f"eval command not found: {command[0]}") from exc
    if proc.returncode != 0:
        raise RuntimeError(f"eval command exited {proc.returncode}: {proc.stderr.strip()[-500:]}")
    try:
        answer = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"eval command printed invalid JSON: {proc.stdout[:200]!r}") from exc
    tool = answer.get("tool")
    args = answer.get("args") or {}
    if tool is not None and not isinstance(tool, str):
        raise RuntimeError("eval command: 'tool' must be a string or null")
    if not isinstance(args, dict):
        raise RuntimeError("eval command: 'args' must be an object")
    return Choice(tool=tool, args=args, text=str(answer.get("text", "")))


# ---------- cache ----------


def cache_key(
    provider: str,
    model: str,
    system: str | None,
    prompt: str,
    tools: list[dict[str, Any]],
    params: dict[str, Any],
) -> str:
    """Hash of everything that can change the model's answer."""
    material = {
        "v": CACHE_VERSION,
        "provider": provider,
        "model": model,
        "system": system,
        "prompt": prompt,
        "tools": tools,
        "params": params,
    }
    blob = json.dumps(material, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _cache_path(cache_dir: Path, key: str) -> Path:
    return cache_dir / "evals" / f"{key}.json"


def _read_cache(cache_dir: Path, key: str) -> Choice | None:
    path = _cache_path(cache_dir, key)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Choice(tool=data["tool"], args=data.get("args") or {}, text=data.get("text", ""))
    except (OSError, ValueError, KeyError):
        return None


def _write_cache(cache_dir: Path, key: str, choice: Choice, info: dict[str, Any]) -> None:
    path = _cache_path(cache_dir, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {**info, "tool": choice.tool, "args": choice.args, "text": choice.text}
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# ---------- judging ----------


def _same(expected: Any, actual: Any) -> bool:
    """Compare argument values; strings ignore case and surrounding spaces."""
    if isinstance(expected, str) and isinstance(actual, str):
        return expected.strip().casefold() == actual.strip().casefold()
    if isinstance(expected, bool) or isinstance(actual, bool):
        return expected is actual
    if isinstance(expected, int | float) and isinstance(actual, int | float):
        return float(expected) == float(actual)
    if isinstance(expected, dict) and isinstance(actual, dict):
        return all(k in actual and _same(v, actual[k]) for k, v in expected.items())
    if isinstance(expected, list) and isinstance(actual, list):
        return len(expected) == len(actual) and all(map(_same, expected, actual))
    return bool(expected == actual)


def judge(case: EvalCase, choice: Choice, tools: dict[str, types.Tool]) -> list[str]:
    """Failure messages for one answer; empty means it's correct."""
    if case.expect_tool is None:
        if choice.tool is not None:
            return [f"expected no tool call, got {choice.tool}"]
        return []
    if choice.tool is None:
        return [f"expected {case.expect_tool}, but the model called no tool"]
    if choice.tool != case.expect_tool:
        return [f"expected {case.expect_tool}, got {choice.tool}"]

    failures = []
    for key, expected in case.expect_args.items():
        if key not in choice.args:
            failures.append(f"argument {key!r} missing (expected {expected!r})")
        elif not _same(expected, choice.args[key]):
            failures.append(f"argument {key!r} is {choice.args[key]!r}, expected {expected!r}")
    tool = tools.get(choice.tool)
    if tool is not None:
        errors = list(Draft202012Validator(tool.input_schema).iter_errors(choice.args))
        if errors:
            failures.append(f"arguments don't match the input schema: {errors[0].message}")
    return failures


# ---------- running ----------


def _short(text: str, limit: int = 60) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def resolve_provider_and_model(config: EvalConfig) -> tuple[str, str]:
    """Pick provider and model: command-line flags, then environment variables, then the YAML."""
    provider = (
        config.override_provider or os.environ.get("TOOLPROOF_EVAL_PROVIDER") or config.provider
    )
    model = config.override_model or os.environ.get("TOOLPROOF_EVAL_MODEL") or config.model
    if not provider:
        raise EvalError(
            "no eval provider: set evals.provider (anthropic, openai or command) "
            "or TOOLPROOF_EVAL_PROVIDER"
        )
    if provider not in ("anthropic", "openai", "command"):
        raise EvalError(f"unknown eval provider {provider!r}: use anthropic, openai or command")
    if provider == "command" and not config.command:
        raise EvalError("the command provider needs evals.command")
    if provider != "command" and not model:
        raise EvalError("no eval model: set evals.model or TOOLPROOF_EVAL_MODEL")
    return provider, model or ""


async def run_evals(tools: list[types.Tool], config: EvalConfig, base_dir: Path) -> EvalReport:
    """Ask the model about every case and score the answers."""
    try:
        provider, model = resolve_provider_and_model(config)
    except EvalError as exc:
        return EvalReport(
            provider=config.provider or "",
            model=config.model or "",
            min_accuracy=config.min_accuracy,
            error=str(exc),
        )

    report = EvalReport(provider=provider, model=model, min_accuracy=config.min_accuracy)
    # A tool whose input schema isn't valid JSON Schema would make the API
    # reject every request, so leave it out and say so. The static checks
    # report the broken schema itself.
    usable = []
    for tool in tools:
        try:
            Draft202012Validator.check_schema(tool.input_schema)
            usable.append(tool)
        except SchemaError:
            report.skipped_tools.append(tool.name)
    api_tools, back = _api_tools(usable)
    by_name = {t.name: t for t in tools}
    cache_dir = (base_dir / config.cache_dir).resolve()
    # A local command is cheap, and the key can't see edits to the script,
    # so only answers from model APIs are cached.
    use_cache = config.cache and provider != "command"
    params = dict(config.params)

    def ask(prompt: str) -> Choice:
        if provider == "anthropic":
            return _ask_anthropic(model, config.system, prompt, api_tools, params)
        if provider == "openai":
            return _ask_openai(model, config.system, prompt, api_tools, params)
        return _ask_command(
            config.command or [],
            base_dir,
            config.timeout_s,
            model,
            config.system,
            prompt,
            api_tools,
        )

    for case in config.cases:
        result = EvalCaseResult(
            name=case.name or _short(case.prompt),
            prompt=case.prompt,
            expect_tool=case.expect_tool,
            expect_args=case.expect_args,
        )
        key = cache_key(provider, model, config.system, case.prompt, api_tools, params)
        # `refresh` (--no-cache) skips reading but still stores the new answers.
        choice = _read_cache(cache_dir, key) if use_cache and not config.refresh else None
        if choice is not None:
            result.cached = True
        else:
            try:
                choice = await anyio.to_thread.run_sync(ask, case.prompt)
            except EvalError as exc:
                report.error = str(exc)
                report.cases.append(result)
                return report
            except Exception as exc:  # a provider hiccup on one case shouldn't stop the run
                result.failures = [f"provider error: {exc}"]
                report.cases.append(result)
                continue
            # Map API-safe names back to the server's tool names before caching,
            # so cached files show the real names.
            if choice.tool is not None:
                choice.tool = back.get(choice.tool, choice.tool)
            if use_cache:
                _write_cache(
                    cache_dir,
                    key,
                    choice,
                    {"provider": provider, "model": model, "prompt": case.prompt},
                )

        result.picked_tool, result.picked_args, result.text = choice.tool, choice.args, choice.text
        result.failures = judge(case, choice, by_name)
        report.cases.append(result)

    return report
