# tectdist Performance Optimisation Technical Plan

**Status:** Implemented on the `perf` branch; release qualification deferred
**Target repository:** `tmonk/tectdist`
**Baseline:** `v0.2.2`, main commit `e3d52c0888e7522e160a0e7e05ffed7dfa714077`
**Last updated:** 24 August 2026
**Active phases:** 0, A, B, C, E, F, G
**Deferred:** Phase D, persistent daemon and incremental compilation

The engineering implementation described here is present on this performance
branch. Release-only work—multi-platform qualification sessions, publishing
evidence, bottles, tags, and claims—has deliberately not been performed. CI
execution is also outside this branch's local completion pass. Those omissions
do not relax the qualification gates; they prevent an unqualified development
result from being presented as a release result.

---

## 1. Purpose

This document defines the engineering programme required to make `tectdist`
the lowest-latency, drop-in route from supported LaTeX source to a correct,
fully resolved PDF on supported macOS and Linux systems.

The project has historical launcher and single-document measurements, but
they are engineering context rather than a current product-performance claim.
The versioned paired corpus and generated summaries defined below replace
hand-maintained headline numbers. See [BENCHMARKS.md](BENCHMARKS.md).

That evidence is not yet broad enough for an unqualified claim that `tectdist`
is the fastest way to compile TeX. The active programme therefore has two
equally important outputs:

1. A materially faster implementation.
2. A public, reproducible evidence system that makes every performance claim
   precise, current, and defensible.

The intended final positioning is:

> **tectdist is the fastest drop-in path from supported LaTeX source to a
> correct, fully resolved PDF, as measured by the published tectdist benchmark
> suite on supported platforms.**

The exact public wording must be generated from the benchmark results and may
be weaker than this target if the release does not pass every claim gate.

---

## 2. Scope

### 2.1 In scope

The active plan covers:

- A formal definition of performance and correctness.
- A representative, public benchmark corpus.
- Correctness oracles for benchmark outputs.
- Paired and statistically robust competitor measurements.
- Removal of avoidable Python and subprocess overhead.
- A native Rust dispatcher compatible with the existing command farm.
- Direct embedding of the Tectonic engine.
- Cold-start, bundle, package, and format-cache optimisation.
- Engine-level profiling and upstream performance work.
- CI performance regression gates.
- Reproducible release evidence and benchmark-backed marketing claims.
- Homebrew packaging changes required by the native and embedded
  implementation.

### 2.2 Explicitly out of scope

The following work is not part of the active programme:

- Persistent daemon processes.
- Warm worker pools.
- Cross-invocation incremental compilation.
- Final-output or intermediate-result caches managed by `tectdist`.
- Dependency-aware watch mode.
- Remote or shared build caches.
- Windows support in the first qualification cycle.
- Complete TeX Live command compatibility.
- DVI and PostScript output.
- ConTeXt support.
- Guaranteed native pdfTeX or LuaTeX semantics.
- Automatic selection among multiple TeX engine backends.

The daemon and incremental design formerly described as Phase D is parked in
Section 11. It is not a dependency of any active milestone.

---

## 3. Product and performance contract

Optimisation must target a defined result. A faster process that produces an
incomplete or stale PDF is not a performance win.

### 3.1 Unit of work

A benchmarked compile is complete only when it produces a **correct, fully
resolved PDF**.

A successful result must satisfy all applicable checks:

- The process exits successfully.
- The output PDF exists and is structurally valid.
- The expected number of pages is present.
- Required document text and semantic markers are present.
- Cross-references have converged.
- Citations are resolved.
- Table-of-contents and PDF outline entries are current.
- Required bibliography processing has completed.
- Required index processing has completed.
- No actionable rerun warning remains.
- No required stage has been silently skipped.
- The result respects the declared output directory and job name.

The benchmark runner must reject a faster but incomplete result.

### 3.2 Claim population

The initial performance claim applies only to documents that satisfy all of
the following:

- They produce PDF output.
- They are supported by the Tectonic backend used by `tectdist`.
- They pass the benchmark corpus correctness oracle.
- They do not rely on unsupported DVI, PostScript, ConTeXt, true LuaTeX, or
  true pdfTeX behaviour.
- They run on a supported release platform.

Current limitations remain documented in
[COMPATIBILITY.md](COMPATIBILITY.md). The claim must not imply broader engine
or format compatibility than the product provides.

### 3.3 Performance scenarios

Every corpus document must support one or more explicitly named scenarios.
Cold and warm results must never be combined.

| Scenario | Definition |
|---|---|
| `cold-empty-cache` | Empty Tectonic bundle and format caches; package source is controlled and declared. |
| `warm-clean` | Compiler/package cache is warm; project outputs are removed before each trial. |
| `warm-existing-output` | Existing PDF and intermediate files remain, but the compiler is invoked normally. |
| `source-small-edit` | A deterministic text or equation edit is applied before each trial. No `tectdist` incremental cache is used. |
| `source-structural-edit` | A deterministic section, reference, or citation edit is applied. |
| `bibliography` | The document requires BibTeX or Biber processing. |
| `index` | The document requires `makeindex` or `upmendex`. |
| `batch` | Multiple independent documents are compiled in one benchmark session. |

Because Phase D is parked, edit scenarios measure the normal one-shot
compiler behaviour with ordinary project intermediates. They do not include a
persistent service or a `tectdist`-managed content cache.

### 3.4 Competitor set

The qualification suite must include:

1. The current `tectdist` candidate.
2. The previous released `tectdist` version.
3. Direct Tectonic using the same compatible engine and bundle.
4. TeX Live with `latexmk` for fully resolved one-command output.
5. TeX Live raw engines only on documents for which the oracle proves that a
   single pass is complete.
6. ClutTeX where installation and document compatibility allow it.
7. MiKTeX when Windows or a controlled compatible environment is added.

The exact executable path, version output, distribution identity, package
state, and configuration of every competitor must be stored with the raw
results.

Direct Tectonic is a mandatory control. It reveals whether a `tectdist`
change improves the compiler path or merely reduces wrapper overhead.

### 3.5 Measurement targets

The following are engineering targets, not pre-approved marketing claims.
They may be revised after Phase 0 establishes stable baselines.

| Metric | Target |
|---|---:|
| Native `tectdist --version` p50 | `< 2 ms` |
| Native `tectdist --version` p95 | `< 4 ms` |
| Native external-engine overhead over direct Tectonic | `< 3 ms` p50 |
| Embedded-engine overhead over equivalent Tectonic driver call | Within measurement noise |
| `latexmk` compatibility-layer overhead versus direct `pdflatex` path | `< 3 ms` excluding engine work |
| Correctness pass rate on claim corpus | `100%` |
| Pull-request microbenchmark regression tolerance | Maximum of `3%` and `0.5 ms`, subject to confidence rules |
| Pull-request real-build aggregate regression tolerance | `5%` unless explicitly approved |
| Release benchmark trial count | At least 30 paired samples for ordinary cases |
| Release qualification sessions | Three independent sessions per supported platform |

No target is allowed to weaken correctness, security, or compatibility.

---

## 4. Current architecture and baseline

### 4.1 Runtime architecture

The current product is a standard-library-only Python application distributed
as a compressed zipapp. A symlink farm points traditional TeX command names at
a single launcher. Dispatch is based on `argv[0]`.

The important runtime files are:

- [bin/tectdist](bin/tectdist): source-tree launcher.
- [src/tectdist/dispatcher.py](src/tectdist/dispatcher.py): command dispatch,
  flag translation, engine execution, and index rerun handling.
- [src/tectdist/latexmk.py](src/tectdist/latexmk.py): common `latexmk`
  compatibility layer.
- [src/tectdist/tools.py](src/tectdist/tools.py): proxies, stubs,
  Ghostscript helpers, and `kpsewhich`.
- [src/tectdist/pairing.py](src/tectdist/pairing.py): Tectonic/Biber version
  health and runtime pairing checks.
- [build.py](build.py): zipapp builder.
- [Formula/tectdist.rb](Formula/tectdist.rb): Homebrew package definition.

### 4.2 Existing performance work

The current tree already includes useful optimisations:

- Lazy imports in the dispatcher.
- Lazy Homebrew glob expansion for tool proxies.
- Deflated zipapp packaging.
- Direct `exec` for real utility proxies.
- A cached runtime engine-pairing check.

The existing benchmark report attributes large launcher improvements to those
changes. Further work must therefore focus on remaining process boundaries,
engine integration, bundle access, and engine-dominated execution rather than
repeatedly micro-optimising the already negligible in-process flag parser.

### 4.3 Known hot-path issues

