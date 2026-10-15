"""Tool-selection evals. No test calls a real model API: the provider SDKs are
replaced with fakes, and end-to-end runs use the keyword picker script."""

import json
import sys
from types import SimpleNamespace

import anthropic
import mcp_types as types
import openai
import pytest

from tests.conftest import EXAMPLES, WEATHER
from toolproof import evals
from toolproof.config import EvalCase, EvalConfig
from toolproof.evals import Choice, EvalError, judge
from toolproof.runner import run_config

PICKER = str(EXAMPLES / "keyword_picker.py")

TOOLS = {
    "get_weather": types.Tool(
        name="get_weather",
        description="Weather for a city.",
        input_schema={
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    )
}


def case(**kwargs):
    return EvalCase.model_validate({"prompt": "p", **kwargs})


# ---------- judging ----------


def test_correct_tool_and_args():
    c = case(expect_tool="get_weather", expect_args={"city": "Montreal"})
    assert judge(c, Choice("get_weather", {"city": " montreal "}), TOOLS) == []


def test_wrong_tool():
    c = case(expect_tool="get_weather")
    assert judge(c, Choice("get_forecast", {}), TOOLS) == ["expected get_weather, got get_forecast"]
    assert "called no tool" in judge(c, Choice(None), TOOLS)[0]


def test_expect_no_tool():
    c = case(expect_tool=None)
    assert judge(c, Choice(None), TOOLS) == []
    assert "expected no tool call" in judge(c, Choice("get_weather", {"city": "x"}), TOOLS)[0]


def test_argument_checks():
    c = case(expect_tool="get_weather", expect_args={"city": "Montreal"})
    assert "missing" in judge(c, Choice("get_weather", {}), TOOLS)[0]
    assert "expected 'Montreal'" in judge(c, Choice("get_weather", {"city": "Paris"}), TOOLS)[0]


def test_arguments_must_match_the_schema():
    c = case(expect_tool="get_weather")
    failures = judge(c, Choice("get_weather", {"city": 5}), TOOLS)
    assert "don't match the input schema" in failures[0]


def test_value_comparison():
    assert evals._same(5, 5.0)
    assert not evals._same(True, 1)
    assert evals._same({"a": "X"}, {"a": "x", "b": 2})
    assert evals._same([1, "A"], [1, "a"])
    assert not evals._same([1], [1, 2])


def test_expect_tool_is_required():
    with pytest.raises(ValueError, match="expect_tool"):
        EvalCase.model_validate({"prompt": "p"})


# ---------- requests ----------


def test_tool_names_are_made_api_safe():
    tools = [
        types.Tool(name="weather.get", description="a", input_schema={"type": "object"}),
        types.Tool(name="weather/get", description="b", input_schema={"type": "object"}),
    ]
    defs, back = evals._api_tools(tools)
    names = [d["name"] for d in defs]
    assert len(set(names)) == 2
    assert all(evals._SAFE_NAME.search(n) is None for n in names)
    assert {back[n] for n in names} == {"weather.get", "weather/get"}


def test_cache_key_covers_everything_that_changes_the_answer():
    base = ("anthropic", "m", None, "prompt", [{"name": "t"}], {})
    key = evals.cache_key(*base)
    assert evals.cache_key(*base) == key
    for i, changed in enumerate(["openai", "m2", "sys", "other", [{"name": "u"}], {"x": 1}]):
        args = list(base)
        args[i] = changed
        assert evals.cache_key(*args) != key


def test_provider_precedence(monkeypatch):
    config = EvalConfig(provider="openai", model="from-yaml", cases=[])
    monkeypatch.setenv("TOOLPROOF_EVAL_MODEL", "from-env")
    assert evals.resolve_provider_and_model(config) == ("openai", "from-env")
    config.override_model = "from-flag"
    assert evals.resolve_provider_and_model(config) == ("openai", "from-flag")


def test_provider_errors(monkeypatch):
    monkeypatch.delenv("TOOLPROOF_EVAL_PROVIDER", raising=False)
    monkeypatch.delenv("TOOLPROOF_EVAL_MODEL", raising=False)
    with pytest.raises(EvalError, match="no eval provider"):
        evals.resolve_provider_and_model(EvalConfig(cases=[]))
    with pytest.raises(EvalError, match="no eval model"):
        evals.resolve_provider_and_model(EvalConfig(provider="anthropic", cases=[]))
    with pytest.raises(EvalError, match="needs evals.command"):
        evals.resolve_provider_and_model(EvalConfig(provider="command", cases=[]))


# ---------- provider adapters, against fake SDK clients ----------


class FakeAnthropic:
    calls: list[dict] = []

    def __init__(self):
        self.messages = SimpleNamespace(create=self.create)

    def create(self, **kwargs):
        FakeAnthropic.calls.append(kwargs)
        return SimpleNamespace(
            stop_reason="tool_use",
            content=[
                SimpleNamespace(type="text", text="Let me check."),
                SimpleNamespace(type="tool_use", name="get_weather", input={"city": "Montreal"}),
            ],
        )


def test_anthropic_request_and_parsing(monkeypatch):
    FakeAnthropic.calls = []
    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropic)
    tools, _ = evals._api_tools(list(TOOLS.values()))
    choice = evals._ask_anthropic("some-model", "be brief", "rain in Montreal?", tools, {})

    assert choice == Choice("get_weather", {"city": "Montreal"}, "Let me check.")
    [request] = FakeAnthropic.calls
    assert request["model"] == "some-model"
    assert request["system"] == "be brief"
    assert request["tool_choice"] == {"type": "auto"}
    assert request["tools"][0]["input_schema"]["required"] == ["city"]
    assert request["messages"] == [{"role": "user", "content": "rain in Montreal?"}]
    assert "temperature" not in request


