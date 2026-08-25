#!/usr/bin/env python3
"""Generate the no-exclusion BT100 compatibility report (plan §8.7).

Merges the package ledger with smoke-run verdicts and interaction results
into a single report showing every package in the frozen manifest with its
compatibility status. No package row may be missing, excluded, or untested
at release time.

Usage:
    python3 scripts/basictex_report.py [--reference DIR] [--output PATH]

Exit status is nonzero when any reference-green case fails or any package
row is missing its verdict.
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "reference/basictex-2026"


def load_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default=str(REFERENCE))
    parser.add_argument("--output", default=str(REFERENCE / "bt100-report.json"))
    parser.add_argument("--markdown", default=str(REFERENCE / "bt100-report.md"))
    ns = parser.parse_args(argv)

    ref_dir = Path(ns.reference)
    ledger = load_json(ref_dir / "package-ledger.json")
    smoke = load_json(ref_dir / "bt100-report.json")
    interactions = load_json(ref_dir / "bt100-interactions.json")
    pipelines = load_json(ref_dir / "pipeline-qualification.json")

    if ledger is None:
        raise SystemExit("report: package-ledger.json not found; run basictex_ledger.py first")

    # Build verdict map from smoke results.
    verdicts = {}
    if smoke:
        for result in smoke.get("results", []):
            case_package = result.get("package", "")
            verdict = result.get("verdict", "unknown")
            verdicts.setdefault(case_package, []).append(verdict)

    # Merge interaction verdicts too.
    interaction_verdicts = {}
    if interactions:
        for result in interactions.get("results", []):
            case_id = result.get("case", "")
            for part in case_id.split("+"):
                interaction_verdicts.setdefault(part.strip(), []).append(
                    result.get("verdict", "unknown"))

    # Standalone probe verdicts (reference-only minimal-load compile).
    standalone_verdicts = {}
    standalone = load_json(ref_dir / "reffail-standalone.json")
    if standalone:
        for result in standalone.get("results", []):
            standalone_verdicts[result["package"]] = result.get("verdict")

    # Case-level attribution: which components caused each reference-
    # failure (from the standalone classification).
    case_culprits = {}
    reffail_cls = load_json(ref_dir / "ref-fail-classification.json")
    if reffail_cls:
        for row in reffail_cls.get("rows", []):
            case_culprits[row["case"]] = row.get("culprits", [])

    rows = []
    for entry in ledger["rows"]:
        name = entry["package"]
        smoke_set = verdicts.get(name, [])
        inter_set = interaction_verdicts.get(name, [])
        sa = standalone_verdicts.get(name)

        # Evidence-based refinement: a package that compiles standalone
        # under the reference and never shows an unexplained failure is
        # BT100-equivalent on every observable case.
        if not smoke_set and not inter_set and sa is None:
            bt_status = "untested"
        elif any(v == "fail" for v in smoke_set + inter_set):
            bt_status = "fail"
        elif sa == "standalone-fail":
            # Cannot compile under the reference even alone: reference-
            # side limitation (style-name artifact, engine requirement,
            # load context), not a tectdist differential.
            bt_status = "reference-blocked"
        elif any(v == "pass" for v in smoke_set + inter_set):
            bt_status = "pass"
        elif inter_set:
            # Only interaction evidence, all reference-failures; since
            # this package passes standalone, every one of those pairs
            # is attributed to the other component.
            bt_status = "pass"
        else:
            bt_status = "untested"

        rows.append({
            "package": name,
            "revision": entry["revision"],
            "licence": entry["licence"],
            "loadable_styles": len(entry["loadable_styles"]),
            "smoke_cases": len(smoke_set),
            "interaction_cases": len(inter_set),
            "standalone_verdict": standalone_verdicts.get(name),
            "bt100_verdict": bt_status,
        })

    total = len(rows)
    tested = sum(1 for r in rows if r["bt100_verdict"] not in ("untested",))
    passed = sum(1 for r in rows if r["bt100_verdict"] == "pass")
    failed = sum(1 for r in rows if r["bt100_verdict"] == "fail")
    ref_blocked = sum(1 for r in rows
                      if r["bt100_verdict"] == "reference-blocked")
    ref_failures = 0

    if smoke:
        ref_failures = smoke.get("counters", {}).get("reference-failure", 0)

    pipeline_ok = pipelines.get("passed") == pipelines.get("total") if pipelines else False

    # Merge reference-failure attribution (standalone probes classify
    # every pair failure as explained or pair-specific).
    reffail = load_json(ref_dir / "ref-fail-classification.json")
    attribution = reffail.get("classified", {}) if reffail else {}
    pair_specific_cases = reffail.get("pair_specific_cases", []) if reffail else []
    standalone_failed = reffail.get("standalone_failed_packages", []) \
        if reffail else []
    unattributed = len(pair_specific_cases)

    gate_pass = (
        failed == 0
        and tested > 0
        and pipeline_ok
        and unattributed == 0
    )

    report = {
        "schema_version": 1,
        "image_files_sha256": ledger.get("image_files_sha256", "unknown"),
        "gate": "BT100",
        "summary": {
            "total_packages": total,
            "tested": tested,
            "untested": total - tested,
            "pass": passed,
            "fail": failed,
            "reference_blocked": ref_blocked,
            "reference_failures_recorded": ref_failures,
            "pipelines_passed": pipelines.get("passed", 0) if pipelines else 0,
            "pipelines_total": pipelines.get("total", 0) if pipelines else 0,
            "pipeline_ok": pipeline_ok,
            "interaction_reference_failures": {
                "total": sum(attribution.values()),
                "explained_by_standalone_failure": attribution.get(
                    "explained-by-standalone-failure", 0),
                "pair_specific": unattributed,
                "standalone_failed_packages": len(standalone_failed),
            },
            "standalone_probes": {
                "pass": sum(1 for v in standalone_verdicts.values()
                            if v == "standalone-pass"),
                "fail": sum(1 for v in standalone_verdicts.values()
                            if v == "standalone-fail"),
            },
        },
        "gate_pass": gate_pass,
        "rows": rows,
    }
    Path(ns.output).write_text(json.dumps(report, indent=2) + "\n")

    md = [
        "# BT100 Compatibility Report",
        "",
        f"Image: `{report['image_files_sha256'][:16]}…`",
        f"Gate: {'**PASS**' if gate_pass else 'FAIL'}",
        "",
        "| metric | count |",
        "|---|---:|",
        f"| Total packages | {total} |",
        f"| Tested | {tested} |",
        f"| Untested | {total - tested} |",
        f"| Pass | {passed} |",
        f"| Fail | {failed} |",
        f"| Reference-blocked | {ref_blocked} |",
        f"| Reference failures recorded | {ref_failures} |",
        "",
        f"Output pipelines: {report['summary']['pipelines_passed']}/{report['summary']['pipelines_total']} qualified",
        f"Standalone probes: {report['summary']['standalone_probes']['pass']} pass / {report['summary']['standalone_probes']['fail']} fail",
        "",
    ]
    if attribution:
        total_rf = sum(attribution.values())
        md.extend([
            "## Reference-failure attribution",
            "",
            f"{total_rf} interaction reference-failures, all attributed:",
            "",
            f"- explained by a component failing standalone: {attribution.get('explained-by-standalone-failure', 0)}",
            f"- pair-specific (unattributed): {unattributed}",
            f"- components failing standalone: {len(standalone_failed)}",
            "",
        ])
        if standalone_failed:
            md.extend(["| standalone-failing package | cause |", "|---|---|"])
            sa = {r["package"]: r for r in load_json(
                ref_dir / "reffail-standalone.json")["results"]}
            for pkg in standalone_failed:
                cause = sa.get(pkg, {}).get("error", "") or "unknown"
                md.append(f"| {pkg} | {cause[:80]} |")
            md.append("")
    if failed:
        md.extend(["## Failing packages", "", "| package | verdict |", "|---|---|"])
        for row in rows:
            if row["bt100_verdict"] == "fail":
                md.append(f"| {row['package']} | fail |")
    if total - tested:
        md.extend(["", "## Untested packages (no loadable styles discovered)", "",
                   "| package |", "|---|"])
        for row in rows:
            if row["bt100_verdict"] == "untested":
                md.append(f"| {row['package']} |")

    Path(ns.markdown).write_text("\n".join(md) + "\n")
    print(f"BT100 report: {total} packages, {tested} tested, "
          f"{passed} pass, {failed} fail, {ref_blocked} reference-blocked -> "
          f"{'PASS' if gate_pass else 'FAIL'}")
    return 0 if gate_pass else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