#### Nested Python launch in `latexmk`

The current `latexmk` flow launches a farm engine command as a subprocess. That
command re-enters the Python dispatcher before Tectonic is started:

```text
latexmk symlink
  -> Python dispatcher
    -> latexmk.py
      -> subprocess: pdflatex symlink
        -> second Python dispatcher
          -> subprocess: tectonic
```

This creates an avoidable interpreter startup and process boundary on every
`latexmk` build.

#### Split engine resolution

A normal compile can resolve the engine during the pairing check and then
resolve it again for execution. The information should be calculated once and
passed through a typed execution plan.

#### Directory scanning for index detection

The dispatcher scans the output directory before and after an engine run to
find changed `.idx` files. This is robust but can become expensive in a large
shared output directory. Embedded engine events should eventually replace
broad filesystem inference.

#### Python zipapp startup

The benchmark report records measurable zipapp and Python startup latency.
This matters most for tiny documents and compatibility commands. It is not,
by itself, sufficient to produce a large improvement on engine-dominated
papers or books.

### 4.4 Current verification

The repository currently has:

- A 272-check acceptance battery.
- Mock-only CI verification.
- Zipapp purity checks.
- Installation and Homebrew formula checks.
- Python 3.9 syntax verification in
  [.github/workflows/ci.yml](.github/workflows/ci.yml).
- Launcher, proxy, end-to-end, and TeX Live comparison benchmarks under
  [benchmarks/](benchmarks/).

The active plan extends these rather than replacing them prematurely.

---

## 5. Engineering principles

### 5.1 Correctness before latency

Every optimisation pull request must demonstrate unchanged or improved output
correctness. A performance result without an oracle is treated as exploratory,
not release evidence.

### 5.2 Measure the whole path

Report at least:

- End-to-end wall time.
- CPU time.
- Peak resident memory.
- Process count.
- Engine pass count.
- External tool count and duration.
- Bytes read and written where supported.
- Wrapper, engine, bibliography, index, and post-processing spans.

### 5.3 Optimise the dominant cost

No low-level change should be accepted merely because it makes a synthetic
microbenchmark faster. It must improve a claim-relevant path or remove a
known architectural cost.

### 5.4 Preserve a reference implementation

The Python implementation remains the behavioural reference until the native
implementation passes differential tests across the entire acceptance suite.

### 5.5 Prefer upstream engine improvements

Tectonic changes should be submitted upstream whenever practical. Long-lived
private engine forks increase security, release, and compatibility risk.

### 5.6 Keep public claims reproducible

Headline numbers must be generated from immutable raw results. Documentation
must not contain manually maintained percentages that can drift from the
current release.

### 5.7 No hidden background service

While Phase D is parked, every command must remain a one-shot process. The
implementation may use process-local caches and normal filesystem caches
provided by dependencies, but it must not depend on a resident daemon.

---

## 6. Target one-shot architecture

The active target is a single native executable that parses compatibility
commands, constructs a typed compilation plan, and invokes an embedded
Tectonic engine in the same process.

```text
argv[0] and command-line arguments
               |
               v
       Native tectdist CLI
               |
               v
        Invocation parser
               |
               v
       Compatibility planner
               |
               v
        CompilationPlan
       /        |        \
      /         |         \
external   embedded    utility
Tectonic   Tectonic    executor
executor   executor    or proxy
      \         |         /
       \        |        /
          ExecutionResult
               |
               v
  validation, index integration,
  artifact rename, diagnostics,
  and process exit status
```

### 6.1 Core data model

The Python refactor and Rust implementation should share the same conceptual
model.

```text
Invocation
  invoked_name
  argv
  cwd
  environment view

CompilationPlan
  requested command identity
  selected engine backend
  input document
  output directory
  job name
  search paths
  SyncTeX setting
  security and shell-escape setting
  chatter and diagnostic mode
  rerun policy
  bundle and format identity
  external bibliography/index requirements
  compatibility warnings

ResolvedEngine
  executable path or embedded build identity
  canonical identity
  version
  bundle identity
  format-cache identity

ExecutionResult
  exit status
  timing spans
  files read
  files written
  engine passes
  external commands
  warnings
  output artifacts
```

### 6.2 Executor interfaces

The target code must make engine selection explicit:

```text
Executor
  execute(plan) -> ExecutionResult

ExternalTectonicExecutor
  used during Phase A and Phase B
  retained as a diagnostic and fallback path

EmbeddedTectonicExecutor
  primary Phase C path

UtilityExecutor
  proxies, Ghostscript helpers, stubs, kpsewhich
```

This separation allows performance and correctness comparisons between the
external and embedded paths without duplicating compatibility parsing.

### 6.3 Proposed Rust workspace

```text
crates/
  tectdist-core/
    invocation parsing
    compatibility tables
    compilation plans
    diagnostics model

  tectdist-engine/
    external Tectonic executor
    embedded Tectonic executor
    status backend
    output and dependency events

  tectdist-tools/
    proxy resolution
    stubs
    kpsewhich
    Ghostscript-backed helpers
    bibliography and index integration

  tectdist-cli/
    argv[0] dispatch
    user-facing commands
    doctor output
    process exit mapping

  tectdist-bench/
    trace schema helpers
    benchmark metadata helpers
```

The workspace layout is a target, not a requirement to split every small
module into a separate crate. Final boundaries should follow compilation time,
testability, and API stability.

---

## 7. Phase 0 — evidence, benchmark, and observability foundation

Phase 0 is the first active milestone. No broad performance claim or native
rewrite should be released before this foundation is usable.

### 7.1 Deliverables

- Performance contract in the repository.
- Versioned benchmark corpus manifest.
- Paired randomised benchmark runner.
- Correctness oracle.
- Raw result schema.
- Stable performance CI infrastructure.
- Internal timing spans.
- Generated benchmark summaries.

### 7.2 Corpus layout

Add:

```text
benchmarks/
  corpus/
    manifest.toml
    tiny/
    references/
    paper/
    bibtex/
    biblatex/
    index/
    glossary/
    tikz/
    graphics/
    unicode-fonts/
    shell-escape/
    thesis/

  runner/
    __init__.py
    cli.py
    competitors.py
    scenarios.py
    correctness.py
    statistics.py
    system_info.py
    results.py

  schemas/
    result.schema.json
    manifest.schema.json

  results/
    README.md
```

Generated scratch directories and local result files remain ignored. Release
qualification result bundles are committed under a release-specific directory
or attached immutably to the GitHub release.

### 7.3 Corpus requirements

The first claim corpus should include at least:

1. Tiny, single-pass document.
2. Cross-reference and hyperref convergence document.
3. Package-heavy academic paper.
4. BibTeX document.
5. biblatex/Biber document.
6. Index document.
7. Glossary document.
8. TikZ-heavy document.
9. Graphics-heavy document.
10. Unicode and `fontspec` document.
11. Controlled shell-escape document.
12. Large thesis or book.
13. A compact, self-contained set of feature fixtures. The initial corpus is
    intentionally bounded to the named document classes above; large
    third-party repositories are neither vendored nor fetched by the runner.
    The separately declared ITP3 QFT stress fixture is a pinned, opt-in
    742,627-byte download and is excluded from the default claim aggregate.

Each corpus entry must declare:

- Source and licence.
- Expected engine compatibility.
- Required packages and external tools.
- Expected page count.
- Required semantic markers.
- Whether references, bibliography, or index work is expected.
- Applicable scenarios.
- Deterministic edit operations.
- Correctness checks.
- Whether the document is included in the public claim aggregate.

Example manifest entry:

```toml
[[document]]
id = "paper-hyperref"
path = "corpus/paper"
main = "paper.tex"
license = "CC0-1.0"
claim = true
platforms = ["macos-arm64", "linux-x86_64", "linux-arm64"]
scenarios = ["warm-clean", "source-small-edit", "source-structural-edit"]
requires = ["hyperref", "booktabs", "listings"]
expected_pages = 3
expected_text = [
  "A Representative LaTeX Document",
  "Colored text",
  "Example results table",
]
forbid_log_patterns = [
  "undefined references",
  "Citation .* undefined",
  "Rerun to get cross-references right",
]
```

### 7.4 Paired randomised runner

The current competitor tests should be replaced or wrapped by a paired runner.
For each document and scenario:

1. Prepare identical scratch copies.
2. Prepare the declared cache state.
3. Randomly select `candidate -> competitor` or `competitor -> candidate`.
4. Run both tools.
5. Capture timing, process, I/O, and trace data.
6. Validate both outputs.
7. Record the paired difference.
8. Reset scenario state.
9. Repeat.

