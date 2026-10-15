"""Single-file HTML report.

The page has no external scripts, styles or fonts, so it works when opened
offline from a CI artifact. Everything that came from the server under test
(tool output, inputs, stderr, messages) is untrusted, so every value goes
through `_e()` before it is written into the page.
"""

from __future__ import annotations

import html
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from toolproof import __version__
from toolproof.runner import RunReport


def _e(value: Any) -> str:
    """Escape any value for use in HTML text or a quoted attribute."""
    return html.escape(str(value), quote=True)


def _badge(passed: bool, label: str | None = None) -> str:
    cls = "pass" if passed else "fail"
    return f'<span class="badge {cls}">{_e(label or ("PASS" if passed else "FAIL"))}</span>'


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def render_html(report: RunReport) -> str:
    """Build the full HTML page for a report."""
    title = report.server_name or report.target
    if report.server_version:
        title += f" {report.server_version}"
    generated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    sections = [_summary(report)]
    if report.error:
        sections.append(
            f'<section><h2>Connection error</h2><pre class="err">{_e(report.error)}</pre></section>'
        )
    if "checks" in report.phases:
        sections.append(_checks(report))
    if "tests" in report.phases:
        sections.append(_tests(report))
    if "bench" in report.phases:
        sections.append(_bench(report))
    if "fuzz" in report.phases:
        sections.append(_fuzz(report))
    if "evals" in report.phases:
        sections.append(_evals(report))

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>toolproof report - {_e(title)}</title>
<style>{_CSS}</style>
</head>
<body>
<header>
  <h1>toolproof report</h1>
  <p class="meta">{_e(title)} &middot; <code>{_e(report.target)}</code></p>
  <p class="meta">Generated {_e(generated)} by toolproof {_e(__version__)}
     in {report.duration_s:.2f}s</p>
</header>
<main>
{"".join(sections)}
</main>
</body>
</html>
"""


def write_html(report: RunReport, path: str | Path) -> None:
    Path(path).write_text(render_html(report), encoding="utf-8")


# ---------- sections ----------


def _summary(report: RunReport) -> str:
    cards = [
        f'<div class="card">{_badge(report.passed, "PASSED" if report.passed else "FAILED")}</div>'
    ]
    if "tests" in report.phases:
        passed = len(report.tests) - report.tests_failed
        cards.append(_card("Tests", f"{passed}/{len(report.tests)}", report.tests_failed == 0))
    if "checks" in report.phases:
        errors = sum(1 for c in report.checks if c.severity == "error")
        cards.append(_card("Check errors", str(errors), not report.checks_failed))
    if "bench" in report.phases:
        failed = sum(1 for b in report.bench if not b.passed)
        cards.append(
            _card("Bench", f"{len(report.bench) - failed}/{len(report.bench)}", failed == 0)
        )
    if "fuzz" in report.phases:
        findings = sum(len(f.findings) for f in report.fuzz)
        cards.append(_card("Fuzz findings", str(findings), findings == 0))
    if "evals" in report.phases and report.evals is not None:
        ev = report.evals
        cards.append(_card("Eval accuracy", f"{ev.accuracy:.0%}", ev.passed))
    return f'<section class="cards">{"".join(cards)}</section>'


def _card(label: str, value: str, ok: bool) -> str:
    cls = "ok" if ok else "bad"
    return f'<div class="card {cls}"><div class="value">{_e(value)}</div><div class="label">{_e(label)}</div></div>'


def _checks(report: RunReport) -> str:
    if not report.checks:
        return '<section><h2>Static checks</h2><p class="muted">No problems found.</p></section>'
    rows = []
    for c in report.checks:
        failing = c.severity == "error" or report.strict
        badge = _badge(not failing, "FAIL" if failing else "WARN")
        rows.append(
            f"<tr><td>{badge}</td><td><code>{_e(c.tool)}</code></td>"
            f"<td>{_e(c.check)}</td><td>{_e(c.message)}</td></tr>"
        )
    return f"""<section><h2>Static checks</h2>
<table><thead><tr><th></th><th>Tool</th><th>Check</th><th>Problem</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table></section>"""


def _tests(report: RunReport) -> str:
    if not report.tests:
        return '<section><h2>Tests</h2><p class="muted">No tests.</p></section>'
    slowest = max((t.latency_ms for t in report.tests), default=1.0) or 1.0
    rows = []
    for t in report.tests:
        details = "".join(f"<div>{_e(f)}</div>" for f in t.failures)
        if t.attempts > 1:
            details += f'<div class="muted">after {t.attempts} attempts</div>'
        extra = ""
        if t.result is not None and t.result.text:
            extra += (
                f"<details><summary>Result</summary><pre>{_e(t.result.text[:5000])}</pre></details>"
            )
        if t.server_stderr:
            extra += f'<details open><summary>Server stderr</summary><pre class="err">{_e(t.server_stderr)}</pre></details>'
        width = max(2.0, 100 * t.latency_ms / slowest)
        rows.append(
            f"<tr><td>{_badge(t.passed)}</td><td>{_e(t.name)}</td><td><code>{_e(t.tool)}</code></td>"
            f'<td class="num">{t.latency_ms:.0f}ms<div class="bar"><span style="width:{width:.1f}%"></span></div></td>'
            f"<td>{details}{extra}</td></tr>"
        )
    return f"""<section><h2>Tests</h2>
