#!/usr/bin/env python3
import sys
from pathlib import Path

try:
    import tomllib
except ImportError:
    print("check_benchmark_manifest: SKIPPED (requires Python 3.11 TOML parser)")
    raise SystemExit(0)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmarks.runner.cli import manifest
from benchmarks.runner.manifest import validate

ROOT = Path(__file__).resolve().parents[1]
errors = validate(manifest(ROOT / "benchmarks/corpus/manifest.toml"), ROOT / "benchmarks")
if errors:
    raise SystemExit("benchmark manifest invalid:\n- " + "\n- ".join(errors))

# The optional external workload remains fetch-free during tests, but its pinned
# metadata must stay aligned with the downloader and outside claim aggregation.
external_path = ROOT / "benchmarks/external-manifests/itp3-qft.toml"
external = tomllib.loads(external_path.read_text(encoding="utf-8"))
from scripts.fetch_itp3_fixture import FILES
assert external["corpus_kind"] == "external"
assert external["fixture_bytes"] == 742_627
assert len(FILES) == 21
assert len(external["document"]) == 1
assert external["document"][0]["claim"] is False
assert external["document"][0]["expected_pages"] == 51
print("check_benchmark_manifest: OK")