Minimum release settings:

- 5 to 10 warmups.
- 30 measured paired trials for ordinary documents.
- 15 measured paired trials for expensive book-scale documents.
- Three independent sessions per supported platform.
- No arbitrary outlier deletion.
- Bootstrap confidence intervals over paired differences.

The runner must support a faster smoke mode for local development without
mistaking smoke output for release evidence.

### 7.5 Correctness oracle

A layered oracle is required.

#### Structural checks

- PDF exists.
- PDF parser or `qpdf --check` succeeds.
- Expected page count matches.
- Output path and job name match the invocation.

#### Semantic checks

- Extracted text contains required markers.
- References and citations show expected values.
- PDF outline contains expected entries where applicable.
- Bibliography and index content appears in extracted text.

#### Diagnostic checks

- No unresolved-reference warning.
- No undefined-citation warning.
- No pending rerun warning.
- No missing external tool warning for a required stage.
- No silent stub use where the corpus requires a real tool.

#### Equivalence checks

For the same Tectonic backend:

- Compare `tectdist` with direct Tectonic using normalised metadata.
- Compare page count, extracted text, outline, and selected rendered pages.
- Allow expected timestamp, object-order, and compression differences.

For cross-engine comparisons:

- Require semantic correctness rather than byte identity.
- Document accepted rendering differences.
- Exclude documents for which semantic equivalence cannot be established.

### 7.6 Result schema

Every run bundle must include:

```json
{
  "schema_version": 1,
  "repository_commit": "...",
  "dirty": false,
  "runner_commit": "...",
  "session_id": "...",
  "timestamp_utc": "...",
  "platform": {
    "os": "...",
    "kernel": "...",
    "architecture": "...",
    "cpu": "...",
    "cores": 0,
    "memory_bytes": 0,
    "power_mode": "..."
  },
  "tool": {
    "name": "tectdist",
    "path": "...",
    "version_output": "...",
    "engine": "...",
    "bundle_identity": "..."
  },
  "document": "paper-hyperref",
  "scenario": "warm-clean",
  "order": ["candidate", "competitor"],
  "samples": [],
  "correctness": {},
  "summary": {}
}
```

Each raw sample should record:

- Wall time.
- User and system CPU time.
- Peak RSS where available.
- Exit status.
- Process count.
- Engine pass count.
- External tool invocations.
- Trace spans.
- Output hash and semantic validation result.

### 7.7 Internal timing spans

Add opt-in structured tracing to the Python implementation before refactoring
it. Use a disabled-by-default environment variable such as
`TECTDIST_TRACE_FILE`.

Required spans:

- `process.startup`
- `dispatcher.import`
- `dispatcher.route`
- `pairing.resolve`
- `pairing.cache_read`
- `pairing.version_probe`
- `planner.translate`
- `filesystem.output_setup`
- `filesystem.index_scan_before`
- `engine.spawn`
- `engine.run`
- `filesystem.index_scan_after`
- `indexer.resolve`
- `indexer.run`
- `engine.rerun_after_index`
- `artifacts.rename`
- `process.total`

Trace output must be machine-readable and stable enough for the benchmark
runner, but it is not a public API until explicitly versioned.

### 7.8 Performance CI

#### Pull requests

Use stable self-hosted runners for performance gates. Shared hosted runners
may still run correctness and smoke tests.

PR performance suite:

- Native or Python startup microbenchmarks.
- Compatibility parsing.
- Fake-engine dispatch.
- `latexmk` dispatch.
- Proxy resolution.
- Tiny real-engine compile.
- Five representative corpus documents.

A regression fails when:

- The confidence interval excludes zero in the regressive direction, and
- The regression exceeds the larger of 3% or 0.5 ms for stable microcases, or
- The claim-corpus aggregate exceeds 5%, or
- Correctness, process count, or engine-pass count regresses.

A maintainer may approve an intentional regression only when the pull request
records the reason and the expected user benefit.

#### Nightly

- Full corpus.
- Candidate versus direct Tectonic.
- Candidate versus previous `tectdist` release.
- Candidate versus TeX Live `latexmk`.
- Supported platform matrix.
- Warm and controlled cold scenarios.

#### Weekly

- Resolve current competitor packages in a clean environment.
- Re-run qualification subset.
- Open an issue if the published claim no longer passes.
- Preserve all raw output.

### 7.9 Generated reporting

Add a script that reads raw JSON and generates:

- `BENCHMARKS.md` tables.
- Per-platform summaries.
- A claim-corpus aggregate.
- Correctness pass rates.
- Confidence intervals.
- A machine-readable badge payload.

Human-edited benchmark numbers should be removed once generated reporting is
reliable.

### 7.10 Phase 0 exit gate

Phase 0 is complete when:

- The corpus manifest is versioned and validated.
- The paired runner can reproduce the current paper benchmark.
- Direct Tectonic and the previous `tectdist` release are included.
- Correctness failures reject a sample.
- Raw results contain full machine and tool metadata.
- PR smoke performance and nightly full performance jobs run successfully.
- `BENCHMARKS.md` can be generated from raw result data.

---

## 8. Phase A — optimise the existing Python implementation

Phase A delivers measurable improvements without changing language or engine
integration. It also creates clean interfaces for the Rust migration.

### 8.1 Refactor into plan and execution layers

Introduce internal typed models. A practical Python layout is:

```text
src/tectdist/
  invocation.py
  plan.py
  planner.py
  engine.py
  dispatcher.py
  latexmk.py
  tools.py
  pairing.py
```

Illustrative interfaces:

```python
from dataclasses import dataclass
from typing import Mapping, Sequence


@dataclass(frozen=True)
class Invocation:
    invoked_name: str
    argv: tuple[str, ...]
    cwd: str
    environment: Mapping[str, str]


@dataclass(frozen=True)
class ResolvedEngine:
    path: str
    realpath: str
    mtime_ns: int | None
    version_pair: str | None


@dataclass(frozen=True)
class CompilationPlan:
    program: str
    engine: ResolvedEngine
    engine_args: tuple[str, ...]
    input_path: str | None
    output_directory: str
    job_name: str | None
    rename: tuple[str, str, str] | None
    requires_index_detection: bool
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class ExecutionResult:
    returncode: int
    generated_files: tuple[str, ...]
    engine_passes: int
```

The exact field set may change, but parsing, engine resolution, and execution
must no longer be interleaved in one function.

### 8.2 Remove the nested Python launch from `latexmk`

Change `latexmk.py` from constructing and spawning a farm engine command to
constructing a `CompilationPlan` and invoking the shared engine executor in
process.

Target flow:

```text
latexmk symlink
  -> Python dispatcher
    -> latexmk compatibility parser
      -> shared planner
        -> external Tectonic executor
```

Requirements:

- Preserve the existing supported `latexmk` CLI.
- Preserve exact engine arguments.
- Preserve output and cleaning behaviour.
- Preserve error and exit-status behaviour.
- Keep custom engine commands working through an explicit external-command
  branch.
- Do not route a custom arbitrary command through internal Tectonic logic.

Tests:

- Differential test old and new `latexmk` execution with a fake engine.
- Assert one Python process before the engine.
- Assert the engine is launched once.
- Run the full acceptance battery.
- Run all corpus cases that invoke `latexmk`.

Acceptance:

- No second `tectdist` interpreter appears in process traces.
- Fixed `latexmk` overhead is within 3 ms of the matching direct engine path.
- No correctness or compatibility regression.

### 8.3 Unify engine resolution and pairing

Replace separate lookup paths with one resolver that returns `ResolvedEngine`.

The resolver must:

1. Honour an explicit `TECTONIC` setting.
2. Resolve a bare command name through `PATH` where appropriate.
3. Preserve an invalid explicit path so the normal execution error is clear.
4. Fall back to the supported Homebrew path only when no explicit or PATH
   engine exists.
5. Capture canonical path and file identity.
6. Read the version-pairing cache once.
7. Probe `tectonic --version` only when required.
8. Return the same resolved engine to the executor.

The current safety property must remain: an engine binary replacement is
detected immediately through identity or modification-time change.

Optimisation of the cache representation is secondary. JSON should only be
replaced if tracing shows it is material.

### 8.4 Make `latexmk` imports path-sensitive

Move heavy imports behind the paths that use them:

- Version and help should avoid `subprocess`, `shutil`, and RC parsing imports.
- Cleaning should avoid engine execution imports.
- RC parsing should import `re` only when a file exists.
- `shlex` should be loaded only for custom command parsing or dry-run output.

This change is small but directly measurable in the existing startup suite.

