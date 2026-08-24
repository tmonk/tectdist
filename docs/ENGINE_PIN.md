# Engine pin evidence

Status of plan workstream X3 (docs/ORDER_OF_MAGNITUDE_PERFORMANCE_PLAN.md)
as of the perf-branch programme.

## Current pin

`tectdist-engine` pins **Tectonic 0.17.0** (`tag = tectonic@0.17.0`,
commit `8c0126a9`). Measured baseline on the reference host (Apple M3 Max,
macOS arm64): tiny warm-clean median **134.7 ms**, paper **280.5 ms**,
unicode-fonts **349.1 ms** — classified *good* by
`scripts/tectonic_perf_matrix.py` gates.

## Bundle improvements are already included (X3.4)

The pinned tag ships `tectonic_bundles 0.4.2`, which contains the concurrent
first-build prefetch and less frequent remote rechecking called out in the
plan (`crates/bundles/src/cache.rs`, `mod prefetch`). No component-level
upgrade is required; cold-cache gains from prefetch therefore apply to the
existing pin.

## How to extend the evidence

1. Add entries to `scripts/tectonic-matrix.toml`
   (`tag=...` or `rev=<commit>` per line).
2. Run `python3 scripts/tectonic_perf_matrix.py --gate-tiny-ms <budget>`
   on the stable performance host with `PKG_CONFIG_PATH` configured for the
   Tectonic system libraries.
3. For regression archaeology between two known commits:
   `python3 scripts/bisect_tectonic_perf.py --good <c> --bad <c>`.

Historical revisions must run against the current bundle so only engine code
varies: set `TECTONIC_BUNDLE_URL` (or the equivalent config field for older
engines) to the same immutable bundle location for every matrix entry. Old
public package endpoints must not invalidate the comparison.

## Pin rules (plan X3.5)

A revision may be pinned when it passes the full correctness corpus,
measurably improves the claim corpus, documents security/bundle
compatibility, and has an upstream PR or named maintenance owner.
Upstreaming of any local patch series is tracked as follow-up issues;
local patches carry rationale comments in-tree until then.