<table><thead><tr><th></th><th>Test</th><th>Tool</th><th>Latency</th><th>Details</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table></section>"""


def _bench(report: RunReport) -> str:
    if not report.bench:
        return '<section><h2>Benchmarks</h2><p class="muted">Nothing benchmarked.</p></section>'
    rows = []
    for b in report.bench:
        details = "".join(f"<div>{_e(f)}</div>" for f in b.failures)
        if b.first_error:
            details += f'<div class="muted">first error: {_e(b.first_error)}</div>'
        rows.append(
            f"<tr><td>{_badge(b.passed)}</td><td>{_e(b.name)}</td>"
            f'<td class="num">{b.calls} &times; {b.concurrency}</td>'
            f'<td class="num">{b.p50_ms:.1f}</td><td class="num">{b.p95_ms:.1f}</td>'
            f'<td class="num">{b.p99_ms:.1f}</td><td class="num">{b.throughput:.1f}</td>'
            f'<td class="num">{b.error_rate:.1%}</td><td>{details}</td></tr>'
        )
    return f"""<section><h2>Benchmarks</h2>
{_latency_chart(report)}
<table><thead><tr><th></th><th>Target</th><th>Calls</th><th>p50 ms</th><th>p95 ms</th>
<th>p99 ms</th><th>Calls/s</th><th>Errors</th><th>Details</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table></section>"""


def _latency_chart(report: RunReport) -> str:
    """Horizontal bars per target: p50 solid, p95 and p99 as lighter extensions."""
    top = max((b.p99_ms for b in report.bench), default=0.0) or 1.0
    row_h, label_w, chart_w = 28, 220, 520
    height = row_h * len(report.bench) + 30
    parts = []
    for i, b in enumerate(report.bench):
        y = i * row_h + 6

        def w(ms: float) -> float:
            return max(1.0, chart_w * ms / top)

        label = b.name if len(b.name) <= 30 else b.name[:29] + "…"
        parts.append(
            f'<text x="{label_w - 8}" y="{y + 13}" text-anchor="end" class="lbl">{_e(label)}</text>'
            f'<rect x="{label_w}" y="{y}" width="{w(b.p99_ms):.1f}" height="16" class="p99"><title>p99 {b.p99_ms:.1f} ms</title></rect>'
            f'<rect x="{label_w}" y="{y}" width="{w(b.p95_ms):.1f}" height="16" class="p95"><title>p95 {b.p95_ms:.1f} ms</title></rect>'
            f'<rect x="{label_w}" y="{y}" width="{w(b.p50_ms):.1f}" height="16" class="p50"><title>p50 {b.p50_ms:.1f} ms</title></rect>'
            f'<text x="{label_w + w(b.p99_ms) + 6:.1f}" y="{y + 13}" class="val">{b.p99_ms:.1f} ms</text>'
        )
    legend_y = height - 8
    legend = (
        f'<rect x="{label_w}" y="{legend_y - 10}" width="12" height="10" class="p50"/>'
        f'<text x="{label_w + 16}" y="{legend_y}" class="lbl">p50</text>'
        f'<rect x="{label_w + 56}" y="{legend_y - 10}" width="12" height="10" class="p95"/>'
        f'<text x="{label_w + 72}" y="{legend_y}" class="lbl">p95</text>'
        f'<rect x="{label_w + 112}" y="{legend_y - 10}" width="12" height="10" class="p99"/>'
        f'<text x="{label_w + 128}" y="{legend_y}" class="lbl">p99</text>'
    )
    total_w = label_w + chart_w + 90
    return (
        f'<svg class="chart" viewBox="0 0 {total_w} {height}" role="img" '
        f'aria-label="Latency percentiles per target">{"".join(parts)}{legend}</svg>'
    )


def _fuzz(report: RunReport) -> str:
    if not report.fuzz:
        return '<section><h2>Fuzzing</h2><p class="muted">No tools fuzzed.</p></section>'
    rows = []
    for f in report.fuzz:
        if f.skipped:
            rows.append(
                f'<tr><td><span class="badge skip">SKIP</span></td><td><code>{_e(f.tool)}</code></td>'
                f'<td class="num">{f.calls}</td><td colspan="3" class="muted">{_e(f.skipped)}</td></tr>'
            )
            continue
        if not f.findings:
            rows.append(
                f"<tr><td>{_badge(True)}</td><td><code>{_e(f.tool)}</code></td>"
                f'<td class="num">{f.calls}</td><td colspan="3"></td></tr>'
            )
            continue
        for i, x in enumerate(f.findings):
            first = i == 0
            rows.append(
                f"<tr><td>{_badge(False) if first else ''}</td>"
                f"<td>{'<code>' + _e(f.tool) + '</code>' if first else ''}</td>"
                f'<td class="num">{f.calls if first else ""}</td>'
                f'<td>{_e(x.kind)} <span class="muted">({_e(x.mode)})</span></td>'
                f"<td><code>{_e(_json(x.input)[:500])}</code></td><td>{_e(x.detail)}</td></tr>"
            )
    return f"""<section><h2>Fuzzing <span class="muted">seed {_e(report.fuzz_seed)}</span></h2>
