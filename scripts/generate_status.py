#!/usr/bin/env python3
"""Generate docs/STATUS.md from machine-readable gate artefacts.

Plan O100-001 / M0: status documentation must be generated from gate
artefacts rather than hand-maintained. Hand-written status documents
(docs/BT100_STATUS.md) are frozen historical snapshots.

Sources consumed when present:
  reference/release-gate.json       release-gate stage results
  reference/bt100-report.json       package probe report summary
  reference/x2-edit-scenarios.json  edit-scenario speedups
  reference/baseline-denominators-basictex-corpus.json
                                    oracle timing denominators

Missing artefacts are reported as "no evidence" rather than guessed.
Exit code is 0 even when artefacts are missing (generation succeeds);
the rendered status itself states what is unproven.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REF = ROOT / "reference"
OUT = ROOT / "docs" / "STATUS.md"


def git_head() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT,
            capture_output=True, text=True, timeout=10,
        ).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def load(name: str):
    path = REF / name
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception as error:
        return {"_error": str(error)}


def render_release_gate(data) -> list[str]:
    lines = ["## Release gate", ""]
    if data is None:
        lines += ["No `reference/release-gate.json` artefact found — "
                  "run `python3 scripts/basictex_release_gate.py`.", ""]
        return lines
    if "_error" in data:
        lines += [f"Artefact unreadable: {data['_error']}", ""]
        return lines
    stages = data.get("stages", [])
    overall = data.get("overall")
    lines.append(f"Overall: **{overall}**" if overall else "Overall: unknown")
    lines += ["", "| stage | status | detail |", "|---|---|---|"]
    for stage in stages:
        detail = str(stage.get("detail", "")).replace("|", "\\|")
        lines.append(f"| {stage.get('stage')} | {stage.get('status')} "
                     f"| {detail} |")
    lines.append("")
    return lines


def render_report(data) -> list[str]:
    lines = ["## Package probe report", ""]
    if data is None:
        lines += ["No `reference/bt100-report.json` artefact found — "
                  "run `python3 scripts/basictex_report.py`.", ""]
        return lines
    if "_error" in data:
        lines += [f"Artefact unreadable: {data['_error']}", ""]
        return lines
    summary = data.get("summary", {})
    for key in ("pass", "fail", "reference_blocked", "untested"):
        if key in summary:
            lines.append(f"- {key}: {summary[key]}")
    lines.append(f"- gate_pass: {data.get('gate_pass')}")
    lines.append("")
    return lines


def render_edits(data) -> list[str]:
    lines = ["## Edit scenarios (vs stock one-shot)", ""]
    if data is None:
        lines += ["No `reference/x2-edit-scenarios.json` artefact found — "
                  "run `python3 scripts/basictex_x2_edit_scenarios.py`.", ""]
        return lines
    if "_error" in data:
        lines += [f"Artefact unreadable: {data['_error']}", ""]
        return lines
    rows = [
        ("unchanged rebuild", data.get("speedup_unchanged_vs_stock")),
        ("body edit", data.get("speedup_body_edit_vs_stock")),
    ]
    scenarios = data.get("scenarios", {})
    stock = scenarios.get("stock-one-shot")
    structural = scenarios.get("structural-edit-format-reused")
    if isinstance(stock, (int, float)) and isinstance(structural, (int, float)):
        rows.append(("structural edit (format reused)",
                     round(stock / max(structural, 1), 3)))
    lines += ["| scenario | speedup | X10 gate (>=10x) |", "|---|---|---|"]
    for name, value in rows:
        if isinstance(value, (int, float)):
            gate = "PASS" if value >= 10.0 else "FAIL"
            lines.append(f"| {name} | {value}x | {gate} |")
        else:
            lines.append(f"| {name} | no evidence | — |")
    lines += ["", "Warm-clean: no evidence yet (X10-C not implemented; "
              "see BASICTEX_X10_PLAN.md §9.4).", ""]
    return lines


def main() -> int:
    parts = [
        "# tectdist Programme Status",
        "",
        "**GENERATED FILE — do not edit by hand.**",
        f"Rendered by `scripts/generate_status.py` at "
        f"{datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"Git head at generation time: `{git_head()}`",
        "",
        "Canonical plan: `docs/BASICTEX_X10_PLAN.md`. Historical hand-written",
        "status (`docs/BT100_STATUS.md`) is frozen and non-authoritative.",
        "",
    ]
    parts += render_release_gate(load("release-gate.json"))
    parts += render_report(load("bt100-report.json"))
    parts += render_edits(load("x2-edit-scenarios.json"))
    OUT.write_text("\n".join(parts))
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
