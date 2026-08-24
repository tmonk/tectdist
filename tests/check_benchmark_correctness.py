#!/usr/bin/env python3
"""Exercise required bibliography/index completion checks without a PDF toolchain."""
import tempfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmarks.runner.correctness import validate


with tempfile.TemporaryDirectory(prefix="tectdist-oracle-") as temporary:
    root = Path(temporary)
    pdf = root / "main.pdf"
    pdf.write_bytes(b"not-a-real-pdf")

    # A missing PDF parser makes the structural check fail too, but the stage
    # failure must remain visible so a benchmark cannot pass after skipping it.
    missing = validate(str(pdf), requires_bibliography=True, requires_index=True,
                       requires_glossary=True)
    assert any("bibliography output" in error for error in missing["errors"])
    assert any("index output" in error for error in missing["errors"])
    assert any("glossary output" in error for error in missing["errors"])

    (root / "main.bbl").write_text("bibliography", encoding="utf-8")
    (root / "main.ind").write_text("index", encoding="utf-8")
    (root / "main.gls").write_text("glossary", encoding="utf-8")
    present = validate(str(pdf), requires_bibliography=True, requires_index=True,
                       requires_glossary=True, requires_shell_escape=True,
                       log_text="running shell command")
    assert not any("output is missing" in error for error in present["errors"])
    assert present["stages"] == {"bibliography": True, "index": True, "glossary": True,
                                  "shell_escape": True}

print("check_benchmark_correctness: OK")
