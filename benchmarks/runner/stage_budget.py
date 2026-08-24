"""Per-document stage budget report (plan X1.4).

Consumes benchmark result bundles containing traced diagnostics
(``--diagnose`` runs) and reports how much of each candidate process's wall
time is assigned to named trace stages. Spans are merged into non-overlapping
intervals before comparison against ``process.total``, so nested parents never
double-count.

A stage optimisation issue may only enter implementation once its target
consumes at least 5% of aggregate corpus time, 10% of a claim-relevant
workload, or 5 ms on the tiny path; this report is the evidence source.

Usage:
    python -m benchmarks.runner.stage_budget RESULT.json [RESULT.json ...] \
        [--min-coverage 95.0]

Exits 1 when any reported document falls below --min-coverage.
"""
import argparse
import json

EXCLUDED_ROOT_SPANS = {"process.total"}


def merge_intervals(records):
    """Merge [start_ns, end_ns] pairs into disjoint sorted intervals."""
    intervals = sorted((r["start_ns"], r["start_ns"] + r.get("duration_ns", 0))
                       for r in records)
    merged = []
    for start, end in intervals:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def coverage(diagnostic):
    """Return (total_ms, covered_ms, per-span medians) for one diagnostic."""
    spans = diagnostic.get("trace_spans", [])
    total = next((r.get("duration_ns", 0) for r in spans
                  if r.get("span") == "process.total"), None)
    named = [r for r in spans if r.get("span") not in EXCLUDED_ROOT_SPANS]
    merged = merge_intervals(named)
    covered = sum(end - start for start, end in merged)
    per_span = {}
    for record in named:
        per_span.setdefault(record.get("span"), []).append(
            record.get("duration_ns", 0))
    return total, covered, per_span


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", nargs="+")
    parser.add_argument("--min-coverage", type=float, default=95.0)
    ns = parser.parse_args(argv)

    failures = []
    print("| document | samples | process.total median ms | named-stage coverage | below gate |")
    print("|---|---:|---:|---:|---|")
    seen = set()
    for path in ns.results:
        payload = json.load(open(path, encoding="utf-8"))
        for run in payload.get("runs", []):
            diagnostics = run.get("traced_diagnostics", [])
            if not diagnostics:
                continue
            document = run.get("document", "unknown")
            totals = []
            coverages = []
            span_totals = {}
            for diagnostic in diagnostics:
                candidate = diagnostic.get("tools", {}).get("candidate", {})
                total, covered, per_span = coverage(candidate)
                if not total:
                    continue
                totals.append(total)
                coverages.append(covered / total * 100)
                for name, values in per_span.items():
                    span_totals.setdefault(name, []).extend(values)
            if not totals:
                continue
            import statistics
            key = (document, run.get("scenario"))
            if key in seen:
                continue
            seen.add(key)
            median_total_ms = statistics.median(totals) / 1_000_000
            mean_coverage = statistics.mean(coverages)
            below = mean_coverage < ns.min_coverage
            if below:
                failures.append((key, mean_coverage))
            print("| %s %s | %d | %.1f | %.2f%% | %s |" %
                  (document, key[1], len(totals), median_total_ms,
                   mean_coverage, "YES" if below else ""))
            for name, values in sorted(span_totals.items(),
                                       key=lambda item: -statistics.median(item[1])):
                share = statistics.median(values) / 1_000_000
                print("  - %-32s median %8.3f ms" % (name, share))
    if failures:
        print("\nstage budget FAILED: %d document(s) below %.1f%% coverage" %
              (len(failures), ns.min_coverage))
        raise SystemExit(1)
    print("\nstage budget passed")


if __name__ == "__main__":
    main()