### 8.5 Reduce output-directory overhead

#### Directory creation

Do not call `os.makedirs(..., exist_ok=True)` when a fast existence check
shows the output directory already exists and is a directory. Preserve the
current best-effort behaviour for race conditions.

#### Index detection

Introduce an `IndexStrategy` abstraction:

```text
NoIndexCheck
ExpectedStemIndexCheck
DirectoryIndexCheck
```

Use `NoIndexCheck` when the invocation or corpus proves no index integration
is needed. Use `ExpectedStemIndexCheck` when the output stem is known. Retain
`DirectoryIndexCheck` as the compatibility fallback.

Do not attempt unsafe source-text heuristics such as searching for
`makeindex`. The decision must be based on reliable output or engine
information.

Add benchmarks for output directories containing approximately 10, 1,000,
and 100,000 entries.

### 8.6 Minimise process creation

Audit all common paths:

- Keep `os.execvpe` for transparent real-tool proxies.
- Use the shared external engine executor rather than wrapper subprocesses.
- Avoid separate version probes when the pairing cache is valid.
- Avoid shell invocation entirely.
- Preserve direct argument arrays for every subprocess.

Record process count as a benchmark metric so a future change cannot
reintroduce wrapper layers unnoticed.

### 8.7 Improve error and trace structure

Return structured internal errors from the planner and executor, then render
them in the dispatcher. This makes the Rust port and differential tests less
fragile than matching ad hoc exceptions.

Internal categories should include:

- Invalid invocation.
- Engine not found.
- Engine not executable.
- Pairing mismatch.
- Unsupported requested format.
- External tool unavailable.
- External tool failed.
- Output rename failed.
- Correctness-critical stage skipped.

User-facing text may remain compatible while the internal representation is
made explicit.

### 8.8 Phase A pull-request sequence

1. Add trace spans without changing behaviour.
2. Introduce `Invocation`, `ResolvedEngine`, `CompilationPlan`, and
   `ExecutionResult` behind existing functions.
3. Add a shared external engine executor.
4. Move `pdflatex` execution onto the planner/executor path.
5. Move `latexmk` onto the same path and remove nested dispatch.
6. Unify engine resolution and pairing.
7. Add index strategies and large-directory benchmarks.
8. Complete import-path cleanup.
9. Update benchmark baselines and generated documentation.

### 8.9 Phase A exit gate

- Full acceptance battery passes.
- Corpus correctness is unchanged.
- `latexmk` uses one Python process and one engine process.
- Engine lookup occurs once per invocation.
- Common non-index builds avoid broad index scans where reliably possible.
- Trace spans account for the complete one-shot path.
- Every Phase A optimisation has a paired benchmark result.
- No claim-relevant case regresses beyond the agreed threshold.

---

## 9. Phase B — native Rust dispatcher with external Tectonic

Phase B replaces Python startup and the zipapp while retaining external
Tectonic. This isolates the language migration from engine embedding.

### 9.1 Objectives

- One native executable for all symlinked command names.
- Behavioural parity with the Python reference.
- External Tectonic execution through a shared compilation plan.
- No Python runtime dependency in the installed product.
- Native startup within the target budget.
- A stable platform for embedding Tectonic in Phase C.

### 9.2 Rust core model

Implement strongly typed equivalents of the Phase A models.

```rust
pub struct Invocation {
    pub invoked_name: OsString,
    pub args: Vec<OsString>,
    pub cwd: PathBuf,
}

pub struct CompilationPlan {
    pub logical_program: ProgramKind,
    pub engine: EngineSelection,
    pub input: Option<PathBuf>,
    pub output_dir: PathBuf,
    pub job_name: Option<OsString>,
    pub engine_args: Vec<OsString>,
    pub index_strategy: IndexStrategy,
    pub diagnostics: Vec<Diagnostic>,
}

pub enum EngineSelection {
    External(ResolvedExternalEngine),
    Embedded(EmbeddedEngineConfig),
}

pub struct ExecutionResult {
    pub status: i32,
    pub engine_passes: u32,
    pub generated_files: Vec<PathBuf>,
    pub events: Vec<ExecutionEvent>,
}
```

Use `OsString` and `PathBuf` rather than assuming UTF-8 command lines and
paths.

### 9.3 Compatibility data

Port the command farm and flag tables from
[src/tectdist/flags.py](src/tectdist/flags.py) into a single Rust source of
truth.

During migration, generate one representation from the other or add a test
that proves exact equality. The Python and Rust tables must not silently
split.

Required command groups:

- Engine aliases.
- Bibliography and index proxy-or-stub commands.
- DVI and maintenance stubs.
- Font and MetaFont stubs.
- ConTeXt stubs.
- Poppler and qpdf proxies.
- Ghostscript-backed helpers.
- `kpsewhich`.
- `latexmk`.

### 9.4 `argv[0]` dispatch

The native executable must preserve the existing farm behaviour:

- Determine the logical command from the invoked basename.
- Treat `tectdist FILE.tex` as the default compile command.
- Preserve meta-commands such as `doctor` and `tools`.
- Preserve symlink behaviour in Homebrew prefixes and source checkouts.
- Avoid canonicalising the invoked path when the original directory is needed
  to locate adjacent farm commands.

### 9.5 External engine executor

Use direct process spawning with inherited standard streams unless capture is
required for a specific feature.

Requirements:

- No shell.
- Exact argument preservation.
- Explicit environment propagation.
- Clear mapping of missing executable, permission, signal, and exit-status
  failures.
- Trace events around spawn and execution.
- One resolved engine per invocation.

For true utility proxies, replace the `tectdist` process with the real process
using the platform-equivalent of `execve` where supported.

### 9.6 Native `latexmk` compatibility

Port only the currently supported interface first. Do not expand feature scope
during the language migration.

The native `latexmk` parser should produce the same `CompilationPlan` as the
native `pdflatex` path, with compatibility options applied before planning.

Required parity areas:

- Common engine-selection flags.
- Forwarded interaction, SyncTeX, shell-escape, recorder, and error flags.
- Output and auxiliary directory flags.
- Job name.
- Clean and clean-all modes.
- Dry run.
- Common RC-file assignments.
- Existing warning behaviour for unsupported modes.

Custom engine command strings must continue to use an explicit external
command path.

### 9.7 Native tools and proxies

Port utility behaviour in risk order:

1. Silent and informational stubs.
2. Real-tool proxy resolution.
3. `kpsewhich`.
4. Ghostscript wrappers.
5. Proxy-or-stub bibliography/index commands.

Do not change user-visible tool semantics while optimising the main compiler
path.

### 9.8 Differential test harness

For every test case, run both implementations in isolated directories and
compare:

- Exit status.
- Standard output.
- Standard error.
- Engine command and exact arguments.
- Environment passed to the engine.
- Files created.
- Files removed.
- File contents where deterministic.
- Rename behaviour.
- Proxy selection.
- Diagnostic category.

Add a normalisation layer only for intentional differences such as the program
version string or temporary paths.

The Python implementation remains the reference until:

- Every existing acceptance case has a Rust comparison.
- Every corpus scenario passes.
- Platform-specific path and symlink cases pass.
- Security tests pass.

### 9.9 Native build configuration

Start with conservative release settings:

```toml
[profile.release]
lto = "thin"
codegen-units = 1
panic = "abort"
strip = "symbols"
```

Benchmark before permanently adopting:

- Full LTO.
- Profile-guided optimisation.
- Target-specific CPU features.
- Alternative allocators.
- Static versus dynamic system libraries.
- Post-link optimisers.

Portability and reproducibility take precedence over small machine-specific
wins.

### 9.10 Packaging migration

Homebrew work:

- Build the Rust binary from pinned sources.
- Remove the Python dependency after parity is complete.
- Preserve the existing symlink farm.
- Preserve real-tool exclusions so the farm does not shadow Homebrew-provided
  Poppler, qpdf, Ghostscript, or bundled Biber commands incorrectly.
- Build bottles for supported macOS and Linux architectures.
- Add bottle smoke tests that compile a real document.
- Produce an SBOM and dependency manifest.
- Record the Rust compiler version and dependency lockfile in release
  provenance.

For one release cycle, retain the Python reference implementation in the
source tree or a tagged branch for bisecting behavioural regressions.

### 9.11 Phase B exit gate

- Native implementation passes the full differential suite.
- Full acceptance battery passes on all supported platforms.
- Claim corpus correctness is 100%.
- `tectdist --version` meets the native startup budget.
- External-engine overhead over direct Tectonic is below 3 ms p50 on stable
  runners.
