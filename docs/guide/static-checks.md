# Static checks

Static checks look at the tool list a server advertises, before any tool is called. They catch definitions that make a tool hard or impossible for a client to use. They run as part of `toolproof run` and `toolproof inspect`.

| Check | Severity | What it catches |
|---|---|---|
| `name` | error | A tool with an empty name. |
| `duplicate-name` | error | Two tools with the same name. |
| `description` | error | A tool with no description. Clients and models pick tools by their descriptions. |
| `description-length` | warning | A description longer than `checks.max_description_length` (default 1024 characters). |
| `input-schema` | error | An input schema that isn't valid JSON Schema (draft 2020-12), or whose root isn't `type: object`. |
| `required-fields` | error | `required` names a field that isn't in `properties`, so a valid call is impossible to build from the schema. |
| `required-fields` | warning | The schema has properties but none are required. Often fine, sometimes a forgotten `required` list. |
| `output-schema` | error | An `outputSchema` that isn't valid JSON Schema. |

Errors fail `toolproof run`. Warnings are reported but only fail the run with `--strict` or `checks.strict: true`.

To skip the checks, pass `--no-checks` or set `checks.enabled: false`.

## Example

```
Static checks
┌──────┬───────────────┬─────────────────┬──────────────────────────────────────────────────────┐
│      │ Tool          │ Check           │ Problem                                              │
├──────┼───────────────┼─────────────────┼──────────────────────────────────────────────────────┤
│ FAIL │ search_cities │ description     │ tool has no description                              │
│ FAIL │ search_cities │ input-schema    │ input schema is not valid JSON Schema: 'strng' is    │
│      │               │                 │ not valid under any of the given schemas             │
│ FAIL │ lookup        │ required-fields │ required fields not listed in properties: city_id    │
└──────┴───────────────┴─────────────────┴──────────────────────────────────────────────────────┘
```

In JUnit reports, the "static checks" suite has one test case per tool, so a clean tool shows as passed.