def test_anthropic_refusal_is_no_tool(monkeypatch):
    class Refuses(FakeAnthropic):
        def create(self, **kwargs):
            return SimpleNamespace(stop_reason="refusal", content=[])

    monkeypatch.setattr(anthropic, "Anthropic", Refuses)
    choice = evals._ask_anthropic("m", None, "p", [], {})
    assert choice.tool is None


class FakeOpenAI:
    calls: list[dict] = []

    def __init__(self):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        FakeOpenAI.calls.append(kwargs)
        call = SimpleNamespace(
            type="function",
            function=SimpleNamespace(name="get_weather", arguments='{"city": "Toronto"}'),
        )
        message = SimpleNamespace(content=None, tool_calls=[call])
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def test_openai_request_and_parsing(monkeypatch):
    FakeOpenAI.calls = []
    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)
    tools, _ = evals._api_tools(list(TOOLS.values()))
    choice = evals._ask_openai("m", "sys", "weather in Toronto", tools, {"seed": 1})

    assert choice.tool == "get_weather" and choice.args == {"city": "Toronto"}
    [request] = FakeOpenAI.calls
    assert request["tool_choice"] == "auto"
    assert request["seed"] == 1  # params pass straight through
    assert request["messages"][0] == {"role": "system", "content": "sys"}
    assert request["tools"][0]["function"]["parameters"]["required"] == ["city"]