- No installed Python runtime dependency remains.
- Homebrew bottle and source builds pass.
- The Python implementation is no longer on the default installed path.

---

## 10. Phase C — embed Tectonic in the native binary

Phase C removes the external engine process boundary and makes engine identity
part of the `tectdist` release.

### 10.1 Objectives

- Link the Tectonic driver directly into `tectdist`.
- Construct and run the engine session from `CompilationPlan`.
- Remove external Tectonic process startup and CLI parsing.
- Eliminate runtime drift between a `tectdist` release and an independently
  upgraded Tectonic executable.
- Capture structured engine dependency and output events.
- Retain an external-engine fallback for diagnosis and compatibility bisects.

### 10.2 Dependency and version policy

- Pin Tectonic and relevant subcrates in `Cargo.lock`.
- Record the embedded engine commit or version in `tectdist --version` and
  `tectdist doctor --json`.
- Record bundle identity and format-cache identity.
- Keep Biber, biblatex, and BCF compatibility as explicit release metadata.
- Add automated checks that the formula, release metadata, runtime doctor, and
  tests agree.
- Review licence and redistribution obligations for every embedded component.

### 10.3 Embedded executor mapping

Map `CompilationPlan` fields onto the Tectonic driver configuration:

- Primary input path.
- Logical TeX input name.
- Output directory.
- Format selection.
- Bundle selection.
- Format cache path.
- SyncTeX.
- Output format.
- Chatter and diagnostic mode.
- Security stance and shell escape.
- Search paths.
- Rerun policy.
- Makefile dependency output if used.
- Intermediate and log retention.

Every mapping must have a focused test proving parity with the external
Tectonic executor.

### 10.4 Status backend

Implement a `tectdist` status backend that receives structured notes,
warnings, errors, and engine logs.

It must support:

- Human-compatible `pdflatex` and `latexmk` output.
- Quiet and batch modes.
- Machine-readable trace events.
- Preservation of engine error details.
- Stable diagnostic categories for tests.
- No expensive string formatting when output is suppressed.

### 10.5 Engine events and generated files

Capture reliable events for:

- Files opened.
- Files written.
- Output artifacts.
- Engine pass count.
- Bibliography activity.
- `.idx`, `.bcf`, `.aux`, `.toc`, and similar generated files.
- External commands requested through shell escape.

Use these events to replace broad pre/post output-directory scanning wherever
the engine exposes sufficient information.

The active plan uses these events for one-shot correctness, tracing, and index
integration only. It does not build a persistent dependency graph or
cross-invocation cache.

### 10.6 Index integration

After an embedded engine run:

1. Inspect generated-file events for changed index inputs.
2. Resolve a real `makeindex` or `upmendex` according to existing precedence.
3. Run the indexer in the output directory.
4. Feed the generated `.ind` file into one additional embedded engine run.
5. Report failures honestly.
6. Record all stages and durations in `ExecutionResult`.

Retain a compatibility fallback to filesystem checks if an engine version does
not expose enough output information.

### 10.7 Bibliography integration

Preserve the release's explicit Biber/biblatex compatibility policy.

Required tests:

- BibTeX document.
- biblatex/Biber document.
- Remote bibliography source where supported.
- Missing Biber.
- Broken Biber runtime.
- Version mismatch.
- Bibliography failure propagation.

Do not remove runtime health checks until the new embedded engine and packaged
Biber relationship is represented and verified another way.

### 10.8 Security

Embedding moves engine code into the main process, so security settings must
be explicit.

Required controls:

- Clear trusted versus untrusted mode.
- Shell escape disabled when requested.
- No accidental widening of file access.
- Exact search-path handling.
- Safe output path construction.
- Job-name sanitisation.
- No shell interpretation of arguments.
- Fuzz tests for command-line parsing.
- Corpus tests containing malicious path and job-name cases.
- External tool timeout and failure handling.

### 10.9 External fallback

Keep a documented switch such as:

```text
TECTDIST_ENGINE_MODE=external
```

or a diagnostic CLI option. The exact interface is to be decided before
release.

Fallback uses:

- The same `CompilationPlan`.
- The same correctness expectations.
- The same output post-processing.
- Separate trace metadata identifying the executor.

The fallback is intended for diagnosis, compatibility comparison, and
emergency recovery. It is not the default fast path.

### 10.10 Embedded performance work

Measure the following separately:

- Native dispatcher and planning.
- Tectonic configuration creation.
- Bundle opening.
- Format-cache access.
- Engine session creation.
- Engine passes.
- PDF backend.
- Index and bibliography work.
- Post-processing.

Success is not merely “fewer processes.” The embedded path must be at least as
fast as direct Tectonic within uncertainty on every primary clean-build class,
and faster where process and CLI overhead were material.

### 10.11 Packaging changes

Once the embedded path qualifies:

- Remove external Tectonic as a required runtime dependency.
- Keep it optional for diagnostic fallback if packaging policy allows.
- Build and test architecture-specific bottles.
- Report embedded engine and bundle versions in bottle metadata.
- Add reproducibility checks for native artifacts.
- Verify that binary-size growth is acceptable relative to install and cold
  start performance.

### 10.12 Phase C exit gate

- Embedded and external executors pass semantic equivalence tests.
- Claim corpus correctness is 100%.
- Embedded one-shot performance is not materially worse than direct Tectonic
  in any primary category.
- Small clean builds improve measurably.
- Broad output-directory scans are eliminated on the embedded path where
  engine events are sufficient.
- Security and shell-escape tests pass.
- `doctor --json` reports embedded engine, bundle, bibliography, and executor
  state.
- Homebrew bottles no longer require external Tectonic for the default path.
- External fallback remains tested.

---

## 11. Phase D — parked: daemon and incremental compilation

Phase D is explicitly deferred.

### 11.1 Deferred capabilities

No active issue or release milestone should implement:

- A resident `tectdistd` process.
- Unix-domain socket or other client/server protocol.
- Warm reusable engine workers.
- Cross-invocation final-output caching.
- Cross-invocation intermediate caching.
- Persistent dependency graphs.
- Dependency-aware watch mode.
- Remote cache integration.

### 11.2 Reason for parking

The one-shot path still has substantial, lower-risk opportunities:

- Eliminate nested Python execution.
- Remove Python entirely.
- Eliminate the external Tectonic process.
- Improve bundle and format access.
- Optimise engine-dominated stages upstream.

A daemon would add correctness, invalidation, security, lifecycle, resource,
and support complexity before the one-shot architecture is fully measured and
optimised. It is also unnecessary for a defensible claim about clean,
fully-resolved compilation.

### 11.3 Future-compatible design constraints

Active phases should avoid blocking a future daemon, but must not build one.

- Keep `CompilationPlan` serialisable in principle.
- Keep executor interfaces independent of CLI parsing.
- Emit dependency and output events in the embedded executor.
- Avoid uncontrolled global mutable state.
- Make engine/session ownership explicit.
- Version trace and result schemas.

These constraints improve testability now and preserve future options without
committing to a service architecture.

### 11.4 Re-entry criteria

Reconsider Phase D only when all are true:

- Phase C is released and stable.
- One-shot overhead outside the engine is below the target budget.
- Phase E and Phase F have addressed dominant cold and engine costs.
- User research shows repeated edit latency is a top adoption blocker.
- A prototype demonstrates a meaningful gain that cannot be obtained through
  ordinary project intermediates or upstream engine work.
- A correctness and security model for invalidation and shell escape is
  approved.

Until then, Phase D remains parked and excluded from release planning.

---

## 12. Phase E — cold-start, bundle, package, and format optimisation

Phase E targets first-use and empty-cache latency without relying on a daemon
or `tectdist`-managed result cache.

### 12.1 Separate network from compiler performance

Publish two cold scenarios:

#### Controlled cold local source

- Empty bundle and format caches.
- Packages served from a local, versioned mirror or fixture.
- Network latency effectively removed from the measurement.
- Measures package discovery, transfer volume, decompression, indexing, and
  engine initialisation.

#### Public network cold start

- Empty cache.
- Real package endpoint.
- Region, network type, and timestamp recorded.
- Reported separately from compiler claims.
- Never used as the sole basis for “fastest compiler” wording.

### 12.2 Bundle identity and reproducibility

Every run must record:

- Bundle source.
- Bundle serial or immutable identity.
- Manifest hash.
- Format-cache identity.
- Whether any package was downloaded.
- Bytes downloaded.
- Download and decompression spans.

A release must not silently change bundle identity without a full benchmark
and correctness run.

### 12.3 Core package strategy

Evaluate three alternatives with measured install-size and cold-start impact:

