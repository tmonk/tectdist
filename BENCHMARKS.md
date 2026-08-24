# Benchmarks

The new native Rust implementation has the lowest aggregate complete-build
latency on the compact project corpus: **3.497 seconds versus 4.100 seconds for
TeX Live `latexmk`, a 14.71% reduction**. The paired bootstrap 95% confidence
interval for the suite difference is -615 to -543 milliseconds. All 420 timed
outputs passed the correctness oracle.

The precise claim supported by these results is:

> On the seven-project `tectdist` corpus, on Apple M3 Max/macOS arm64, the new
> native Rust implementation is the fastest measured complete implementation
> in aggregate against TeX Live 2026 `latexmk`.

This is not a claim that Rust wins every individual workload. TeX Live is
faster on the deliberately tiny startup-dominated document and the index case;
Rust wins the other five documents and the aggregate.

## Compact corpus result

The scenario is `warm-clean`: dependencies are available, but each timed
sample starts from a clean project output directory and must produce a complete
PDF. Negative differences favour the Rust candidate.

| Document | Pairs | Rust median / p95 (ms) | TeX Live median / p95 (ms) | Median difference | Result |
|---|---:|---:|---:|---:|---|
| `tiny` | 30 | 166.858 / 171.953 | 129.843 / 134.463 | +36.673 ms | TeX Live |
| `references` | 30 | 173.877 / 224.802 | 193.544 / 299.937 | -20.967 ms | Rust |
| `paper` | 30 | 351.175 / 714.696 | 496.228 / 648.517 | -133.016 ms | Rust |
| `bibtex` | 30 | 218.427 / 302.337 | 382.467 / 818.593 | -165.874 ms | Rust |
| `biblatex` | 30 | 1996.432 / 2822.383 | 2353.660 / 2673.181 | -335.404 ms | Rust |
| `index` | 30 | 340.426 / 484.394 | 264.738 / 309.240 | +74.628 ms | TeX Live |
| `thesis` | 30 | 249.949 / 492.952 | 279.712 / 565.250 | -32.761 ms | Rust |
| **Aggregate** | **210** | **3497.144 / 5213.518** | **4100.192 / 5449.181** | **-603.047 ms (-14.71%)** | **Rust** |

The aggregate is the sum of per-document medians and p95 values so every
project has equal weight. Its interval is bootstrapped over paired samples
within each project, then summed: **[-614.528, -543.497] ms**.

## Stuttgart ITP3 QFT stress result

The optional fixture pins the University of Stuttgart ITP3 QFT source at
742,627 bytes and 21 files. It exercises a much larger equation-, box-, and
TikZ-heavy document than the default corpus.

| Workload | Pairs | Rust complete build | TeX Live `latexmk` complete build | Difference | Correct outputs |
|---|---:|---:|---:|---:|---:|
| ITP3 QFT | 1 | 41.548 s | 49.189 s | -7.641 s (-15.53%) | 2/2 |

This is intentionally a **quick smoke result**, not a statistical
qualification: it is one paired clean build and was recorded while the
benchmark-harness fixes were uncommitted. It shows the same direction as the
corpus aggregate without pretending that a 15- or 30-pair QFT run belongs in a
quick developer loop.

The [official Stuttgart benchmark](https://web.itp3.uni-stuttgart.de/latex-benchmark/)
first prepares the document and then times three individual `pdflatex` passes.
Those published CPU scores therefore measure a different operation and are not
mixed into this complete clean-build comparison.

## What was compared

Only independent complete implementations appear in the headline comparison:

- Candidate: this branch's new native Rust `tectdist`, binary SHA-256
  `c46f19bce9a448688f0d8e29e68c882ff5f83ec4b4c03d6a766e556b09d2acce`.
- Competitor: TeX Live 2026 `latexmk` 4.88 with pdfTeX 1.40.29, Biber 2.22,
  BibTeX 0.99e, and MakeIndex.
- Machine: Apple M3 Max, 16 cores, 128 GB RAM, macOS arm64.
- Candidate bundle ID:
  `6ffe055852f8faf66c0acbe1a7fb27f87b869a90bad1204f3bf4d9683f597c7c`.
- TeX Live package manifest SHA-256:
  `2d96c645b85c8b0d0eb5ebc2329f45abf023e04e5ce4b0647a0435637396e81b`.

The previous `tectdist` release and direct Tectonic are same-product or
same-engine controls. The runner can still use them for diagnostics, but they
are excluded from the product-performance claim. Qualification of that claim
requires the independent TeX Live control.

## Quick local benchmark

The default developer check uses three pairs, no warmups, and all seven compact
documents. The command below completed in **26.27 seconds** on the reference
machine and is intended to stay below 30 seconds there:

```sh
cargo build --release --locked

TEXLIVE_BIN=/path/to/texlive/bin
PATH="$PWD/dist/native-bin:$PATH" \
TECTDIST_BENCH_LATEXMK="/usr/bin/env PATH=$TEXLIVE_BIN:/usr/bin:/bin $TEXLIVE_BIN/latexmk -silent" \
python3 -m benchmarks.runner.cli \
  --candidate ./target/release/tectdist \
  --document tiny --document references --document paper \
  --document bibtex --document biblatex --document index --document thesis \
  --scenario warm-clean --trials 3 --warmups 0 \
  --output benchmark-results/quick-rust-vs-texlive.json
```

The QFT fixture is opt-in because even one sequential pair takes about 90
seconds on the reference machine, although each implementation's complete
build is individually below 50 seconds:

```sh
python3 scripts/fetch_itp3_fixture.py

PATH="$PWD/dist/native-bin:$PATH" \
TECTDIST_BENCH_LATEXMK="/usr/bin/env PATH=$TEXLIVE_BIN:/usr/bin:/bin $TEXLIVE_BIN/latexmk -silent" \
python3 -m benchmarks.runner.cli \
  --manifest benchmarks/external-manifests/itp3-qft.toml \
  --candidate ./target/release/tectdist --scenario warm-clean \
  --trials 1 --warmups 0 --output benchmark-results/itp3-smoke.json
```

Every timed sample must exit successfully, produce a parseable non-empty PDF,
pass `qpdf --check`, contain the manifest's expected text, satisfy its page and
stage requirements, and avoid fatal log markers. Failed samples never count as
fast results.

These results establish the scoped corpus claim above. They do not establish a
universal result across all documents, hardware, operating systems, TeX
distributions, or cache states.
