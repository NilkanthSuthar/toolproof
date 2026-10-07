"""toolproof: automated tests for MCP servers.

The names exported here are the public Python API. Anything else may change
between minor releases.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from toolproof.client import CallResult, McpServer, ServerError
from toolproof.config import Config, ConfigError, ServerConfig, load_config

if TYPE_CHECKING:
    from toolproof.runner import RunReport, run_config, run_config_async

__version__ = "0.2.0"

__all__ = [
    "CallResult",
    "Config",
    "ConfigError",
    "McpServer",
    "RunReport",
    "ServerConfig",
    "ServerError",
    "__version__",
    "load_config",
    "run_config",
    "run_config_async",
]

# The runner pulls in Hypothesis (for fuzzing). Importing it lazily keeps
# `import toolproof` and the pytest plugin fast for people who never fuzz.
_RUNNER_NAMES = {"RunReport", "run_config", "run_config_async"}


def __getattr__(name: str) -> Any:
    if name in _RUNNER_NAMES:
        from toolproof import runner

        return getattr(runner, name)
    raise AttributeError(f"module 'toolproof' has no attribute {name!r}")
