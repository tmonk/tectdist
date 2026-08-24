"""Generate Markdown and badge summaries from immutable result bundles."""
import argparse
import json
from pathlib import Path
import statistics

from .statistics import paired_summary, percentile


def differences(run):
    values = []
    for sample in run.get("samples", []):
        tools = sample.get("tools", {})
        candidate = tools.get("candidate", {})
        for name, tool in tools.items():
            if name != "candidate":
                values.append(candidate.get("wall_time_ms", 0) - tool.get("wall_time_ms", 0))
    return values


def timing_summary(run):
    """Summarise both sides and paired percentages without dropping samples."""
    candidate = []
    competitor = []
    percentages = []
    competitor_name = "competitor"
    for sample in run.get("samples", []):
        tools = sample.get("tools", {})
        candidate_value = tools.get("candidate", {}).get("wall_time_ms")
        others = [(name, tool.get("wall_time_ms")) for name, tool in tools.items()
                  if name != "candidate"]
        if candidate_value is None or not others or others[0][1] is None:
            continue
        competitor_name, competitor_value = others[0]
        candidate.append(candidate_value)
        competitor.append(competitor_value)
        if competitor_value:
            percentages.append((candidate_value - competitor_value) / competitor_value * 100)
    return {
        "competitor": competitor_name,
        "candidate_median": statistics.median(candidate) if candidate else None,
        "candidate_p95": percentile(candidate, .95),
        "competitor_median": statistics.median(competitor) if competitor else None,
        "competitor_p95": percentile(competitor, .95),
        "median_percent": statistics.median(percentages) if percentages else None,
    }


def correctness(samples):
    passed = total = 0
    for sample in samples:
        for tool in sample.get("tools", {}).values():
            total += 1
            passed += bool(tool.get("correctness", {}).get("ok"))
    return passed, total


def candidate_spans(samples):
    """Return per-span milliseconds from candidate trace records only."""
    result = {}
    for sample in samples:
        candidate = sample.get("tools", {}).get("candidate", {})
        for span in candidate.get("trace_spans", []):
            name = span.get("span")
            duration = span.get("duration_ns")
            if isinstance(name, str) and isinstance(duration, (int, float)):
                result.setdefault(name, []).append(duration / 1_000_000)
    return result


def render(payloads):
    rows = []
    aggregates = {}
    spans = {}
    passed = total = 0
    for payload in payloads:
        platform = "%s/%s" % (payload.get("platform", {}).get("os", "unknown"),
                               payload.get("platform", {}).get("architecture", "unknown"))
        for run in payload.get("runs", []):
            summary = run.get("summary", {})
            ci = summary.get("ci95_ms", [None, None])
            timings = timing_summary(run)
            rows.append((platform, run.get("document", "unknown"), run.get("scenario", "unknown"),
                         timings["competitor"], summary.get("count", 0),
                         timings["candidate_median"], timings["candidate_p95"],
                         timings["competitor_median"], timings["competitor_p95"],
                         summary.get("median_difference_ms"), timings["median_percent"], ci))
            if run.get("claim"):
                aggregates.setdefault(platform, []).extend(differences(run))
            good, count = correctness(run.get("samples", []))
            passed += good
            total += count
            for name, values in candidate_spans(run.get("samples", [])).items():
                spans.setdefault(platform, {}).setdefault(name, []).extend(values)
    lines = ["# Generated benchmark summary", "",
             "This file is generated from raw paired result bundles; negative differences favour tectdist.",
             "", "| platform | document | scenario | competitor | pairs | tectdist median/p95 ms | competitor median/p95 ms | median Δ ms | median Δ % | 95% CI (ms) |",
             "|---|---|---|---|---:|---:|---:|---:|---:|---|"]
    for (platform, document, scenario, competitor, count, candidate_median,
         candidate_p95, competitor_median, competitor_p95, median, percent, ci) in rows:
        display = "n/a" if median is None else "%.3f" % median
        percent_display = "n/a" if percent is None else "%.2f%%" % percent
        candidate_display = "n/a" if candidate_median is None else "%.3f / %.3f" % (
            candidate_median, candidate_p95)
        competitor_display = "n/a" if competitor_median is None else "%.3f / %.3f" % (
            competitor_median, competitor_p95)
        interval = "n/a" if ci[0] is None else "[%.3f, %.3f]" % (ci[0], ci[1])
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" %
                     (platform, document, scenario, competitor, count,
                      candidate_display, competitor_display, display,
                      percent_display, interval))
    lines.extend(["", "## Claim-corpus aggregate", "",
                  "| platform | pairs | median Δ ms | 95% CI (ms) |",
                  "|---|---:|---:|---|"])
    for platform, values in sorted(aggregates.items()):
        summary = paired_summary(values)
        ci = summary["ci95_ms"]
        lines.append("| %s | %d | %.3f | [%.3f, %.3f] |" %
                     (platform, summary["count"], summary["median_difference_ms"], ci[0], ci[1]))
    lines.extend(["", "## Candidate trace spans", "",
                  "| platform | span | samples | median ms |",
                  "|---|---|---:|---:|"])
    for platform, platform_spans in sorted(spans.items()):
        for name, values in sorted(platform_spans.items()):
            lines.append("| %s | %s | %d | %.3f |" %
                         (platform, name, len(values), statistics.median(values)))
    lines.extend(["", "## Correctness", "", "Pass rate: **%d/%d** samples." % (passed, total)])
    return "\n".join(lines) + "\n"


def badge(payloads):
    passed = total = 0
    for payload in payloads:
        for run in payload.get("runs", []):
            good, count = correctness(run.get("samples", []))
            passed += good
            total += count
    return {"schemaVersion": 1, "label": "tectdist correctness",
            "message": "%d/%d" % (passed, total),
            "color": "brightgreen" if passed == total else "red"}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("results", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--badge-output", type=Path)
    ns = parser.parse_args(argv)
    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in ns.results]
    ns.output.write_text(render(payloads), encoding="utf-8")
    if ns.badge_output:
        ns.badge_output.write_text(json.dumps(badge(payloads), indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
