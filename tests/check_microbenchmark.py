#!/usr/bin/env python3
"""Validate the standalone startup microbenchmark payload."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="tectdist-micro-") as temporary:
    output = Path(temporary) / "micro.json"
    subprocess.run(
        [sys.executable, "-m", "benchmarks.runner.micro", "--warmups", "0",
         "--trials", "3", "--output", str(output), "--command", "/usr/bin/true"],
        cwd=ROOT, check=True)
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["kind"] == "microbenchmark"
    assert len(payload["samples_ms"]) == 3
    assert payload["summary"]["count"] == 3
    assert payload["summary"]["p50_ms"] >= 0

print("check_microbenchmark: OK")
