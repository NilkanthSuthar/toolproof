"""Config models for toolproof.yaml.

Example:

    server:
      command: ["python", "examples/weather_server.py"]
    tests:
      - name: toronto weather
        tool: get_weather
        args: { city: Toronto }
        expect:
          is_error: false
          contains: "Toronto"
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

JsonType = Literal["string", "number", "integer", "boolean", "array", "object", "null"]


class ConfigError(Exception):
    """Raised when toolproof.yaml is missing or invalid."""


class _Strict(BaseModel):
    # Typos in the YAML should be errors, not silently ignored.
    model_config = ConfigDict(extra="forbid")


class ServerConfig(_Strict):
    """How to reach the server: a command to launch over stdio, or a URL."""

    command: list[str] | None = None
    url: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    cwd: str | None = None
    startup_timeout_s: float = 30

    @model_validator(mode="after")
    def _one_transport(self) -> ServerConfig:
        if bool(self.command) == bool(self.url):
            raise ValueError("set exactly one of 'command' or 'url'")
        if self.headers and not self.url:
            raise ValueError("'headers' only applies to 'url' servers")
        return self


class JsonPathCheck(_Strict):
    """Checks for the value found at a JSONPath."""

    type: JsonType | None = None
    equals: Any = None
    min: float | None = None
    max: float | None = None
    exists: bool = True


class Expect(_Strict):
    """What a test expects from the tool result. Every field is optional."""

    is_error: bool | None = None
    equals: Any = None
    contains: str | list[str] | None = None
    regex: str | None = None
    jsonpath: dict[str, JsonPathCheck] = Field(default_factory=dict)
    max_latency_ms: float | None = None
    output_schema: bool = True

    # `equals: null` is a valid expectation, so remember whether it was set at all.
    @property
    def has_equals(self) -> bool:
        return "equals" in self.model_fields_set


class TestCase(_Strict):
    """One tool call plus its expectations."""

    __test__ = False  # stop pytest from trying to collect this class

    name: str
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    expect: Expect = Field(default_factory=Expect)
    timeout_ms: float | None = None
    retries: int | None = None


class ChecksConfig(_Strict):
    """Settings for the static checks run on the tool list."""

    enabled: bool = True
    max_description_length: int = 1024
    strict: bool = False


class FuzzConfig(_Strict):
    """Settings for `toolproof fuzz`: random inputs generated from each tool's schema."""

    enabled: bool = True
    max_examples: int = 50  # per tool, for valid and for invalid inputs
    timeout_ms: float = 2000
    max_time_s: float = 60  # per tool, so a slow tool can't stall the run
    seed: int | None = None
    tools: list[str] = Field(default_factory=list)  # only fuzz these (empty = all)
    skip: list[str] = Field(default_factory=list)
    include_destructive: bool = False
    valid_must_succeed: bool = False
    invalid_must_fail: bool = True


class BenchThresholds(_Strict):
    """Limits that fail a benchmark. Unset limits aren't checked."""

    p50_ms: float | None = None
    p95_ms: float | None = None
    p99_ms: float | None = None
    max_error_rate: float | None = None  # 0.01 = 1%
    min_throughput: float | None = None  # calls per second


class BenchTarget(_Strict):
    """One tool call to benchmark."""

    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    name: str | None = None
    thresholds: BenchThresholds | None = None

    @property
    def label(self) -> str:
        return self.name or self.tool


class BenchConfig(_Strict):
    """Settings for `toolproof bench`.

    With no targets, every test case that doesn't expect an error is benchmarked.
    """

    enabled: bool = True
    calls: int = 100
    concurrency: int = 10
    warmup: int = 3
    timeout_ms: float = 10_000
    thresholds: BenchThresholds = Field(default_factory=BenchThresholds)
    targets: list[BenchTarget] = Field(default_factory=list)


class Config(_Strict):
    """The whole toolproof.yaml file."""

    server: ServerConfig
    timeout_ms: float = 10_000
    retries: int = 0
    checks: ChecksConfig = Field(default_factory=ChecksConfig)
    tests: list[TestCase] = Field(default_factory=list)
    fuzz: FuzzConfig | None = None
    bench: BenchConfig | None = None

    # Directory of the YAML file. Relative paths in `command` and `cwd` resolve from here.
    base_dir: Path = Field(default_factory=Path.cwd, exclude=True)


_ENV_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def expand_env(value: Any) -> Any:
    """Replace `${NAME}` with the environment variable NAME, in strings, lists and dicts.

    Used for the `server:` section so secrets like API keys can come from the
    CI environment instead of being written into toolproof.yaml.
    Raises KeyError with the variable name if it isn't set.
    """
    if isinstance(value, str):
        return _ENV_VAR.sub(lambda m: os.environ[m.group(1)], value)
    if isinstance(value, list):
        return [expand_env(v) for v in value]
    if isinstance(value, dict):
        return {k: expand_env(v) for k, v in value.items()}
    return value


def load_config(path: str | Path) -> Config:
    """Read and validate a toolproof.yaml file."""
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} should contain a mapping at the top level")
    if isinstance(raw.get("server"), dict):
        try:
            raw["server"] = expand_env(raw["server"])
        except KeyError as exc:
            raise ConfigError(
                f"{path}: environment variable {exc.args[0]} is not set "
                f"(used as ${{{exc.args[0]}}} in 'server')"
            ) from exc
    try:
        config = Config.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"{path} is invalid:\n{exc}") from exc
    config.base_dir = path.resolve().parent
    return config
