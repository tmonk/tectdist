# Benchmarks

Performance evidence is generated from the compact, versioned corpus in
`benchmarks/corpus/manifest.toml`. A benchmarked compile counts only when the
layered oracle accepts its PDF; cold and warm scenarios are separate.

Run a local paired smoke comparison against direct Tectonic:

```sh
TECTONIC="$(command -v tectonic)" \
TECTDIST_BENCH_DIRECT_TECTONIC="$(command -v tectonic)" \
python -m benchmarks.runner.cli --candidate ./bin/tectdist \
  --document tiny --scenario warm-clean --trials 3 --warmups 1 \
  --output benchmark-results/smoke.json
python -m benchmarks.runner.report benchmark-results/smoke.json \
  --output benchmark-results/summary.md \
  --badge-output benchmark-results/badge.json
```

Measure a startup/dispatch budget separately from a document compile:

```sh
python -m benchmarks.runner.micro --trials 30 --warmups 5 \
  --output benchmark-results/native-version.json \
  --command ./target/release/tectdist --version
```

An optional real-world stress workload is pinned from the University of
Stuttgart ITP3 QFT benchmark. It is 742,627 bytes, stays outside the default
claim aggregate, and is fetched only on request:

```sh
python3 scripts/fetch_itp3_fixture.py
TECTDIST_BENCH_DIRECT_TECTONIC="$(command -v tectonic)" \
python3 -m benchmarks.runner.cli \
  --manifest benchmarks/external-manifests/itp3-qft.toml \
  --candidate ./target/release/tectdist --scenario warm-clean \
  --trials 3 --warmups 1 --output benchmark-results/itp3-smoke.json
```

For qualification, use the declared corpus scenarios, at least 30 paired
trials for ordinary documents, independent sessions, and explicitly configured
competitors. Invoke `--qualification` with `TECTDIST_BUNDLE_SOURCE`,
`TECTDIST_BUNDLE_ID`, `TECTDIST_BUNDLE_MANIFEST_SHA256`, and
`TECTDIST_FORMAT_CACHE_ID` set to immutable values; it rejects weak trial
counts or missing provenance. A `cold-empty-cache` run must also declare
either `--cold-source controlled-local` or `--cold-source public-network` so
network observations cannot be presented as compiler-only measurements. The
raw JSON records tool and bundle identity, binary size, platform, randomised
order, timing, CPU/RSS where available, process-count provenance, trace
spans, download/decompression observations, correctness results, hashes, and
bootstrap confidence intervals. Generated tables include both tools' medians
and p95 values plus paired absolute and percentage differences.

Direct Tectonic is not an index/glossary orchestrator, so those cases are not
misrepresented as direct-engine comparisons; qualification compares them with
the previous tectdist release and TeX Live latexmk instead. Direct Tectonic
remains required and visible for every applicable engine-only workload.

Do not add hand-maintained percentages or broad product claims here. Publish
only generated summaries backed by immutable raw bundles, and scope any claim
to its platform, corpus, cache state, and competitors.
