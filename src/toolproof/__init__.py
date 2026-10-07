"""toolproof: automated tests for MCP servers."""

from toolproof.client import CallResult, McpServer, ServerError
from toolproof.config import Config, ServerConfig, load_config

__version__ = "0.2.0"

__all__ = [
    "CallResult",
    "Config",
    "McpServer",
    "ServerConfig",
    "ServerError",
    "__version__",
    "load_config",
]
