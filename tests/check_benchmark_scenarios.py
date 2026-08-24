#!/usr/bin/env python3
"""Exercise deterministic benchmark scenario preparation."""
import tempfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmarks.runner.cli import (_resource_metrics, _stage_counts, command_for,
                                   competitor_applicable)
from benchmarks.runner.scenarios import environment, prepare


with tempfile.TemporaryDirectory(prefix="tectdist-scenarios-") as temporary:
    root = Path(temporary)
    source = root / "source"
    source.mkdir()
    (source / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nbase\n\\end{document}\n",
        encoding="utf-8")

    small = root / "small"
    prepare(source, small, "source-small-edit", "main.tex")
    assert "small benchmark edit" in (small / "main.tex").read_text(encoding="utf-8")

    structural = root / "structural"
    prepare(source, structural, "source-structural-edit", "main.tex")
    text = (structural / "main.tex").read_text(encoding="utf-8")
    assert text.index("Deterministic benchmark structural edit") < text.index("\\end{document}")

    cold = root / "cold"
    cold.mkdir()
    env = environment(cold, "cold-empty-cache", {})
    assert Path(env["XDG_CACHE_HOME"]).is_dir()
    assert env["TECTONIC_CACHE_DIR"] == env["XDG_CACHE_HOME"]

passes, tools = _stage_counts([
    {"span": "engine.run"}, {"span": "indexer.run"},
    {"span": "engine.rerun_after_index"},
])
assert (passes, tools) == (2, 1)
resources = _resource_metrics([
    {"span": "package.download", "duration_ns": 2_000_000},
    {"span": "package.decompress", "duration_ns": 3_000_000},
], {"TECTDIST_BYTES_DOWNLOADED": "4096"})
assert resources == {
    "download_observed": True, "bytes_downloaded": 4096,
    "download_duration_ms": 2.0, "decompression_duration_ms": 3.0,
    "measurement": "trace-and-explicit-counter",
}
estimated = _resource_metrics([], {}, 2048)
assert estimated["bytes_downloaded"] == 2048
assert estimated["download_observed"] is True
assert estimated["measurement"] == "cache-growth-estimate"
assert command_for("candidate", ["candidate"], "main.tex", {"requires_shell_escape": True}) == [
    "candidate", "-shell-escape", "main.tex"]
assert command_for("direct-tectonic", ["tectonic"], "main.tex", {"requires_shell_escape": True}) == [
    "tectonic", "--keep-intermediates", "--keep-logs", "-Z", "shell-escape", "main.tex"]
assert not competitor_applicable("direct-tectonic", {"requires_index": True})
assert not competitor_applicable("direct-tectonic", {"requires_glossary": True})
assert competitor_applicable("direct-tectonic", {"requires_bibliography": True})
assert competitor_applicable("texlive-latexmk", {"requires_index": True})

print("check_benchmark_scenarios: OK")
