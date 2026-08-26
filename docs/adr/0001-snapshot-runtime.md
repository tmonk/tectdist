# ADR 0001: Snapshot runtime abstraction and deferred runtime decision

- **Status:** Accepted — abstraction adopted; engine-runtime decision DEFERRED to M3 feasibility gates
- **Date:** 2026-08-26
- **Plan reference:** `docs/BASICTEX_X10_PLAN.md` §0.3, §13; milestone M0

## Context

The audited programme ended at `e1afa972` with a native fork-server
approach that is engine-specific, build-system-specific, and fragile:
pdfTeX works, XeTeX resumed children exit 1, LuaHBTeX has no integration
path. Post-initialisation native `fork()` across Web2C globals, C++,
ICU, Fontconfig, HarfBuzz, and an embedded Lua VM does not present a
uniform snapshot surface.

## Decision

1. **Adopt the `SnapshotRuntime` trait** (`prepare`, `instantiate`,
   `run_until`, `capture`, `clone_snapshot`, `restore_host`) as the only
   production route to snapshot-based acceleration.
2. **Defer the engine-runtime choice** — WASM AOT vs Arena vs hybrid — to
   M3, decided strictly by the Section 13.3 feasibility gates measured on
   pdfTeX. The outcome must be recorded as one of
   `ADOPT_WASM_AOT | ADOPT_ARENA | HYBRID_PDFTEX_NATIVE_OTHER_WASM`
   in a successor ADR.
3. **Quarantine the native fork server** under `experiments/native-fork/`
   as evidence plus an optional pdfTeX experiment / benchmark control
   (`NativeForkRuntime`). It is not packaged for production.
4. No further cycles may be spent patching generated engine C for resume
   purposes before the M3 gates pass.

## Primary candidate: WasmAotRuntime

Rationale: TeX Live 2026 pdfTeX/XeTeX/LuaHBTeX/BibTeX/MakeIndex/xdvipdfmx/
Kpathsea have been demonstrated crossing the WASM boundary (TeXlyre BusyTeX
— feasibility input, not a dependency). Linear memory offers a uniform,
clonable state surface. Gates include ≤15% one-shot overhead, ≤1.0 ms p50
snapshot clone+entry, deterministic restore manifests, bounded memory, and
reproducible licence-compatible toolchain.

## Fallback candidate: ArenaRuntime

Engine globals and allocations relocated into a page-backed relocatable
arena with `MAP_PRIVATE` copy-on-write snapshots. More invasive than WASM
but systematic; manually serialising individual Web2C globals is forbidden
as a primary design.

## Consequences

- Engine work before M3 closure is limited to the feasibility spike.
- A failed gate triggers a written decision (fix bounded issue / adopt
  Arena / hybrid) — never indefinite tuning of one resume location.
- The fork-server binaries stay out of Git; CI builds from patches in
  `experiments/native-fork/patches/`.

## Maintenance owner

Runtime/pack workstream owner (M3+). Revisit if TeX Live upstream or WASM
toolchain changes invalidate pinned reproducibility.
