import pytest

from tests.conftest import EXAMPLES
from toolproof.config import ConfigError, Expect, ServerConfig, load_config


def test_loads_example_file():
    config = load_config(EXAMPLES / "toolproof.yaml")
    assert config.server.command == ["python", "weather_server.py"]
    assert config.base_dir == EXAMPLES
    assert config.tests[0].name == "toronto weather"
    assert config.tests[0].expect.jsonpath["$.temp_c"].type == "number"


def test_server_needs_command_or_url():
    with pytest.raises(ValueError, match="exactly one"):
        ServerConfig()
    with pytest.raises(ValueError, match="exactly one"):
        ServerConfig(command=["python", "s.py"], url="http://localhost/mcp")


def test_unknown_keys_are_rejected(tmp_path):
    path = tmp_path / "toolproof.yaml"
    path.write_text(
        "server: { url: http://localhost/mcp }\n"
        "tests:\n  - { name: x, tool: t, expect: { is_eror: true } }\n"
    )
    with pytest.raises(ConfigError, match="is_eror"):
        load_config(path)


def test_missing_file():
    with pytest.raises(ConfigError, match="not found"):
        load_config("does-not-exist.yaml")


def test_bad_yaml(tmp_path):
    path = tmp_path / "toolproof.yaml"
    path.write_text("server: [unclosed")
    with pytest.raises(ConfigError, match="not valid YAML"):
        load_config(path)


def test_equals_null_counts_as_set():
    assert Expect.model_validate({"equals": None}).has_equals
    assert not Expect().has_equals
