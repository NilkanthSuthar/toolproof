# Benchmarks

`toolproof bench` measures how fast a server answers: latency percentiles, throughput and error rate, with a chosen number of calls in flight.

```bash
toolproof bench --tool get_weather --args '{"city": "Toronto"}' --calls 500 --concurrency 20 -- python my_server.py
toolproof bench -c toolproof.yaml
```

## What is measured

For each target, toolproof makes `warmup` calls that aren't counted, then `calls` calls with `concurrency` of them in flight at once, all over one connection. It reports:

| Column | Meaning |
|---|---|
| p50 / p95 / p99 | Latency percentiles (nearest-rank) in milliseconds, measured client-side for each call. |
| Calls/s | Completed calls divided by the wall-clock time of the measured part. |
| Errors | Share of calls that returned an error result, failed, or timed out. |

The JSON report also has the mean and the maximum.

```
Bench
┌──────┬─────────────────┬─────────┬───────┬────────┬────────┬─────────┬────────┬─────────┐
│      │ Target          │   Calls │   p50 │    p95 │    p99 │ Calls/s │ Errors │ Details │
├──────┼─────────────────┼─────────┼───────┼────────┼────────┼─────────┼────────┼─────────┤
│ PASS │ toronto weather │  50 x5  │ 8.3ms │ 10.8ms │ 11.9ms │   583.0 │   0.0% │         │
└──────┴─────────────────┴─────────┴───────┴────────┴────────┴─────────┴────────┴─────────┘
```

## Choosing targets

In order of precedence:

1. `--tool NAME --args JSON` on the command line benchmarks that one call.
2. `bench.targets` in the YAML file.
3. Otherwise, every test case in `tests` that doesn't expect an error, with its arguments.

```yaml
bench:
  calls: 200
  concurrency: 10
  targets:
    - tool: get_weather
      args: { city: Toronto }
    - tool: search
      name: search, broad query
      args: { query: "a" }
      thresholds: { p95_ms: 800 }
```

## Thresholds

A benchmark passes unless it breaks a threshold you set. Without thresholds it only reports numbers.

```yaml
bench:
  thresholds:
    p95_ms: 200
    p99_ms: 500
    max_error_rate: 0.01   # 1%
    min_throughput: 50     # calls per second
```

The same limits are available as flags: `--p50-ms`, `--p95-ms`, `--p99-ms`, `--max-error-rate`, `--min-throughput`.

## Reading the numbers

- Latency includes the transport. Over stdio that is small; over HTTP it includes the network.
- CI runners are noisy. Set thresholds with headroom, for example two to three times what you see locally, and treat them as guards against big regressions rather than exact targets.
- Tools are benchmarked one target at a time, so targets don't slow each other down.
- If a target crashes the server, the remaining calls fail quickly and show up as errors.