1. Ship a compact, high-frequency core package set in the bottle.
2. Pre-scan source and concurrently prefetch declared packages before the
   engine requires them.
3. Provide an explicit `tectdist warm` command that populates common packages
   and formats without compiling a user document.

The selected strategy may combine these, but must preserve deterministic
versioning and avoid an opaque, unbounded install footprint.

### 12.4 Source pre-scan

A source pre-scan may identify obvious package declarations and included
files. It must be treated as an optimisation hint, not a correctness source.

Rules:

- The engine remains authoritative.
- Dynamic macros and generated package names may defeat the scan.
- A missed package falls back to normal engine retrieval.
- Prefetch work must be cancellable when the compile fails early.
- Security-sensitive paths are not fetched merely because text resembles a
  package declaration.

### 12.5 Format-cache work

Investigate release-generated or first-run-generated format data keyed by:

- Embedded Tectonic version.
- Bundle identity.
- Format source hash.
- Relevant architecture or ABI where required.

Required experiments:

- Existing dynamic format-cache cost.
- Packaged pre-generated format.
- Memory-mapped versus normal file access.
- Compression level and install-size trade-off.
- Format invalidation after engine or bundle updates.

Ship a pre-generated format only when reproducibility and compatibility are
proved.

### 12.6 Concurrent resource retrieval

Where upstream APIs allow it, evaluate:

- Concurrent fetching of independent missing resources.
- Bounded concurrency.
- Request coalescing within one compile.
- Streaming decompression.
- Avoidance of duplicate checksum and metadata work.

Concurrency must not alter deterministic package versions or error ordering in
a way that breaks compatibility.

### 12.7 Package and bundle storage

Profile:

- Bundle index parsing.
- Path lookup.
- Metadata calls.
- Compression and decompression.
- Small-file read amplification.
- Cache-directory locking.
- Atomic writes.

Candidate optimisations must be driven by profiles and upstreamed when they
belong to Tectonic.

### 12.8 Phase E exit gate

- Controlled cold-start benchmarks are reproducible.
- Public-network results are clearly separated.
- Bundle and format identities are present in result metadata.
- Selected core-package or prefetch strategy improves the cold claim corpus
  without unacceptable install-size growth.
- Format-cache behaviour is deterministic and versioned.
- No warm-clean regression exceeds thresholds.
- Empty-cache correctness remains 100%.

---

## 13. Phase F — engine profiling and upstream optimisation

Once wrapper and process overhead are small, the remaining clean-build latency
will largely be inside Tectonic and its engines.

### 13.1 Profiling matrix

Profile at least:

- Tiny document.
- Package-heavy paper.
- TikZ-heavy document.
- Graphics-heavy document.
- Biblatex/Biber document.
- Index document.
- Thesis-scale document.
- Controlled cold-cache document.

On:

- macOS arm64.
- Linux x86-64.
- Linux arm64 where stable hardware is available.

### 13.2 Profiling tools

Use platform-appropriate tools:

- Rust tracing spans.
- Linux `perf`.
- macOS Instruments.
- Allocation profiling.
- Syscall tracing.
- Page-fault and filesystem I/O counters.
- Flamegraphs.
- Binary-size and section analysis.

Profiles must identify both absolute cost and frequency. A hot function with a
small total contribution should not displace work on a larger stage.

### 13.3 Stage-level instrumentation

Instrument:

- Persistent configuration creation.
- Bundle discovery and opening.
- Bundle index parsing.
- Format loading.
- Package lookup and decompression.
- Font discovery and font loading.
- TeX pass 1.
- Later TeX passes.
- BibTeX or Biber.
- Indexing.
- XeTeX processing.
- PDF backend and `xdvipdfmx`-equivalent work.
- Image decoding.
- Font subsetting.
- PDF compression.
- Output writes.

### 13.4 Candidate optimisation areas

Only pursue candidates supported by profiles:

- Avoid repeated persistent-config construction within one invocation.
- Memory-map bundle indexes or other read-mostly structures.
- Reduce repeated path canonicalisation.
- Reduce redundant file metadata calls.
- Cache decompressed high-frequency resources within one process.
- Improve format loading.
- Cache font discovery and metadata within one process.
- Avoid duplicate reads of unchanged intermediates during reruns.
- Improve rerun-change detection.
- Parallelise independent resource downloads.
- Parallelise safe image or font preprocessing.
- Reduce copies between engine output and PDF generation.
- Tune PDF compression where size and speed trade-offs are acceptable.
- Apply profile-guided optimisation to release builds.
- Reduce unnecessary logging and formatting in quiet modes.

Because Phase D is parked, all caches in this phase are process-local or normal
versioned dependency caches. They do not survive as `tectdist` execution state
between invocations.

### 13.5 Upstream-first workflow

For each engine-level change:

1. Add or select a corpus case that exposes the cost.
2. Capture a baseline result and profile.
3. Implement the smallest effective change.
4. Run focused correctness tests.
5. Run the full claim corpus.
6. Record before/after profiles.
7. Submit the change upstream when appropriate.
8. Temporarily pin a reviewed patch only when release value justifies the
   maintenance cost.
9. Remove the local patch after an upstream release contains it.

Every temporary patch must have:

- An owner.
- An upstream issue or pull request.
- A removal condition.
- A compatibility test.
- A benchmark proving its value.

### 13.6 Profile-guided build optimisation

Evaluate PGO only after representative workloads exist.

Training set:

- A balanced subset of the claim corpus.
- Both startup-heavy and engine-heavy documents.
- Bibliography and graphics paths.
- Quiet and normal diagnostics.

Acceptance:

- Improvement is consistent across supported platforms.
- No claim-relevant case regresses materially.
- Build reproducibility remains documented.
- Toolchain complexity is acceptable for Homebrew bottles.

### 13.7 Phase F exit gate

Phase F is an ongoing optimisation phase rather than a single rewrite, but a
release qualification cycle may close it when:

- Flamegraphs exist for every primary workload class.
- The top dominant avoidable costs have recorded decisions.
- Accepted engine changes have full correctness and benchmark evidence.
- Temporary patches have upstream tracking and removal plans.
- Release build flags are justified by corpus-wide measurements.
- Remaining dominant costs are documented as fundamental, upstream-owned, or
  deliberately deferred.

---

## 14. Phase G — release qualification and claim publication

Phase G converts engineering results into a defensible public release.

### 14.1 Qualification freeze

Before qualification:

- Freeze the candidate commit.
- Freeze the corpus revision.
- Freeze competitor installation manifests.
- Freeze engine and bundle identities.
- Freeze compiler toolchains.
- Verify clean worktrees and reproducible build inputs.

Only correctness or benchmark-infrastructure fixes may enter after freeze,
and any change restarts affected sessions.

### 14.2 Required qualification runs

For every supported platform:

- Three independent benchmark sessions.
- At least 30 paired trials per ordinary case.
- At least 15 paired trials per expensive case.
- Candidate versus direct Tectonic.
- Candidate versus previous `tectdist` release.
- Candidate versus TeX Live `latexmk`.
- Other qualified competitors where available.
- Warm-clean suite.
- Controlled cold-cache suite.
- Bibliography and index suites.
- Full correctness oracle.

### 14.3 Aggregate methodology

Publish:

- Per-document medians and p95 values.
- Paired percentage differences.
- 95% confidence intervals.
- Correctness pass rate.
- Engine pass and process counts.
- Platform-specific aggregate.
- Overall claim-corpus aggregate only when cross-platform aggregation is
  methodologically justified.

Do not hide losing cases inside one geometric mean. Every claim-relevant cell
must remain visible.

### 14.4 Claim gates

#### Correctness gate

- 100% claim-corpus correctness.
- No unresolved references or citations.
- No required bibliography or index stage skipped.
- No structural PDF failures.
- No security regression.

#### Performance gate

For the selected claim wording:

- Confidence interval supports the claimed advantage.
- Candidate has the lowest qualified aggregate median.
- Candidate has the lowest qualified aggregate p95.
- No excluded scenario is presented as included.
- Direct Tectonic is visible.
- Previous release is visible.
- Cold and warm results are separate.

For wording that says “fastest in every tested workload,” every claim-relevant
cell must be won. If only the aggregate is won, the wording must say “lowest
aggregate latency.”

#### Reproducibility gate

- Raw samples are published.
- System and tool manifests are published.
- Corpus revision is published.
- Runner source is in the tagged release.
- Summary tables regenerate from raw data.
- Headline numbers are not manually edited.

#### Operational gate

- Homebrew bottle installs pass.
- Source installs pass.
- `doctor` reports a healthy installation.
- External fallback passes.
- Upgrade and rollback are tested.

