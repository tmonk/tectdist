#!/usr/bin/env python3
"""Check generated benchmark reporting without a third-party test runner."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmarks.runner.report import badge, render

payload = {
    "platform": {"os": "Darwin", "architecture": "arm64"},
    "runs": [{
        "document": "tiny", "scenario": "warm-clean", "claim": True,
        "summary": {"count": 1, "median_difference_ms": -2.0,
                    "ci95_ms": [-2.0, -2.0]},
        "samples": [{"tools": {
            "candidate": {"wall_time_ms": 8.0, "correctness": {"ok": True},
                          "trace_spans": [{"span": "engine.run", "duration_ns": 2_000_000}]},
            "direct-tectonic": {"wall_time_ms": 10.0, "correctness": {"ok": True}},
        }}],
    }],
}

markdown = render([payload])
assert "Claim-corpus aggregate" in markdown
assert "Candidate trace spans" in markdown
assert "engine.run" in markdown
assert "Pass rate: **2/2** samples." in markdown
assert "-2.000" in markdown
assert "8.000 / 8.000" in markdown
assert "10.000 / 10.000" in markdown
assert "-20.00%" in markdown
assert badge([payload])["color"] == "brightgreen"
print("check_benchmark_report: OK")