<table><thead><tr><th></th><th>Tool</th><th>Calls</th><th>Finding</th><th>Smallest input</th><th>Details</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table>
<p class="muted">Repeat with <code>--seed {_e(report.fuzz_seed)}</code>.</p></section>"""


def _evals(report: RunReport) -> str:
    ev = report.evals
    if ev is None or not ev.cases:
        return '<section><h2>Tool-selection evals</h2><p class="muted">No evals.</p></section>'
    rows = []
    for c in ev.cases:
        picked = _e(c.picked_tool) if c.picked_tool else '<span class="muted">no tool</span>'
        rows.append(
            f"<tr><td>{_badge(c.passed)}</td><td>{_e(c.prompt)}</td>"
            f"<td><code>{_e(c.expect_tool)}</code></td><td><code>{picked}</code></td>"
            f"<td><code>{_e(_json(c.picked_args)[:300])}</code></td>"
            f"<td>{''.join(f'<div>{_e(m)}</div>' for m in c.failures)}</td></tr>"
        )
    return f"""<section><h2>Tool-selection evals
<span class="muted">{_e(" / ".join(x for x in (ev.provider, ev.model) if x))}</span></h2>
<p>Accuracy <strong>{ev.accuracy:.0%}</strong> ({ev.correct}/{len(ev.cases)}),
minimum {ev.min_accuracy:.0%}.</p>
<table><thead><tr><th></th><th>Prompt</th><th>Expected</th><th>Picked</th><th>Arguments</th><th>Details</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table></section>"""


_CSS = """
:root{--bg:#fff;--fg:#1d2330;--muted:#667085;--line:#e4e7ec;--card:#f8f9fb;
--pass:#13795b;--pass-bg:#e3f6ee;--fail:#b42318;--fail-bg:#fde8e7;--skip:#93370d;--skip-bg:#fef0c7;
--p50:#3b5bdb;--p95:#91a7ff;--p99:#dbe4ff;--code:#f2f4f7}
@media (prefers-color-scheme:dark){:root{--bg:#12151c;--fg:#e6e8ee;--muted:#98a2b3;--line:#2a2f3a;
--card:#1a1e27;--pass:#4ade80;--pass-bg:#12301f;--fail:#f87171;--fail-bg:#3a1414;--skip:#fbbf24;
--skip-bg:#3a2a0a;--p50:#748ffc;--p95:#4c5fa8;--p99:#2c3566;--code:#222733}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
header,main{max-width:1180px;margin:0 auto;padding:0 16px}
header{padding-top:24px}
h1{font-size:22px;margin:0 0 4px}
h2{font-size:17px;margin:28px 0 10px}
.meta,.muted{color:var(--muted)}
.meta{margin:2px 0}
code,pre{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:12.5px}
code{background:var(--code);padding:1px 4px;border-radius:4px;word-break:break-all}
pre{background:var(--code);padding:10px;border-radius:6px;overflow:auto;white-space:pre-wrap;word-break:break-word;margin:6px 0}
pre.err{border-left:3px solid var(--fail)}
table{width:100%;border-collapse:collapse;display:block;overflow-x:auto}
th,td{text-align:left;vertical-align:top;padding:7px 10px;border-bottom:1px solid var(--line)}
th{font-weight:600;color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.03em}
td.num{text-align:right;white-space:nowrap}
.badge{display:inline-block;font-size:11px;font-weight:700;padding:2px 7px;border-radius:999px}
.badge.pass{color:var(--pass);background:var(--pass-bg)}
.badge.fail{color:var(--fail);background:var(--fail-bg)}
.badge.skip{color:var(--skip);background:var(--skip-bg)}
.cards{display:flex;flex-wrap:wrap;gap:12px;margin-top:20px}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 16px;min-width:130px}
.card .value{font-size:22px;font-weight:700}
.card.ok .value{color:var(--pass)}
.card.bad .value{color:var(--fail)}
.card .label{color:var(--muted);font-size:12px}
.bar{height:4px;background:var(--line);border-radius:2px;margin-top:4px;min-width:70px}
.bar span{display:block;height:100%;background:var(--p50);border-radius:2px}
details summary{cursor:pointer;color:var(--muted);font-size:12px}
svg.chart{width:100%;max-width:830px;height:auto;margin:4px 0 12px}
svg .lbl{fill:var(--fg);font-size:12px}
svg .val{fill:var(--muted);font-size:11px}
svg .p50{fill:var(--p50)}svg .p95{fill:var(--p95)}svg .p99{fill:var(--p99)}
"""