### 14.5 Claim ladder

Use the strongest wording supported by the release data.

#### Document-specific

> On the published `paper-hyperref` benchmark, tectdist produced a correct,
> fully resolved PDF X% faster than the named competitor on the named platform.

#### Corpus aggregate

> tectdist delivered the lowest aggregate compile latency across the published
> claim corpus on supported macOS and Linux systems.

#### Strong drop-in claim

> tectdist is the fastest drop-in path from supported LaTeX source to a
> correct, fully resolved PDF in our published benchmark suite.

Avoid the unqualified phrase “fastest TeX compiler” unless the product and
corpus truly cover the broader TeX engine and format population implied by
that wording.

### 14.6 Claim freshness

A published claim expires when any of the following changes materially:

- `tectdist` engine implementation.
- Tectonic version.
- Bundle identity.
- Competitor major version.
- TeX Live distribution year.
- Supported platform toolchain.
- Corpus membership or oracle.
- Benchmark runner methodology.

Weekly automation should open a claim-review issue when a competitor or engine
change invalidates the last qualification manifest.

### 14.7 Release artifacts

Each qualifying release should attach:

- Native binaries or package assets.
- SBOM.
- Build provenance.
- Benchmark raw result bundles.
- Generated benchmark summary.
- Corpus manifest hash.
- Tool and platform manifests.
- Reproduction instructions.
- Known limitations and excluded scenarios.

### 14.8 Phase G exit gate

- All four claim gates pass.
- Release artifacts are immutable and reproducible.
- `BENCHMARKS.md` is generated from qualification data.
- README wording matches the exact supported claim.
- Limitations remain prominent.
- Weekly claim-freshness automation is enabled.

---

## 15. Cross-cutting test strategy

### 15.1 Test layers

#### Unit tests

- Flag parsing.
- Pending option values.
- Search-path handling.
- Job-name sanitisation.
- Output-directory rules.
- Pairing cache identity.
- Proxy candidate filtering.
- RC-file parsing.
- Diagnostic mapping.

#### Property and fuzz tests

- Arbitrary argument sequences never panic.
- Paths and job names cannot escape the output directory during rename or
  cleaning.
- `--` terminates option parsing correctly.
- Non-UTF-8 Unix paths survive native parsing.
- Equivalent flag spellings produce equivalent plans.

#### Differential tests

- Python versus Rust.
- Native external executor versus direct external Tectonic.
- Embedded executor versus external executor.

#### Integration tests

- Real Tectonic.
- Real Biber.
- Real indexer.
- Poppler and qpdf proxies.
- Ghostscript tools.
- Homebrew keg paths.
- Shadowed `PATH` cases.

#### Corpus tests

- All documents and scenarios.
- Correctness oracle.
- Performance capture.

#### Packaging tests

- Source build.
- Bottle build.
- Bottle pour.
- Upgrade from previous release.
- Rollback.
- Uninstall.
- Symlink conflict handling.

### 15.2 Performance test hygiene

- Disable unrelated background jobs on self-hosted runners.
- Record thermal and power state where possible.
- Use fixed CPU governor or equivalent stable mode.
- Avoid running benchmark jobs concurrently on the same host.
- Randomise competitor order.
- Retain raw samples.
- Never treat hosted-runner results as release evidence unless variance is
  proven acceptable.
- Re-run qualification after OS or firmware changes.

---

## 16. CI and release pipeline changes

### 16.1 Workflow structure

Recommended workflows:

```text
.github/workflows/
  ci.yml
  compatibility.yml
  perf-pr.yml
  perf-nightly.yml
  perf-weekly-competitors.yml
  build-bottles.yml
  release-qualification.yml
```

### 16.2 `ci.yml`

Retain fast correctness checks:

- Formatting and linting.
- Rust compile and tests after Phase B begins.
- Python reference checks while it remains.
- Acceptance battery mock tier.
- Formula and installer checks.
- Purity or dependency checks applicable to the current architecture.

### 16.3 `compatibility.yml`

- Full acceptance battery.
- Real-engine subset.
- Platform matrix.
- Python/Rust differential suite during migration.
- External/embedded executor differential suite after embedding.

### 16.4 `perf-pr.yml`

- Dispatch to a stable self-hosted runner.
- Compare merge base with candidate.
- Run microbenchmarks and selected corpus subset.
- Upload raw JSON.
- Post a concise pull-request summary.
- Fail only according to versioned regression rules.

### 16.5 `perf-nightly.yml`

- Full corpus.
- All stable benchmark platforms.
- Direct Tectonic and previous release.
- Generated dashboard update.

### 16.6 `perf-weekly-competitors.yml`

- Fresh competitor environments.
- Qualification subset.
- Claim-expiry detection.
- Automatic issue creation with raw evidence.

### 16.7 `release-qualification.yml`

- Manual, versioned dispatch.
- Requires frozen candidate and manifests.
- Runs three sessions or coordinates them across fixed runners.
- Signs or hashes result bundles.
- Generates final benchmark documentation.
- Does not automatically publish a release until maintainers approve the
  generated evidence.

---

## 17. Performance budgets

Budgets make architectural regressions visible.

### 17.1 One-shot budget categories

```text
Total one-shot latency
  = process startup
  + command dispatch
  + plan construction
  + engine resolution or embedded setup
  + bundle and format setup
  + engine passes
  + bibliography/index stages
  + PDF generation
  + artifact post-processing
```

### 17.2 Budget policy

- Each category has a trace span.
- PR reports show category deltas, not only total time.
- An extra process or engine pass requires explicit review.
- A microbudget may regress if a larger end-to-end path improves, but the trade
  must be documented.
- Budgets are platform-specific where necessary.

### 17.3 Initial fixed-overhead budgets

| Category | Phase A target | Phase B target | Phase C target |
|---|---:|---:|---:|
| Process and launcher startup | `< 18 ms` | `< 2 ms` | `< 2 ms` |
| Dispatch and planning | `< 2 ms` | `< 1 ms` | `< 1 ms` |
| Engine resolution and pairing | `< 2 ms` cached | `< 1 ms` cached | Not applicable to embedded default |
| External engine process startup | Existing | Existing | Removed |
| Artifact post-processing without index | `< 1 ms` | `< 1 ms` | `< 1 ms` |

These values must be recalibrated by Phase 0 on stable hardware.

---

## 18. Risk register

### 18.1 Behavioural drift during Rust migration

**Risk:** Native code diverges from the Python compatibility layer.
**Mitigation:** Keep Python as a reference; use differential tests; migrate in
small command groups; require exact external argv comparison.
**Rollback:** Keep the previous Python release installable until the native
release has field validation.

### 18.2 Tectonic API instability

**Risk:** Embedded driver APIs change or expose insufficient events.
**Mitigation:** Pin versions; isolate the integration in `tectdist-engine`;
maintain external fallback; upstream missing hooks.
**Rollback:** Release with native external-engine mode while embedding issues
are resolved.

### 18.3 Biber and biblatex incompatibility

**Risk:** Engine, bundle, and Biber versions drift.
**Mitigation:** Preserve explicit compatibility metadata, doctor checks,
release gates, and real bibliography corpus cases.
**Rollback:** Pin the last known compatible engine/bundle/Biber set.

### 18.4 Benchmark noise or gaming

**Risk:** Optimisations appear beneficial because of load, ordering, or a
narrow corpus.
**Mitigation:** Paired random order, stable hardware, raw samples, confidence
intervals, multiple sessions, visible per-document results.
**Rollback:** Withdraw or narrow the claim automatically when requalification
fails.

### 18.5 Binary size growth

**Risk:** Embedding Tectonic increases download, install, or cold-page-cache
cost.
**Mitigation:** Track size as a release metric; use link-time optimisation and
stripping; measure cold startup; avoid bundling unnecessary features.
**Rollback:** Retain native external-engine packaging as an alternative.

### 18.6 Security regression from embedding or shell escape

**Risk:** In-process execution widens the effect of unsafe input or path bugs.
**Mitigation:** Explicit security stance, fuzzing, path tests, no shell parsing,
external command timeouts, untrusted corpus cases.
**Rollback:** Disable affected features or use external fallback pending a
fix.

### 18.7 Homebrew complexity

**Risk:** Rust, embedded engine, Biber, and architecture builds make bottles
hard to maintain.
**Mitigation:** Reproducible build scripts, locked dependencies, bottle smoke
tests, SBOM, minimal runtime dependency set.
**Rollback:** Temporarily retain external Tectonic or a prior bottle recipe.

### 18.8 Upstream patch maintenance

