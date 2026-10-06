import sys
from pathlib import Path

import pytest
import yaml

from toolproof.config import Config, load_config

pytest_plugins = ["pytester"]

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
WEATHER = str(EXAMPLES / "weather_server.py")
BUGGY = str(EXAMPLES / "buggy_server.py")


@pytest.fixture
def write_config(tmp_path):
    """Write a toolproof.yaml into tmp_path and load it."""

    def write(server_script: str, tests: list[dict], **extra) -> Config:
        data = {"server": {"command": [sys.executable, server_script]}, "tests": tests, **extra}
        path = tmp_path / "toolproof.yaml"
        path.write_text(yaml.safe_dump(data), encoding="utf-8")
        return load_config(path)

    return write
