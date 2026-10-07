# Assertions

Each test's `expect` block lists what the tool result must look like. Every key is optional, and all the keys you set must pass. With an empty `expect`, a test only checks that the server answered and, if the tool declares one, that the result matches its `outputSchema`.

## What a result looks like

An MCP tool result has content blocks, optional structured content and an error flag. toolproof reads it as:

- **text**: the text content blocks joined with newlines. Non-text blocks (images, audio, resources) appear as `<image>`, `<audio>` and so on.
- **data**: the structured content if the tool returned any, otherwise the text parsed as JSON, otherwise nothing.
- **is_error**: the result's `isError` flag. A JSON-RPC error response from the server also counts as an error, with its message as the text.

## Keys

### `is_error`

```yaml
expect: { is_error: true }
```

`true` when the call should fail, `false` when it should succeed. Use `is_error: true` for input validation tests.

### `equals`

```yaml
expect:
  equals: { result: [Calgary, Montreal, Toronto] }
```

Compares the whole result with the value given. It compares against **data** when the result is JSON, and against **text** otherwise. `equals: null` is a valid expectation.

### `contains`

```yaml
expect:
  contains: Toronto
  # or several, all required:
  # contains: [Toronto, cloudy]
```

Each string must appear in the text.

### `regex`

```yaml
expect:
  regex: "\\d+(\\.\\d+)? ?C"
```

A Python regular expression searched for anywhere in the text. In double-quoted YAML strings, backslashes must be doubled, as above. Single quotes avoid that: `regex: '\d+ C'`.

### `jsonpath`

```yaml
expect:
  jsonpath:
    "$.temp_c": { type: number, min: -60, max: 60 }
    "$.city": { equals: Toronto }
    "$.days[0].conditions": { type: string }
    "$.days": { type: array }
    "$.wind": { exists: false }
```

Looks values up in **data** with [JSONPath](https://github.com/h2non/jsonpath-ng) (the extended syntax, so filters like `$.days[?(@.temp_c > 10)]` work). Each path takes:

| Key | Description |
|---|---|
| `type` | JSON type: `string`, `number`, `integer`, `boolean`, `array`, `object` or `null`. `true` is not a number. |
| `equals` | The value must equal this. |
| `min`, `max` | Inclusive range for a number. |
| `exists` | `true` (default) requires a match; `false` requires no match. |

When a path matches several values, they are checked together as a list.

### `max_latency_ms`

```yaml
expect: { max_latency_ms: 500 }
```

Fails if the call took longer. This is a soft limit measured after the call returns; the hard limit is the test's `timeout_ms`.

### `output_schema`

```yaml
expect: { output_schema: false }
```

When a tool declares an `outputSchema`, every successful call's structured content is validated against it automatically. Set `output_schema: false` to turn that off for one test.

## Failure messages

Every failed check adds one line to the report, for example:

```
result does not contain 'Toronto': {"city": "Montreal", "temp_c": 9.0}
$.temp_c: expected type number, got string
output schema: $.temp_c: '12.5' is not of type 'number'
took 2304ms, limit is 2000ms
no result from server: connection lost, server probably crashed (Connection closed)
```
