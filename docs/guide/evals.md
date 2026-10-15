# Tool-selection evals

A tool can work perfectly and still go unused, because a model reading its name and description doesn't realize it's the right one. Tool-selection evals check that: for each prompt, toolproof gives a model your server's tool list and records which tool it picks and with which arguments. No tool is actually called.

```yaml
evals:
  provider: anthropic
  model: your-model-name
  min_accuracy: 0.9
  cases:
    - prompt: Is it raining in Montreal right now?
      expect_tool: get_weather
      expect_args: { city: Montreal }

    - prompt: What's the 5 day forecast for Calgary?
      expect_tool: get_forecast
      expect_args: { city: Calgary, days: 5 }

    - prompt: Tell me a joke.
      expect_tool: null        # no tool should be called
```

```bash
toolproof eval -c toolproof.yaml
```

Evals are the only part of toolproof that needs a model. Everything else works offline.

## Providers

=== "Anthropic"

    ```bash
    pip install "mcp-toolproof[anthropic]"
    export ANTHROPIC_API_KEY=...
    ```

    ```yaml
    evals:
      provider: anthropic
      model: your-model-name
    ```

    Uses the Anthropic Messages API with `tool_choice: auto`. The SDK's usual credential sources work, not only `ANTHROPIC_API_KEY`.

=== "OpenAI and compatible APIs"

    ```bash
    pip install "mcp-toolproof[openai]"
    export OPENAI_API_KEY=...
    # For another OpenAI-compatible API:
    export OPENAI_BASE_URL=https://your-provider.example.com/v1
    ```

    ```yaml
    evals:
      provider: openai
      model: your-model-name
    ```

    Uses the Chat Completions API with `tool_choice: auto`.

=== "Your own program"

    ```yaml
    evals:
      provider: command
      command: ["python", "pick_tool.py"]
    ```

    The program reads one JSON request on stdin and prints its choice on stdout:

    ```json
    {"model": "", "system": null, "prompt": "Is it raining in Montreal?",
     "tools": [{"name": "get_weather", "description": "...", "input_schema": {...}}]}
    ```

    ```json
    {"tool": "get_weather", "args": {"city": "Montreal"}}
    ```

    Use `"tool": null` for no tool. Use this to call a provider toolproof doesn't support, a local model, or an agent framework. The repository's [`examples/keyword_picker.py`](https://github.com/NilkanthSuthar/toolproof/blob/main/examples/keyword_picker.py) is a minimal example.

The provider and model can also come from the environment, which is handy in CI: `TOOLPROOF_EVAL_PROVIDER` and `TOOLPROOF_EVAL_MODEL`. Command-line flags beat environment variables, which beat the YAML:

```bash
toolproof eval -c toolproof.yaml --provider openai --model your-model-name
```

There is no default model. Pick the one your users' clients actually use.

## Scoring

A case is **correct** when:

1. the model picked `expect_tool` (or no tool, when `expect_tool: null`), and
2. every key in `expect_args` matches. Keys you don't list aren't checked. Strings are compared ignoring case and surrounding spaces, numbers by value, objects key by key, and
3. the arguments are valid against the tool's input schema.

**Accuracy** is the share of correct cases. The run fails when accuracy is below `min_accuracy` (default `1.0`, every case must pass), or when the provider can't be used at all, for example because of a missing API key or an unknown model. A temporary error on one case, like a rate limit after retries, counts as a miss for that case and the run carries on.

A single wrong pick doesn't fail the run on its own. That's deliberate: models are not perfectly consistent, and `min_accuracy` is where you decide how much to tolerate.

## Caching

Answers from `anthropic` and `openai` are cached in `.toolproof-cache/evals/`, one small JSON file per answer. The cache key covers everything that can change the answer: provider, model, system prompt, prompt, the full tool list with schemas, and `params`. Editing a tool's description therefore asks the model again, and re-running unchanged evals is free and gives the same result.

```bash
toolproof eval -c toolproof.yaml --no-cache   # ask again and update the cache
```

For CI there are two good setups:

- **Commit the cache.** CI reuses the answers and needs no API key. When a tool changes, its cases miss the cache and run against the API, so add the key as a secret for those runs.
- **Don't commit it.** Every CI run asks the model, which costs a little and can vary slightly between runs.

`command` providers are never cached. They're local and cheap, and the cache key can't see changes to your script.

## Options

| Key | Default | Description |
|---|---|---|
| `provider` | none | `anthropic`, `openai` or `command`. |
| `model` | none | Model name, passed to the provider. Required for `anthropic` and `openai`. |
| `command` | none | The program for `provider: command`. |
| `system` | none | Optional system prompt, for example the one your client uses. |
| `params` | `{}` | Extra request fields passed straight to the provider, for example `{seed: 1}` for OpenAI or `{output_config: {effort: low}}` for Anthropic. |
| `min_accuracy` | `1.0` | Fail below this share of correct cases. |
| `cache` | `true` | Cache API answers. |
| `cache_dir` | `.toolproof-cache` | Cache folder, relative to the YAML file. |
| `timeout_s` | `120` | Timeout for `provider: command`. |
| `enabled` | `true` | Include the section in `toolproof run`. |
| `cases` | `[]` | `prompt`, `expect_tool` (required, may be `null`), optional `expect_args` and `name`. |

## Writing good cases

- **Use real requests.** Take prompts from how people actually ask, not from your tool descriptions. A case that repeats the tool's description word for word proves little.
- **Cover the confusable pairs.** If you have `get_weather` and `get_forecast`, write prompts near the boundary between them ("will it rain tomorrow?").
- **Include "no tool" cases.** A model that calls a tool for "thanks!" is a real problem.
- **When a case fails, fix the tool first.** A clearer name or description usually helps every client, not only the one you tested with.

## Cost

Each uncached case is one API request containing your full tool list. With a few dozen cases and caching on, a run costs very little, and unchanged re-runs cost nothing.