def test_command_provider_errors(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("print('not json')")
    with pytest.raises(RuntimeError, match="invalid JSON"):
        evals._ask_command([sys.executable, str(bad)], tmp_path, 10, "", None, "p", [])
    fails = tmp_path / "fails.py"
    fails.write_text("import sys; print('boom', file=sys.stderr); sys.exit(3)")
    with pytest.raises(RuntimeError, match="exited 3: boom"):
        evals._ask_command([sys.executable, str(fails)], tmp_path, 10, "", None, "p", [])
    with pytest.raises(EvalError, match="not found"):
        evals._ask_command(["no-such-program-xyz"], tmp_path, 10, "", None, "p", [])


# ---------- end to end ----------

CASES = [
    {
        "prompt": "Is it raining in Montreal?",
        "expect_tool": "get_weather",
        "expect_args": {"city": "Montreal"},
    },
    {
        "prompt": "5 day forecast for Calgary",
        "expect_tool": "get_forecast",
        "expect_args": {"days": 5},
    },
    {"prompt": "Tell me a joke", "expect_tool": None},
    {"prompt": "Weather please", "expect_tool": "get_weather", "name": "no city given"},
]


def test_command_provider_end_to_end(write_config):
    config = write_config(
        WEATHER,
        [],
        evals={
            "provider": "command",
            "command": [sys.executable, PICKER],
            "cases": CASES,
            "min_accuracy": 0.75,
        },
    )
    report = run_config(config, ["evals"])
    ev = report.evals
    assert ev is not None and ev.error is None
    assert [c.passed for c in ev.cases] == [True, True, True, False]
    assert ev.accuracy == 0.75
    assert ev.cases[3].name == "no city given"
    assert ev.cases[0].name == "Is it raining in Montreal?"
    assert report.passed
    assert not (config.base_dir / ".toolproof-cache").exists()  # commands aren't cached

    config.evals.min_accuracy = 1.0
    assert not run_config(config, ["evals"]).passed


def test_api_answers_are_cached(write_config, monkeypatch):
    asked = []

    def fake_ask(model, system, prompt, tools, params):
        asked.append(prompt)
        return Choice("get_weather", {"city": "Montreal"})

    monkeypatch.setattr(evals, "_ask_anthropic", fake_ask)
    config = write_config(
        WEATHER, [], evals={"provider": "anthropic", "model": "test-model", "cases": CASES[:1]}
    )

    first = run_config(config, ["evals"]).evals
    assert asked == ["Is it raining in Montreal?"] and not first.cases[0].cached
    [cached_file] = (config.base_dir / ".toolproof-cache" / "evals").iterdir()
    assert json.loads(cached_file.read_text())["tool"] == "get_weather"

    second = run_config(config, ["evals"]).evals
    assert len(asked) == 1 and second.cases[0].cached and second.passed

    config.evals.refresh = True  # --no-cache
    run_config(config, ["evals"])
    assert len(asked) == 2


def test_provider_error_on_one_case_does_not_stop_the_run(write_config, monkeypatch):
    def flaky(model, system, prompt, tools, params):
        if "Montreal" in prompt:
            raise RuntimeError("rate limited")
        return Choice(None)

    monkeypatch.setattr(evals, "_ask_anthropic", flaky)
    config = write_config(
        WEATHER,
        [],
        evals={
            "provider": "anthropic",
            "model": "m",
            "cache": False,
            "cases": [CASES[0], CASES[2]],
        },
    )
    ev = run_config(config, ["evals"]).evals
    assert ev.cases[0].failures == ["provider error: rate limited"]
    assert ev.cases[1].passed


def test_missing_api_key_stops_the_run(write_config, monkeypatch):
    def no_key(*args):
        raise EvalError("anthropic: no API key")

    monkeypatch.setattr(evals, "_ask_anthropic", no_key)
    config = write_config(
        WEATHER, [], evals={"provider": "anthropic", "model": "m", "cases": CASES}
    )
    report = run_config(config, ["evals"])
    assert report.evals.error == "anthropic: no API key"
    assert not report.passed


def sdk_error(cls, message):
    """An SDK exception without a real HTTP response behind it."""
    exc = cls.__new__(cls)
    Exception.__init__(exc, message)
    return exc


@pytest.mark.parametrize(
    ("module", "client", "error", "ask"),
    [
        (anthropic, "Anthropic", anthropic.BadRequestError, evals._ask_anthropic),
        (openai, "OpenAI", openai.BadRequestError, evals._ask_openai),
        (openai, "OpenAI", openai.UnprocessableEntityError, evals._ask_openai),
    ],
)
def test_rejected_requests_stop_the_run(monkeypatch, module, client, error, ask):
    def raise_error(**kwargs):
        raise sdk_error(error, "invalid params")

    fake = SimpleNamespace(
        messages=SimpleNamespace(create=raise_error),
        chat=SimpleNamespace(completions=SimpleNamespace(create=raise_error)),
    )
    monkeypatch.setattr(module, client, lambda: fake)
    with pytest.raises(EvalError, match="rejected the request: invalid params"):
        ask("m", None, "p", [], {})


def test_tools_with_invalid_schemas_are_left_out(write_config):
    from tests.conftest import BUGGY

    config = write_config(
        BUGGY,
        [],
        evals={
            "provider": "command",
            "command": [sys.executable, PICKER],
            "cases": [{"prompt": "Weather in Toronto", "expect_tool": "get_weather"}],
        },
    )
    ev = run_config(config, ["evals"]).evals
    assert ev.skipped_tools == ["search_cities"]
    assert ev.passed