**Risk:** Local Tectonic patches become a permanent fork.
**Mitigation:** Upstream-first policy, patch owners, removal conditions, and
tracked upstream PRs.
**Rollback:** Drop patches whose maintenance cost exceeds measured benefit.

### 18.9 Unsupported documents undermining the claim

**Risk:** Users interpret “fastest TeX” as universal compatibility.
**Mitigation:** Precise claim population, visible limitations, compatibility
oracle, no silent backend substitution.
**Rollback:** Narrow README wording immediately if qualification or field data
shows ambiguity.

---

## 19. Milestones and issue breakdown

### Milestone 0 — Performance evidence

- `perf-contract`: define correctness, scenarios, platforms, and claim scope.
- `bench-manifest`: add corpus manifest and schema.
- `bench-corpus-core`: add the first 12 representative documents.
- `bench-corpus-bounded`: keep the self-contained fixture corpus small while
  adding only coverage that represents a distinct supported behaviour.
- `bench-runner-paired`: implement randomised paired trials.
- `bench-correctness`: add structural and semantic PDF oracle.
- `bench-results-schema`: store raw samples and system manifests.
- `trace-python`: add one-shot internal timing spans.
- `ci-perf-pr`: add self-hosted PR performance job.
- `ci-perf-nightly`: add full nightly suite.
- `docs-bench-generated`: generate benchmark documentation from results.

### Milestone A — Python fast path

- `core-plan-model`: introduce invocation and plan data models.
- `engine-external-shared`: add one shared external engine executor.
- `latexmk-direct-plan`: remove nested Python dispatch.
- `engine-resolver-single-pass`: unify engine resolution and pairing.
- `index-strategy`: avoid broad scans on reliable common paths.
- `latexmk-lazy-imports`: reduce non-build startup.
- `perf-process-count`: add process-count regression assertions.
- `phase-a-baseline`: publish paired before/after results.

### Milestone B — Native dispatcher

- `rust-workspace`: add workspace and core crate.
- `rust-invocation`: implement `argv[0]` dispatch.
- `rust-plan`: port flag translation and compatibility tables.
- `rust-external-engine`: execute external Tectonic.
- `rust-latexmk`: port supported `latexmk` interface.
- `rust-tools-stubs`: port stubs and proxies.
- `rust-kpsewhich`: port file lookup.
- `rust-gs-tools`: port Ghostscript wrappers.
- `diff-python-rust`: run complete behavioural comparison.
- `formula-native`: build native Homebrew package without Python.
- `release-native`: publish native external-engine release.

### Milestone C — Embedded engine

- `engine-tectonic-link`: pin and link Tectonic.
- `engine-plan-mapping`: map `CompilationPlan` to driver settings.
- `engine-status-backend`: structured diagnostics.
- `engine-output-events`: capture reads, writes, and passes.
- `engine-index-events`: replace common directory scans.
- `engine-bibliography`: preserve Biber integration and health checks.
- `engine-security`: trusted/untrusted and shell-escape tests.
- `engine-external-fallback`: retain diagnostic mode.
- `formula-embedded`: remove required external Tectonic dependency.
- `release-embedded`: publish qualified embedded-engine release.

### Milestone D — Parked

No active implementation issues. Maintain one tracking issue labelled
`parked` containing the re-entry criteria from Section 11.

### Milestone E — Cold start

- `bench-cold-controlled`: local deterministic package source.
- `bundle-identity`: record immutable bundle metadata.
- `bundle-profile`: profile index, lookup, and decompression.
- `package-core-experiment`: measure bundled core package set.
- `package-prefetch-experiment`: measure source pre-scan and prefetch.
- `format-cache-experiment`: evaluate pre-generated formats.
- `tectdist-warm-design`: evaluate explicit pre-warm command.
- `cold-release-gate`: publish controlled cold results.

### Milestone F — Engine optimisation

- `profile-matrix`: produce platform and workload flamegraphs.
- `engine-hotspots`: prioritised hotspot report.
- `upstream-bundle`: submit bundle access improvements.
- `upstream-format`: submit format-loading improvements.
- `upstream-fonts`: submit font-discovery improvements if justified.
- `upstream-pdf`: submit PDF backend improvements if justified.
- `release-pgo`: evaluate and qualify profile-guided builds.

### Milestone G — Claim release

- `qual-freeze`: freeze candidate, corpus, and competitors.
- `qual-macos-arm64`: three-session qualification.
- `qual-linux-x86_64`: three-session qualification.
- `qual-linux-arm64`: three-session qualification where supported.
- `claim-generator`: derive README wording and badge data.
- `claim-freshness`: weekly expiry automation.
- `release-evidence`: attach raw results and provenance.
- `release-fastest`: publish the strongest supported claim.

---

## 20. Delivery order and dependencies

Recommended implementation order:

```text
Phase 0 benchmark contract
        |
        v
Phase 0 runner + correctness + tracing
        |
        +----------------------------+
        |                            |
        v                            v
Phase A Python fast path       Performance CI
        |
        v
Phase B native external-engine implementation
        |
        v
Native release and field validation
        |
        v
Phase C embedded engine
        |
        +----------------------------+
        |                            |
        v                            v
Phase E cold-start work       Phase F engine profiling
        |                            |
        +-------------+--------------+
                      |
                      v
             Phase G qualification
```

Phase D has no dependency edge because it is parked.

### 20.1 Suggested pull-request sizing

Prefer pull requests that:

- Change one architectural boundary at a time.
- Include tests and benchmark output.
- Avoid combining semantic expansion with a performance rewrite.
- Keep generated benchmark results separate from runner logic where practical.
- Preserve an easy rollback path.

A language migration pull request should not simultaneously embed Tectonic.
An engine embedding pull request should not simultaneously introduce new
`latexmk` features.

---

## 21. Pull-request performance checklist

Every performance pull request should answer:

- [ ] Which user-visible path is being improved?
- [ ] Which trace span or profile identified the cost?
- [ ] What is the baseline commit?
- [ ] What benchmark cases exercise the change?
- [ ] Are trials paired and randomised?
- [ ] Are raw samples attached?
- [ ] What is the median and p95 change?
- [ ] What is the confidence interval?
- [ ] Did process count change?
- [ ] Did engine pass count change?
- [ ] Did peak memory or binary size regress?
- [ ] Does the full correctness oracle pass?
- [ ] Does the acceptance battery pass?
- [ ] Are there platform-specific effects?
- [ ] Is the change upstream-owned?
- [ ] What is the rollback plan?

---

## 22. Definition of done

The active programme is complete when:

### Evidence

- The public corpus is representative and licence-audited.
- Correctness is machine-checked.
- Raw benchmark results and system manifests are published.
- Benchmark summaries are generated rather than hand-edited.

### Implementation

- The installed product is a native binary.
- The default compiler path embeds Tectonic.
- The common `latexmk` path has no nested wrapper process.
- Direct tool proxies replace the wrapper process.
- Engine and bundle identities are explicit.
- External Tectonic remains available as a tested fallback.

### Performance

- Native fixed overhead meets the release budget.
- Embedded execution is not materially slower than direct Tectonic on any
  primary clean-build category.
- Cold-start improvements are measured separately and reproducibly.
- Dominant engine costs have profile-backed decisions.

### Correctness and operations

- Acceptance battery and claim corpus pass on all supported platforms.
- Homebrew source and bottle paths pass.
- Security and shell-escape tests pass.
- Upgrade, rollback, and doctor flows pass.

### Claim

- Qualification sessions pass all gates.
- Public wording matches the evidence exactly.
- Limitations remain visible.
- Claim-freshness automation is active.

Phase D is not required for this definition of done.

---

## 23. Branch completion and release handoff

This branch contains the compact corpus and schemas, paired randomised runner,
layered correctness oracle, generated reports, qualification enforcement,
Python trace/plan/executor refactor, native dispatcher and tool farm, embedded
and external Tectonic executors, cold-cache accounting, one-shot warming,
MakeIndex bootstrap, differential tests, and native source installation.

The self-contained claim corpus is intentionally only 12 documents, 15 files,
and about 64 KB. The pinned University of Stuttgart QFT workload is an optional
742,627-byte fetch and is excluded from aggregate claims. This keeps routine
development bounded without losing an available real-world stress case.

The next actions belong to a future release effort, not this branch:

1. Run CI and the stable multi-platform qualification sessions.
2. Freeze candidate, competitor, bundle, and format-cache identities.
3. Review generated evidence and decide the narrowest supported claim.
4. Build and test Homebrew bottles from the qualified native artifact.
5. Publish only after explicit maintainer approval.

Phase D remains parked.
