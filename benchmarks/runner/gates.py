"""Baseline regression gates for benchmark result bundles (plan X0.5).

Compares a current result bundle against an accepted baseline and fails when:

- any correctness oracle fails,
- the claim-corpus aggregate p50 regresses by more than max(threshold, noise
  floor),
- aggregate p95 regresses by more than its threshold,
- a stage count increases unexpectedly, or
- a claimed fast path now spawns external tools it previously avoided.

Usage:
    python -m benchmarks.runner.gates --baseline BASELINE.json --current CURRENT.json \
        [--noise-floor-pct 1.0] [--p50-threshold-pct 3.0] [--p95-threshold-pct 5.0]

Exits 0 when every gate passes; exits 1 listing violations otherwise.
"""
import argparse
import json
import statistics

from .report import timing_summary


def run_key(run):
    return (run.get("document"), run.get("scenario"),
            run.get("tool", {}).get("competitor", {}).get("name"))


def index_runs(payload):
    return {run_key(run): run for run in payload.get("runs", [])}


def sample_values(run, tool_name):
    values = []
    for sample in run.get("samples", []):
        value = sample.get("tools", {}).get(tool_name, {}).get("wall_time_ms")
        if value is not None:
            values.append(value)
    return values


def median_stage_count(run, tool_name, field):
    values = [sample.get("tools", {}).get(tool_name, {}).get(field)
              for sample in run.get("samples", [])]
    values = [value for value in values if isinstance(value, (int, float))]
    return statistics.median(values) if values else None


def check_gates(baseline, current, noise_floor_pct, p50_threshold_pct, p95_threshold_pct):
    """Return a list of human-readable gate violations."""
    failures = []
    base_runs = index_runs(baseline)
    current_runs = index_runs(current)

    # Gate: every correctness oracle passes in the current bundle.
    for key, run in sorted(current_runs.items()):
        for pair_index, pair in enumerate(run.get("samples", [])):
            for name, tool in pair.get("tools", {}).items():
                correctness = tool.get("correctness", {})
                if not correctness.get("ok"):
                    failures.append(
                        "correctness failure %s sample %d tool %s: %s" %
                        (key, pair_index, name, "; ".join(correctness.get("errors", []))))

    # Timing gates over claim-corpus runs present in both bundles.
    regressions_p50 = []
    regressions_p95 = []
    stage_regressions = []
    fallback_regressions = []
    aggregate_base_median = 0.0
    aggregate_current_median = 0.0
    aggregate_base_p95 = 0.0
    aggregate_current_p95 = 0.0
    compared = 0
    for key, base_run in sorted(base_runs.items()):
        current_run = current_runs.get(key)
        if current_run is None or not base_run.get("claim"):
            continue
        competitor = key[2]
        base_candidate = sample_values(base_run, "candidate")
        current_candidate = sample_values(current_run, "candidate")
        if not base_candidate or not current_candidate:
            continue
        from .statistics import percentile
        base_median = statistics.median(base_candidate)
        current_median = statistics.median(current_candidate)
        base_p95 = percentile(base_candidate, .95)
        current_p95 = percentile(current_candidate, .95)
        aggregate_base_median += base_median
        aggregate_current_median += current_median
        aggregate_base_p95 += base_p95
        aggregate_current_p95 += current_p95
        compared += 1
        if base_median > 0 and (current_median - base_median) / base_median * 100 > \
                max(p50_threshold_pct, noise_floor_pct):
            regressions_p50.append("%s: %.1fms -> %.1fms (+%.1f%%)" %
                                   (key, base_median, current_median,
                                    (current_median - base_median) / base_median * 100))
        if base_p95 > 0 and (current_p95 - base_p95) / base_p95 * 100 > p95_threshold_pct:
            regressions_p95.append("%s: %.1fms -> %.1fms (+%.1f%%)" %
                                   (key, base_p95, current_p95,
                                    (current_p95 - base_p95) / base_p95 * 100))
        for field in ("engine_pass_count", "external_tool_count"):
            base_stages = median_stage_count(base_run, "candidate", field)
            current_stages = median_stage_count(current_run, "candidate", field)
            if base_stages is not None and current_stages is not None \
                    and current_stages > base_stages:
                target = (stage_regressions if field == "engine_pass_count"
                          else fallback_regressions)
                target.append("%s: %s median %.0f -> %.0f" %
                              (key, field, base_stages, current_stages))

    if compared:
        effective_floor = max(p50_threshold_pct, noise_floor_pct)
        if aggregate_base_median > 0:
            delta = (aggregate_current_median - aggregate_base_median) / aggregate_base_median * 100
            if delta > effective_floor:
                failures.append(
                    "aggregate p50 regressed %.2f%% (> %.2f%%): %.1fms -> %.1fms" %
                    (delta, effective_floor, aggregate_base_median, aggregate_current_median))
        if aggregate_base_p95 > 0:
            delta = (aggregate_current_p95 - aggregate_base_p95) / aggregate_base_p95 * 100
            if delta > p95_threshold_pct:
                failures.append(
                    "aggregate p95 regressed %.2f%% (> %.2f%%): %.1fms -> %.1fms" %
                    (delta, p95_threshold_pct, aggregate_base_p95, aggregate_current_p95))
    failures.extend("per-document p50 regression " + item for item in regressions_p50)
    failures.extend("per-document p95 regression " + item for item in regressions_p95)
    failures.extend("unexpected stage-count increase " + item for item in stage_regressions)
    failures.extend("unexpected fast-path fallback " + item for item in fallback_regressions)
    missing_claim = sorted(set(key for key, run in base_runs.items() if run.get("claim")) -
                           set(current_runs))
    if missing_claim:
        failures.append("claim-corpus documents missing from current results: " +
                        ", ".join(str(key) for key in missing_claim))
    return failures


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--current", required=True)
    parser.add_argument("--noise-floor-pct", type=float, default=1.0)
    parser.add_argument("--p50-threshold-pct", type=float, default=3.0)
    parser.add_argument("--p95-threshold-pct", type=float, default=5.0)
    ns = parser.parse_args(argv)
    baseline = json.loads(open(ns.baseline, encoding="utf-8").read())
    current = json.loads(open(ns.current, encoding="utf-8").read())
    failures = check_gates(baseline, current, ns.noise_floor_pct,
                           ns.p50_threshold_pct, ns.p95_threshold_pct)
    if failures:
        print("benchmark gates FAILED:")
        for failure in failures:
            print("- " + failure)
        raise SystemExit(1)
    print("benchmark gates passed")


if __name__ == "__main__":
    main()
