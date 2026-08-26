# tectdist O100 / X10-X100 Continuation Plan

**Status:** Active architectural reset and continuation plan  
**Canonical file:** `docs/BASICTEX_X10_PLAN.md` (filename retained so existing links do not break)  
**Supersedes:** the runtime-coupled BasicTeX plan previously stored at this path, `docs/FULL_COMPATIBILITY_X10_PLAN.md`, and the execution assumptions in `docs/BT100_STATUS.md`  
**Audit range:** `bd9c37ee43041421e6fbf11f324436290e314f7d..e1afa97230a92b20eab9971dd414d18b88fa448c`  
**Audited changes:** 124 commits  
**Continuation baseline:** `e1afa97230a92b20eab9971dd414d18b88fa448c`  
**Oracle:** pinned BasicTeX 2026, used only in build, test, and qualification infrastructure  
**Runtime rule:** production tectdist must neither discover, execute, link against, nor fall back to an installed BasicTeX distribution  
**Compatibility goal O100:** tectdist independently implements the complete observable behaviour of the pinned BasicTeX oracle for the declared command, engine, format, package, font, configuration, and output universe  
**Performance goal:** X10-X100 improvements for the explicitly named warm-clean, rebuild, and edit scenarios, with correctness and publication time included  
**Footprint goal:** a small signed bootstrap plus lazily materialised engine and package shards; no copied BasicTeX installation and no full TeX Live payload  
**Release rule:** O100 compatibility and the applicable performance gate must pass on the same signed tectdist build

---

## 0. Executive reset

The work ending at `e1afa97230a92b20eab9971dd414d18b88fa448c` has produced valuable infrastructure:

- a pinned BasicTeX oracle and extensive evidence capture;
- a native command layer and per-user supervisor;
- project locking, cancellation, telemetry, and action caching;
- an unchanged-rebuild fast path that exceeds X10;
- a project-format experiment that proves package initialisation can be reused;
- an embedded MakeIndex path;
- mutation and differential testing;
- experimental pdfTeX and XeTeX fork-server patches;
- supervisor-side checkpoint and output-graph models.

It has also reached the limit of its current architecture.

The release gate is green for the existing differential checks but fails the two engine-cost edit scenarios: body edits are approximately 2.1x and structural edits approximately 1.8x, while unchanged rebuilds are approximately 13.3x. The current supervisor can avoid work or skip preamble loading, but it still re-executes nearly the entire TeX body and output backend. The checkpoint and output-graph code does not yet contain real engine state or real page objects. The native fork-server approach has become engine-specific, build-system-specific, and fragile: pdfTeX works, XeTeX is inconsistent across the recorded commits and the final committed binary exits after resume, and LuaHBTeX requires a separate integration strategy.

The previous plan compounded this by treating an extracted BasicTeX tree as both the oracle and the production compatibility fallback. That is no longer acceptable.

This plan makes four decisive changes.

### 0.1 BasicTeX becomes an oracle only

BasicTeX defines expected behaviour and the deployment scope. It is not a runtime dependency.

Production tectdist will ship its own independently built engines, tools, package files, formats, maps, indexes, and configuration derived from pinned upstream sources. A compatibility miss escalates to tectdist's own exact execution lane, never to BasicTeX.

### 0.2 The runtime is split into an exact lane and an accelerated lane

The exact lane is a tectdist-owned, one-shot implementation of the pinned oracle semantics. It is always available and is the internal correctness authority.

The accelerated lane uses snapshots, replay, and output reuse. It may serve a request only when its proof obligations pass. Otherwise the same request is run by the exact lane.

```text
request
  -> classify semantic contract
  -> construct exact BuildSpec
  -> acceleration eligibility + proof
       -> accelerated execution
       -> validate
       -> publish
     OR
       -> tectdist exact execution
       -> validate
       -> publish
```

There is no BasicTeX fallback anywhere in this graph.

### 0.3 Snapshotting is moved behind a runtime abstraction

The current native fork-server work is retained as evidence and as an optional pdfTeX experiment, but it is no longer the sole route to X10-X100.

The primary continuation experiment is an AOT WebAssembly engine runtime because TeX Live 2026 pdfTeX, XeTeX, LuaHBTeX, BibTeX, MakeIndex, `xdvipdfmx`, and Kpathsea utilities have already been built into a single WebAssembly/static toolchain by TeXlyre BusyTeX. This does not prove that its current product is a drop-in tectdist runtime, but it proves that the three principal engines can cross the WASM boundary. Linear memory provides a much more uniform snapshot surface than post-initialisation native `fork()` across Web2C globals, C++, ICU, Fontconfig, HarfBuzz, and an embedded Lua VM.

The architecture is deliberately pluggable:

```rust
trait SnapshotRuntime {
    fn prepare(&self, image: &EngineImage) -> Result<PreparedEngine>;
    fn instantiate(&self, prepared: &PreparedEngine) -> Result<EngineInstance>;
    fn run_until(
        &self,
        instance: &mut EngineInstance,
        stop: StopCondition,
        request: &BuildRequest,
    ) -> Result<RunOutcome>;
    fn capture(
        &self,
        instance: &EngineInstance,
        host: &HostState,
        reason: SnapshotReason,
    ) -> Result<Snapshot>;
    fn clone_snapshot(&self, snapshot: &Snapshot) -> Result<EngineInstance>;
    fn restore_host(&self, snapshot: &Snapshot) -> Result<HostState>;
}
```

Planned implementations:

1. `WasmAotRuntime` — primary feasibility and production candidate.
2. `NativeForkRuntime` — transitional pdfTeX path and benchmark control.
3. `ArenaRuntime` — fallback design if AOT WASM cannot meet parity or latency gates; engine globals and allocations are placed in a page-backed relocatable arena with copy-on-write snapshots.

The programme must not spend further cycles patching generated engine C without first passing the runtime feasibility gates in this plan.

### 0.4 Performance claims become scenario-specific

The intended end state is:

- **X50-X100 unchanged rebuild:** no engine execution, client-visible response from a trusted change journal.
- **X10-X100 local body edit:** restore a project or page checkpoint, replay only affected work, reuse the converged suffix and unchanged output objects.
- **X10 structural edit:** replay from the earliest affected structural checkpoint and reuse a suffix only after strong state convergence.
- **X10 warm-clean on qualified common stacks:** clone a project-neutral package-prefix snapshot, then execute project-specific input.
- **X3-X5 general warm-clean as an intermediate gate:** exact engine and package initialisation are warm, but no project state exists.
- **No universal X100 cold-build claim.**

All ratios include client IPC, dependency checking, engine execution, helper actions, output assembly, validation, and atomic publication.

### 0.5 Audited checkpoint at `e1afa972`

| Gate or subsystem | Audited result | Plan interpretation |
|---|---:|---|
| workspace tests | 90 passed | strong base, retain |
| differential battery | pass | retain and extend |
| bibliography differential | pass | retain |
| package report | 195 pass, 0 candidate fail, 65 oracle-blocked, 112 untested | not O100 closure; test taxonomy must cover every row |
| document equivalence | 14/14 | retain |
| failure equivalence | 65/65 | retain |
| unchanged rebuild | 13.3x | first X10 success; journal can move it toward X100 |
| body edit | 2.078x | engine/body/backend work still dominates |
| structural edit | 1.839x | checkpoint/replay and output reuse required |
| warm-clean | not implemented | requires project-neutral snapshots |
| pdfTeX fork server | working in recorded batteries | keep as control/prototype |
| XeTeX fork server at final head | server starts; resumed children exit 1 and exact fallback runs | do not build the roadmap around this continuation point |
| LuaHBTeX fork server | not implemented | use runtime abstraction rather than another bespoke loop |

The recorded documents disagree about whether XeTeX is “done”: an earlier status snapshot describes working paths, while the final engine-build README and head commit record resumed-child failure. The plan therefore treats generated gate artefacts and the final head as authoritative and requires status documentation to be generated rather than manually reconciled.

---

# Part I — Audit and disposition

## 1. What changed in the audited 124 commits

The audited range added or materially changed the following systems.

| Area | Delivered | Current maturity |
|---|---|---|
| Oracle capture | package TLPDB, file hashes, binaries, formats, Kpathsea state, licences | retain |
| Oracle corpus | BasicTeX-specific documents, pipeline cases, package probes, interactions | retain and deepen |
| Native supervisor | private Unix socket, project locks, cancellation, status, telemetry | retain and split into modules |
| Rebuild gate | whole-project content hashing and existing-output reuse | retain concept; replace scan with journal |
| Project formats | preamble/body split and per-project dumped format | retain as experiment; replace parser/format mechanism |
| Action broker | exact helper execution and content-addressed restore | retain and harden |
| Engine fork servers | generated-C patch plus pdfTeX/XeTeX binaries | quarantine as prototype; do not ship committed binaries |
| Checkpoints | metadata structures and unit tests | replace with records produced by a real engine runtime |
| Output graph | logical page/resource models and content store | retain concepts; replace unsafe assumptions and wire to backend |
| Release gates | compatibility, equivalence, edit scenarios | retain; redefine O100 and add coverage closure |
| Runtime image | copy of frozen BasicTeX payload | remove from production design; oracle only |
| Evidence | large committed JSON/evidence files | keep release evidence, move transient data to CI artefacts/releases |

## 2. What is production-ready

The following pieces should be preserved and promoted.

### 2.1 Measurement discipline

Keep:

- untraced timed runs;
- separate traced diagnostic runs;
- wait-based per-child resource measurement;
- balanced pair order and recorded seed;
- immutable binary provenance;
- gate code that exercises both pass and fail paths;
- correctness checks before a timing sample is accepted.

### 2.2 Supervisor lifecycle primitives

Keep:

- private per-user socket directory and restrictive permissions;
- per-project exclusion;
- cancellation;
- crash and wedge recovery;
- bounded helper execution;
- atomic publication;
- explicit counters and structured responses.

Refactor the current monolithic `main.rs` into:

```text
tectdist-supervisor/
  protocol.rs
  service.rs
  project_registry.rs
  journal.rs
  scheduler.rs
  exact_lane.rs
  accelerator.rs
  actions.rs
  snapshots.rs
  outputs.rs
  telemetry.rs
```

### 2.3 Oracle capture and differential harness

Keep the frozen BasicTeX manifest generator and pairwise comparisons, but move all BasicTeX execution behind test-only interfaces.

```rust
#[cfg(feature = "oracle-tools")]
trait OracleRunner {
    fn run(&self, case: &OracleCase) -> OracleResult;
}
```

No production crate may depend on `OracleRunner`, a BasicTeX path, or `TECTDIST_BASICTEX_ROOT`.

### 2.4 Exact helper caching

Keep the action-broker design. Its key must be expanded and its file discovery must come from actual execution rather than caller-declared lists alone.

### 2.5 Mutation and shadow verification

Keep and extend mutation fuzzing. It is central to safe reuse.

## 3. What must be reworked

### 3.1 The “BasicTeX profile” runtime

Current code launches binaries and copies formats from an extracted BasicTeX tree. Replace this with a tectdist runtime pack assembled from:

- pinned TeX Live source revision;
- pinned platform toolchain;
- the oracle TLPDB's run-file/font/format closure;
- tectdist-owned configuration generation;
- signed tectdist manifests.

BasicTeX remains one side of the comparator only.

### 3.2 Project-format source splitting

The current fast path searches source text for exactly one line-start `\begin{document}`, statically scans literal `\input`/`\include`, declines macro-indirected inputs, and supports only the pdfTeX family.

This is a useful experiment, not a compatibility mechanism.

Replace it with a semantic pause emitted by the engine after LaTeX has executed class/package loading and begin-document hooks. All dependencies are observed through the host VFS. No source parser guesses where the preamble ends.

### 3.3 Fork-server patches

The current patch:

- is appended to generated/shared C;
- embeds a text protocol and debug logging;
- injects the job name into Web2C buffers;
- relies on engine-specific continuation points;
- waits synchronously in the parent;
- has no structured environment or file-descriptor reset protocol;
- does not solve LuaHBTeX;
- commits platform binaries into Git.

Quarantine it under `experiments/native-fork/` after extracting the reusable tests and measurements. Production must use reproducible source patches and CI-built release assets. The current binaries must not be part of normal source history after the migration commit.

### 3.4 Checkpoint records

The current supervisor records project file hashes in fields named `engine_state_digest`, `dependency_epoch`, and `shipped_pages`. This is scaffolding, not a checkpoint.

A production checkpoint must be minted by the running engine/runtime and include a restorable state image plus host state. Until then, checkpoint APIs must report `model_only` and may not influence production routing.

### 3.5 Output graph assumptions

The current model may reuse a page when page bytes match even if a referenced font/resource changes. That is unsafe unless the page identity includes the full transitive resource closure.

Production page identity is:

```text
PageIdentity =
    hash(
        canonical_page_content,
        ordered_annotations,
        destinations,
        links,
        inherited_boxes,
        transitive_resource_digests,
        tagging_parent_tree_inputs,
        backend_version
    )
```

### 3.6 Unchanged-rebuild scanning

Hashing every file in the project on every command is correct but consumes much of the 12 ms result and scales poorly.

Replace it with an OS change journal plus periodic audit:

- macOS FSEvents;
- Linux inotify/fanotify;
- a conservative directory generation;
- content hashing only for changed candidates;
- an occasional full digest audit;
- immediate exact execution if event continuity is lost.

## 4. What should be removed or moved

The continuation programme should schedule a hygiene PR that:

- removes committed engine executables from Git and publishes them only as CI artefacts or signed release assets;
- removes root-level generated `texput.fmt`;
- moves generated oracle installer expansion out of the normal working tree;
- moves large transient benchmark JSON to release evidence storage while preserving concise signed summaries and schemas in Git;
- marks `docs/FULL_COMPATIBILITY_X10_PLAN.md` superseded;
- replaces stale status claims with generated status from gate artefacts;
- removes production references to `TECTDIST_BASICTEX_ROOT`;
- removes code paths that execute a BasicTeX binary as fallback.

---

# Part II — Non-negotiable contracts

## 5. O100 compatibility contract

Let:

- `O` be the pinned BasicTeX oracle image;
- `R` be the tectdist runtime built independently from pinned upstream sources;
- `C` be a command and argument vector present in the oracle deployment scope;
- `P` be a project whose required inputs are within the oracle package closure, project tree, allowed user overlays, and declared external environment.

The requirement is:

```text
observe(O, C, P) == observe(R, C, P)
```

within a documented equivalence relation.

`observe` includes:

- exit status and fatal/non-fatal class;
- stdout/stderr diagnostic class and source locations;
- requested semantic engine;
- format selection;
- Kpathsea lookup results and ordering;
- file-read and file-write graph;
- PDF, DVI, XDV, PostScript, HTML, SyncTeX, log, recorder, and auxiliary outputs applicable to the command;
- page count and rasterised visual equivalence;
- extracted text;
- links, destinations, outlines, labels, citations, indexes, tags, and metadata;
- shell-escape invocations and produced files;
- output directory, job name, interaction, and recorder semantics;
- locale, source-date, clock, random, and environment behaviour where observable.

BasicTeX may fail because its own base closure lacks a dependency or because a probe is invalid for the selected engine. O100 means tectdist reproduces that observable result for the same test. It does not mean “all 372 package names compile under pdfLaTeX.”

## 6. Oracle coverage closure

The current report has 195 passing probes, 65 reference-blocked probes, and 112 “untested” packages. The release gate must eliminate “untested” as a final category.

Every oracle package row must have one of these machine-verifiable test classes:

```text
style_or_class
font_or_map
engine_binary
helper_binary
format
hyphenation
configuration
data_file
collection_or_meta
oracle_expected_fail
```

Each class has a specific assertion.

Examples:

```text
font_or_map:
  resolve every installed TFM/map/font family through oracle and candidate
  typeset an engine-appropriate glyph sheet
  compare metrics, subset font identity, and raster output

hyphenation:
  load the appropriate format/language
  compare \showhyphens or node-list output

configuration:
  compare resolved Kpathsea variables and representative lookups

collection_or_meta:
  verify exact transitive file/package closure; no compile probe required

oracle_expected_fail:
  run the same engine-appropriate case on both sides
  require equivalent failure class and no candidate crash
```

O100 release gate:

```text
unclassified_package_rows == 0
untested_package_rows == 0
unexplained_oracle_failures == 0
candidate_mismatches == 0
```

## 7. Runtime independence contract

Production runtime and installed artefacts must pass:

```text
grep runtime dependency graph for:
  BasicTeX installer paths
  TECTDIST_BASICTEX_ROOT
  /usr/local/texlive/*basic
  oracle expanded payload paths

expected matches:
  zero outside test/oracle tools
```

The installer must work on a machine that has never installed TeX, BasicTeX, MacTeX, or TeX Live.

## 8. Footprint contract

The target is a lightweight deployment, not a copied TeX distribution.

Initial engineering budgets:

| Component | Compressed budget |
|---|---:|
| CLI + supervisor + metadata | <= 8 MiB |
| shared AOT engine code for pdfTeX/XeTeX/LuaHBTeX | <= 35 MiB |
| always-present package/config/font bootstrap | <= 20 MiB |
| typical first-project active set | <= 50 MiB |
| complete offline oracle-equivalent pack | <= 120 MiB |
| per-project persistent metadata excluding user outputs | <= 32 MiB by default |
| resident idle RSS, no project snapshot | <= 96 MiB |
| resident RSS with one active project snapshot | <= 256 MiB target, hard configurable cap |

These are gates to be measured and adjusted only through a recorded architecture decision. Source archives, documentation, and package files not installed by the oracle do not enter the runtime pack.

## 9. Performance contracts

### 9.1 X100-U unchanged rebuild

After one successful build, with no relevant input or environment change:

```text
p50 <= max(1.5 ms, oracle_p50 / 100)
p95 <= max(3.0 ms, oracle_p95 / 50)
```

The timer includes client startup, IPC, journal validation, output existence/integrity check, and response.

### 9.2 X10-L local visible edit

For a local body/equation edit that affects a bounded page range:

```text
candidate_p50 <= oracle_p50 / 10
candidate_p95 <= oracle_p95 / 8
```

The result must contain the visible edit and pass full output validation.

### 9.3 X10-S structural edit

For section/reference/TOC edits:

```text
candidate_p50 <= oracle_p50 / 10
```

The engine may replay from an earlier checkpoint and may require additional convergence passes, but the final output must be fully resolved.

### 9.4 X10-W warm-clean

Runtime, engines, formats, immutable indexes, and project-neutral snapshots may be warm. No project output, project snapshot, project action result, or project checkpoint may exist.

```text
candidate_suite_median <= oracle_suite_median / 10
```

This is the hardest gate. The programme first targets X3 and X5 before requiring X10.

### 9.5 Arbitrary shell escape

tectdist executes arbitrary permitted user commands exactly. Compiler overhead may be accelerated, but no ratio is promised for user code itself. Reports separate:

```text
engine_ms
tectdist_helper_ms
user_command_ms
validation_ms
publication_ms
```

---

# Part III — Target architecture

## 10. System overview

```text
traditional command name
        |
        v
tectdist client (small native multicall binary)
        |
        | private versioned IPC
        v
tectdist supervisor
        |
        +-- BuildSpec normaliser
        |     semantic engine/format
        |     arguments and environment
        |     output contract
        |
        +-- project journal
        |     file generations
        |     changed content digests
        |     last exact build manifest
        |
        +-- route planner
        |     exact lane
        |     accelerated lane
        |     shadow verification
        |
        +-- SnapshotRuntime pool
        |     AOT pdfTeX
        |     AOT XeTeX
        |     AOT LuaHBTeX
        |
        +-- host VFS/Kpathsea layer
        |     signed package shards
        |     project and user overlays
        |     dependency/read-interval log
        |
        +-- action broker
        |     exact helpers
        |     safe result reuse
        |
        +-- output graph
        |     pages
        |     fonts/images/resources
        |     annotations/tags/outlines
        |
        +-- validator and publisher
              exact/shadow comparison
              atomic outputs
```

## 11. BuildSpec: one canonical request model

Every front-end command is translated into an immutable `BuildSpec`.

```rust
struct BuildSpec {
    schema: u32,
    profile: RuntimeProfileId,
    command: CommandIdentity,
    engine: EngineIdentity,
    format: FormatIdentity,
    argv: Vec<OsString>,
    cwd: CanonicalPath,
    primary_input: InputSpec,
    output: OutputContract,
    environment: EnvironmentView,
    security: SecurityPolicy,
    clock: ClockPolicy,
    locale: LocaleIdentity,
    overlays: Vec<OverlayIdentity>,
}

struct OutputContract {
    jobname: OsString,
    output_directory: CanonicalPath,
    requested_kinds: BTreeSet<OutputKind>,
    keep_logs: bool,
    keep_intermediates: bool,
    synctex: bool,
}
```

The same `BuildSpec` is used by:

- the exact lane;
- the accelerated lane;
- the oracle comparator in CI;
- the result cache;
- benchmark records.

No acceleration path reparses user source or reconstructs command semantics independently.

## 12. Exact internal lane

The exact lane replaces the current BasicTeX runtime fallback.

It contains tectdist-built, pinned implementations of every engine/tool required by the oracle scope:

- pdfTeX/e-pdfTeX and formats;
- XeTeX;
- LuaHBTeX/LuaTeX;
- TeX/e-TeX DVI formats;
- BibTeX/bibtex8 if present in scope;
- MakeIndex;
- MetaPost/MetaFont;
- `xdvipdfmx`, `dvips`, and `tex4ht` paths in scope;
- Kpathsea helpers and configuration behaviour.

The exact lane may initially be native one-shot binaries. It must be built in CI from pinned sources and packaged by tectdist. It must not call a separately installed TeX distribution.

```rust
fn run_exact(spec: &BuildSpec, runtime: &RuntimePack) -> Result<BuildResult> {
    let tool = runtime.resolve_exact_tool(&spec.command)?;
    let sandbox = ExactSandbox::prepare(spec, runtime)?;
    let status = sandbox.exec(tool, &spec.argv, &spec.environment)?;
    let manifest = sandbox.finish_manifest()?;
    let artifacts = collect_and_validate(spec, &manifest)?;
    Ok(BuildResult::exact(status, manifest, artifacts))
}
```

The exact lane is the escalation target for:

- an acceleration eligibility miss;
- snapshot corruption;
- event-journal discontinuity;
- unsupported shell behaviour;
- checkpoint non-convergence;
- output assembly uncertainty;
- an accelerated crash.

The result records the route. Silent semantic switching is forbidden.

## 13. Snapshot runtime abstraction

### 13.1 Why the native fork prototype is not enough

Native `fork()` is excellent for pdfTeX's mostly single-threaded C state. It is not a uniform production solution for:

- XeTeX with C++ libraries, ICU, Fontconfig, and font caches;
- LuaHBTeX with a live Lua VM and callback state;
- cross-platform support where `fork()` semantics differ or are unavailable;
- persistent serialisable project snapshots;
- fine-grained page checkpoint storage.

The continuation must not require a bespoke post-format-load resume surgery for every engine before any other work can proceed.

External feasibility references:

- [TeXlyre BusyTeX build](https://github.com/TeXlyre/texlyre-busytex-build) compiles TeX Live 2026 pdfTeX, XeTeX, LuaHBTeX, BibTeX, MakeIndex, `xdvipdfmx`, and Kpathsea utilities for static Linux and WebAssembly targets.
- [TeXlyre BusyTeX runtime](https://github.com/TeXlyre/texlyre-busytex) demonstrates multi-file pdfLaTeX, XeLaTeX, and LuaLaTeX execution in a browser worker.

These projects are feasibility inputs, not dependencies that may be copied blindly. tectdist must pin sources, audit patches and licences, replace browser-oriented filesystem/shell assumptions, and pass its own exact oracle.

### 13.2 AOT WebAssembly feasibility lane

Build the pinned engine/tool source into a WASM module with no ambient filesystem. All I/O crosses explicit host imports.

Required exports:

```c
int td_engine_init(const td_engine_config *cfg);
int td_compile(const td_request *req);
int td_continue(void);
int td_request_stop(enum td_stop_reason reason);
void td_reset_job_state(void);
```

Required host imports:

```c
int64_t td_open(const uint8_t *name, size_t len, uint32_t flags);
int64_t td_read(int64_t handle, uint8_t *dst, size_t len);
int64_t td_seek(int64_t handle, int64_t off, uint32_t whence);
int64_t td_write(int64_t handle, const uint8_t *src, size_t len);
int32_t td_close(int64_t handle);

int32_t td_kpse_find(
    const uint8_t *name, size_t name_len,
    uint32_t format, uint8_t *result, size_t cap
);

int32_t td_checkpoint(uint32_t kind, const td_checkpoint_meta *meta);
int32_t td_action(const td_action_request *req, td_action_result *out);
int64_t td_clock(uint32_t clock_kind);
int32_t td_random(uint8_t *dst, size_t len);
int32_t td_log(uint32_t level, const uint8_t *msg, size_t len);
```

The module is compiled ahead of time for each release platform. JIT compilation is not on the timed path.

### 13.3 Feasibility gate

The AOT WASM route proceeds only if the pdfTeX spike passes all gates:

1. It compiles the entire pdfTeX oracle corpus with zero unexplained mismatches.
2. A one-shot AOT instance is no more than 15% slower than tectdist's native exact pdfTeX lane on the warm-clean corpus before snapshot reuse.
3. A format-loaded snapshot can be cloned and entered in <= 1.0 ms p50 and <= 2.0 ms p95.
4. Snapshot restore produces deterministic dependency and output manifests.
5. Memory can be bounded, reclaimed, and isolated after malformed input.
6. SyncTeX, recorder, shell-escape mediation, and error exits match the exact lane.
7. The toolchain and modifications are reproducible and licence-compatible.

Failure of one gate triggers a written decision:

- fix a bounded, measured runtime issue;
- use `ArenaRuntime`;
- retain native fork only for pdfTeX while continuing a different runtime for XeTeX/LuaHBTeX.

It does not trigger indefinite debugging of one generated-C resume location.

### 13.4 ArenaRuntime fallback

If AOT WASM has unacceptable overhead, convert the engine's mutable state into a page-backed arena.

Concept:

```c
struct td_arena {
    uint8_t *base;
    size_t capacity;
    size_t committed;
    td_host_handles host;
};

#define TD_GLOBAL(type, name) \
    (*(type *)(td_current_arena->base + TD_OFFSET_##name))
```

All engine-owned dynamic allocations use arena allocators. External library objects that cannot be copied are represented by stable host handles and reconstructed on restore.

Snapshots use immutable mappings plus `MAP_PRIVATE` copy-on-write pages:

```rust
fn capture_arena(instance: &ArenaInstance) -> Snapshot {
    instance.quiesce();
    Snapshot {
        memory: seal_memfd(instance.arena_mapping()),
        globals: instance.scalar_manifest(),
        host: instance.host_state.snapshot(),
        engine_identity: instance.identity(),
    }
}

fn clone_arena(snapshot: &Snapshot) -> ArenaInstance {
    let mapping = mmap_private(snapshot.memory);
    ArenaInstance::from_mapping(mapping, snapshot.host.clone())
}
```

This is more invasive than WASM but remains systematic. The programme explicitly forbids manually serialising hundreds of individual Web2C globals as the primary design.

## 14. Host VFS and exact Kpathsea model

### 14.1 Runtime file layers

The VFS resolves, in order:

1. generated in-memory job files;
2. project tree;
3. declared user overlay;
4. declared local overlay;
5. immutable tectdist package shards;
6. generated format/map/cache layer.

Each layer has an identity and generation.

```rust
enum VfsLayer {
    Memory(JobMemoryFs),
    Project(ProjectFs),
    UserOverlay(VersionedFs),
    LocalOverlay(VersionedFs),
    PackageShard(ImmutableShardSet),
    Generated(VersionedFs),
}
```

### 14.2 Observed dependency records

Every successful read produces an exact record:

```rust
struct ReadRecord {
    logical_name: TeXPath,
    resolved_layer: LayerId,
    content_digest: Digest,
    open_sequence: u64,
    intervals: IntervalSet,
    first_engine_epoch: u64,
    last_engine_epoch: u64,
    checkpoint_before_first_read: Option<CheckpointId>,
}
```

Read intervals matter. A change to bytes never read by a run need not invalidate an earlier checkpoint, while any ambiguity is conservative.

### 14.3 Kpathsea parity

The host can initially embed real Kpathsea behind the imports. Optimisation occurs by:

- memory-mapping immutable `ls-R`/generated indexes;
- parsing configuration once per runtime profile;
- generation-keyed overlay caches;
- negative lookup caching by generation;
- preserving program-name-specific paths, brace expansion, empty components, and environment overrides.

A rewritten Kpathsea implementation is not a release prerequisite.

## 15. Lightweight package runtime

### 15.1 Oracle-derived file scope, tectdist-owned pack

The oracle TLPDB and file manifest decide which package files are in scope. The deployment pack is generated independently.

Do not copy the expanded BasicTeX directory.

```python
def build_runtime_pack(oracle_tlpdb, oracle_files, upstream_repo, target):
    scope = resolve_installed_run_closure(oracle_tlpdb)
    scope += required_generated_formats(oracle_tlpdb)
    scope += required_maps_and_font_databases(oracle_tlpdb)

    entries = []
    for logical_path in canonical_order(scope):
        source = fetch_verified_upstream_file(upstream_repo, logical_path)
        assert digest(source) == oracle_files[logical_path]
        entries.append(normalize_entry(logical_path, source))

    shards = partition_by_access_and_dependency(entries)
    for shard in shards:
        write_zstd_seekable_shard(shard, trained_dictionary(shard.kind))
        sign_manifest(shard.manifest)

    assert no_docs_or_sources_unless_oracle_installed(entries)
    assert compressed_size(shards) <= footprint_gate
```

### 15.2 Shard classes

```text
bootstrap:
  texmf.cnf, format metadata, core LaTeX/base files, maps/indexes

engine-pdftex:
  pdfTeX binary/module and engine-specific assets

engine-xetex:
  XeTeX binary/module, ICU data subset, font index, xdvipdfmx assets

engine-luahbtex:
  LuaHBTeX module, Lua modules, luaotfload index

packages-<cluster>:
  package run files grouped by dependency and observed co-use

fonts-<cluster>:
  font programs/metrics/maps grouped independently

tools:
  BibTeX, MakeIndex, MetaPost, dvips, tex4ht, and support data
```

### 15.3 Lazy materialisation

A signed manifest maps logical TeX paths to a shard, offset, length, and digest. Missing shards are fetched from tectdist's signed package service or installed from an offline pack.

```rust
fn vfs_open(path: &TeXPath) -> Result<Handle> {
    let entry = runtime_index.lookup(path)?;
    if !shard_cache.contains(entry.shard) {
        shard_cache.fetch_and_verify(entry.shard)?;
    }
    shard_cache.open_slice(entry)
}
```

Package downloading is never permitted in untrusted/offline mode unless explicitly enabled. The first-fetch time is reported separately.

### 15.4 Repository hygiene

No engine binary, package shard, expanded installer, or generated format belongs in normal Git history. Git stores:

- source patches;
- build recipes;
- lock files;
- manifests;
- checksums;
- concise evidence summaries;
- schemas.

CI/release storage holds binaries and large evidence bundles.

## 16. Snapshot hierarchy

Use a hierarchy instead of one monolithic project snapshot.

| Level | State | Reuse scope |
|---|---|---|
| L0 | AOT compiled engine module | release/platform |
| L1 | engine + format loaded | engine/format/profile |
| L2 | package-prefix state | many projects with identical executed prefix |
| L3 | project begin-document state | one project/configuration |
| L4 | page/structural checkpoint | one project build lineage |
| L5 | action and output graph | content-addressed across safe projects |

### 16.1 L1 format snapshot

Captured after:

- runtime initialisation;
- Kpathsea setup;
- exact format load;
- format-specific one-time initialisation;
- no project source read.

### 16.2 L2 package-prefix snapshot DAG

Do not key snapshots on package names alone. Key them on the exact execution transcript up to a safe point.

```rust
struct PrefixEvent {
    kind: PrefixEventKind,
    identity: Digest,
}

enum PrefixEventKind {
    InputFile,
    EnvironmentRead,
    FontResolve,
    ConfigurationRead,
    SafeActionResult,
    EngineOption,
}
```

The prefix DAG shares common roots:

```text
latex format
  -> article.cls
      -> amsmath
          -> hyperref
      -> graphicx
  -> report.cls
```

A node is reusable only when all events and security policy match.

### 16.3 L3 project begin-document snapshot

The engine emits a pause after it has semantically completed begin-document initialisation and before consuming the first body token.

Snapshot host state includes:

- VFS handles and cursors;
- open-output transactional buffers;
- clock/random policy;
- action results;
- dependency manifest prefix;
- diagnostic buffer;
- output backend state;
- security capability set.

### 16.4 L4 page checkpoints

At safe shipout/structural boundaries:

```rust
struct EngineCheckpoint {
    id: CheckpointId,
    runtime_snapshot: SnapshotRef,
    source_cursor: SourceCursor,
    input_stack: Vec<InputCursor>,
    dependency_generation: Digest,
    semantic_state_digest: Digest,
    aux_state_digest: Digest,
    output_state_digest: Digest,
    shipped_page_ids: Vec<ObjectId>,
    safety: CheckpointSafety,
}
```

Checkpoint safety is explicit:

```rust
enum CheckpointSafety {
    Safe,
    Barrier(BarrierReason),
}

enum BarrierReason {
    ActiveExternalAction,
    NonReplayableShellEscape,
    OpenUncheckpointableHandle,
    BackendPendingGlobalRewrite,
    EngineReportedUnsafeState,
}
```

A replay starts at the nearest preceding `Safe` checkpoint.

## 17. Change journal and dependency planner

### 17.1 Project journal

A long-lived watcher maintains project generations.

```rust
struct ProjectJournal {
    generation: u64,
    last_event_sequence: u64,
    continuity: JournalContinuity,
    paths: HashMap<PathBuf, PathState>,
}

struct PathState {
    candidate_metadata: MetadataFingerprint,
    content_digest: Option<Digest>,
    last_changed_generation: u64,
}
```

On an invocation:

```rust
fn changed_paths(project: &ProjectState) -> Result<Vec<FileDelta>> {
    if project.journal.continuity != Continuous {
        return Err(NeedAudit);
    }

    let candidates = project.journal.paths_changed_since(project.last_build_generation);
    candidates
        .into_iter()
        .map(|path| hash_and_compare(path, project.last_manifest))
        .filter(|delta| delta.content_changed)
        .collect()
}
```

A background or scheduled audit verifies watcher correctness. Any watcher overflow forces exact execution and rebuilds the journal baseline.

### 17.2 Earliest affected checkpoint

Use actual read records.

```rust
fn earliest_affected(
    deltas: &[FileDelta],
    manifest: &BuildManifest,
    checkpoints: &[EngineCheckpoint],
) -> ReplayStart {
    let mut earliest = None;

    for delta in deltas {
        match manifest.reads.get(&delta.logical_path) {
            None => return ReplayStart::ExactFullBuild("new/unobserved path"),
            Some(read) => {
                if read.intervals.overlaps(&delta.changed_intervals) {
                    earliest = min_checkpoint(
                        earliest,
                        read.checkpoint_before_first_read
                    );
                }
            }
        }
    }

    match earliest {
        Some(id) => ReplayStart::Checkpoint(previous_safe(id, checkpoints)),
        None => ReplayStart::NoEngineWork,
    }
}
```

### 17.3 Replay and suffix convergence

```rust
fn incremental_build(
    project: &ProjectState,
    spec: &BuildSpec,
    deltas: &[FileDelta],
) -> Result<BuildResult> {
    let start = earliest_affected(
        deltas,
        &project.last_manifest,
        &project.checkpoints,
    );

    if start == ReplayStart::NoEngineWork {
        return publish_prior_result(project, spec);
    }

    let mut run = restore_for_replay(project, start, spec)?;
    apply_file_deltas(&mut run.host, deltas)?;

    loop {
        let outcome = run.runtime.run_until(
            &mut run.instance,
            StopCondition::NextCheckpointOrFinish,
            spec,
        )?;

        match outcome {
            RunOutcome::Checkpoint(new_cp) => {
                if let Some(old_cp) = project.matching_sequence(new_cp.sequence) {
                    if strongly_converged(&new_cp, old_cp)
                        && suffix_dependencies_unchanged(
                            old_cp,
                            deltas,
                            &project.last_manifest,
                        )
                    {
                        return assemble_replayed_prefix_and_old_suffix(
                            run,
                            project,
                            new_cp,
                            old_cp,
                            spec,
                        );
                    }
                }
                run.record(new_cp);
            }
            RunOutcome::Finished(finish) => {
                return finalize_full_replay(run, finish, spec);
            }
            RunOutcome::Unsafe(reason) => {
                return run_exact_with_reason(spec, reason);
            }
        }
    }
}
```

Strong convergence requires all of:

```text
engine semantic state digest
auxiliary state digest
dependency generation
input-stack state
output-backend state
security/action state
```

Visual page equality alone never proves convergence.

## 18. Incremental output architecture

### 18.1 Backend-neutral intermediate graph

Every engine/backend emits logical records:

```rust
struct DocumentGraph {
    pages: Vec<PageNode>,
    resources: BTreeMap<ObjectId, ResourceNode>,
    global: GlobalDocumentState,
}

struct PageNode {
    logical_id: PageLogicalId,
    content: BlobDigest,
    annotations: BlobDigest,
    destinations: BlobDigest,
    resources: Vec<ObjectId>,
    state_after_shipout: Digest,
}
```

### 18.2 pdfTeX/LuaTeX PDF path

Patch the output layer to allocate logical object identities independently of physical object numbers. Reused objects are renumbered during final assembly.

```rust
fn assemble_pdf(
    graph: &DocumentGraph,
    store: &ObjectStore,
    metadata: &PdfMetadata,
) -> Result<PdfBytes> {
    let closure = graph.transitive_object_closure();
    let numbering = deterministic_numbering(closure);
    let mut writer = PdfWriter::new(numbering);

    for object in closure {
        writer.write_object(
            numbering[object.id],
            store.materialize_and_rewrite_refs(object, &numbering)?,
        )?;
    }

    writer.write_catalog_pages_outlines_tags(graph, metadata)?;
    writer.write_xref_and_trailer()?;
    writer.finish()
}
```

### 18.3 XeTeX path

Capture XDV page records and resource usage before `xdvipdfmx`. Patch or wrap `xdvipdfmx` to convert only rebuilt pages and to emit deterministic logical resources.

Global features—outlines, tagging trees, font subsets, destinations—must be represented explicitly. Font reuse keys include:

```text
font file digest
face index
variation axes
encoding/features
used glyph set
backend version
```

### 18.4 DVI/PostScript/HTML

- DVI pages are naturally separable but font definitions and counters must be normalised.
- `dvips` uses page/resource manifests and deterministic prologue selection.
- tex4ht output uses a file/object graph, not a PDF graph.

### 18.5 Validation

Accelerated assembly is validated with:

- parser/structural checks;
- page count;
- extracted text;
- link/destination graph;
- font and image resource closure;
- tagging checks where applicable;
- sampled or mandatory raster comparison based on release mode;
- shadow exact build sampling.

## 19. Exact action broker

### 19.1 Action key

```rust
struct ActionKey {
    tool_identity: Digest,
    argv: Vec<OsString>,
    cwd_mapping: Digest,
    environment: BTreeMap<String, String>,
    locale: LocaleIdentity,
    clock_policy: ClockPolicy,
    stdin_digest: Option<Digest>,
    input_files: Vec<(LogicalPath, Digest)>,
    network_policy: NetworkPolicy,
    security_policy: SecurityPolicy,
}
```

The broker learns actual dependencies through sandbox observation. Caller-supplied input lists are hints only.

### 19.2 Execution

```rust
fn execute_action(req: ActionRequest) -> Result<ActionResult> {
    let provisional = provisional_key(&req)?;
    if let Some(record) = action_index.lookup(provisional) {
        if validate_record_inputs(&record)? {
            return restore_outputs(record);
        }
    }

    let sandbox = ActionSandbox::new(req.policy)?;
    let observed = sandbox.run_exact(req.tool, req.argv, req.env)?;
    let key = final_key(req, observed.reads, observed.effects)?;

    if observed.cacheable {
        action_store.commit(key, observed.outputs)?;
    }

    Ok(observed.into_result(key))
}
```

### 19.3 Preforked helpers

For deterministic helpers with large startup:

- start pristine parent;
- load runtime/modules;
- fork or clone per action;
- reset locale, env, cwd, file descriptors, signals, and random state.

The same `SnapshotRuntime` interface may host helper VMs.

---

# Part IV — Compatibility oracle programme

## 20. Oracle-only topology

```text
CI / qualification host
  +-- pinned BasicTeX oracle
  +-- tectdist exact lane
  +-- tectdist accelerated lane
  +-- comparator

production host
  +-- tectdist exact lane
  +-- tectdist accelerated lane
  -X- BasicTeX
```

BasicTeX paths are accepted only by scripts and crates built with `oracle-tools`.

## 21. Test generation

### 21.1 Engine-aware package probes

The current package probe system must stop loading every package under one default engine/context.

```python
def probe_matrix(package, tlpdb):
    kind = classify_package(package, tlpdb)
    engines = engines_required_by_files_and_metadata(package)
    deps = transitive_runtime_dependencies(package, tlpdb)

    if kind == "style_or_class":
        return generated_minimal_documents(package, engines, deps)
    if kind == "font_or_map":
        return generated_font_metric_and_glyph_tests(package, engines)
    if kind == "helper_binary":
        return generated_cli_and_pipeline_tests(package)
    if kind == "format":
        return generated_format_boot_tests(package)
    if kind == "data_file":
        return generated_lookup_tests(package)
    if kind == "collection_or_meta":
        return [closure_assertion(package)]
    return [expected_fail_assertion(package)]
```

### 21.2 Interactions

Generate pair, triad, and known high-risk interactions from:

- declared dependencies;
- packages that patch the same macro;
- output backend hooks;
- font/math systems;
- hyperref/tagging;
- shell escape;
- bibliography/index stages;
- engine-specific packages.

Use deterministic seeds and preserve minimised failures.

### 21.3 Real project corpus

The oracle corpus must include:

- small one-page documents;
- multi-file documents;
- 50-200 page books;
- references/TOC/outline cases;
- math-heavy;
- table/listings/microtype;
- font and multilingual cases;
- XeTeX and LuaHBTeX cases;
- DVI/dvips;
- MetaPost;
- tex4ht;
- shell escape cases within oracle scope.

### 21.4 Failure equivalence

A failure is equivalent only when:

- the same phase fails;
- diagnostic class matches;
- no candidate crash or hang occurs;
- no output is falsely reported as complete;
- side effects are no broader than the oracle.

## 22. Shadow mode

Production development builds can sample accelerated requests:

```rust
if shadow_policy.should_shadow(spec, project) {
    let accelerated = run_accelerated(spec)?;
    let exact = run_exact_in_background_test_context(spec)?;
    let comparison = compare_results(accelerated, exact);

    if !comparison.equivalent {
        quarantine_snapshot_lineage(project);
        report_minimised_reproducer(spec, comparison);
        publish_exact(exact);
    } else {
        publish_accelerated(accelerated);
    }
}
```

Public releases may use low-rate opt-in shadowing with privacy-safe local reports. CI uses mandatory shadowing.

---

# Part V — Performance engineering

## 23. Performance decomposition

Every timed compile reports:

```text
client_start
ipc
journal
route_plan
snapshot_clone
vfs
engine_replay
actions
backend_conversion
output_assembly
validation
publication
total
```

Named stage coverage must exceed 98%. The sum of exclusive spans may not exceed wall time by more than 2%.

## 24. X100 unchanged path

Replace whole-tree hashing with:

```rust
fn unchanged_fast_path(project: &ProjectState, spec: &BuildSpec) -> Option<Result> {
    if project.journal.continuity != Continuous {
        return None;
    }
    if project.journal.generation != project.last_build_generation {
        return None;
    }
    if project.last_spec_digest != digest(spec) {
        return None;
    }
    if !project.output_manifest.quick_integrity_check() {
        return None;
    }
    Some(project.last_result.clone())
}
```

The output manifest uses inode/file-id, size, and a stored digest. A periodic audit protects against missed external mutations.

## 25. Warm-clean acceleration

Warm-clean cannot use a project snapshot. It can use:

- L1 engine/format snapshot;
- L2 project-neutral package-prefix DAG;
- immutable package and font indexes;
- preforked exact helpers;
- output resource caches keyed only by immutable inputs.

Build the package-prefix DAG from observed workloads, not a hard-coded allowlist.

```rust
fn select_global_prefix(transcript: &[PrefixEvent], dag: &PrefixDag) -> SnapshotRef {
    dag.longest_verified_prefix(transcript)
}
```

A build can start at the deepest matching global prefix and execute the remaining project-specific preamble/body.

## 26. Profile-guided and engine-level optimisation

After snapshots remove stage repetition, optimise the remaining hot path:

- compile engines and runtime with representative PGO;
- consider BOLT/post-link optimisation for native host code;
- use thin LTO unless measured otherwise;
- reduce convergence hashing only after mutation tests;
- vectorise token/input scanning where profiles justify;
- memory-map immutable bundle/index data;
- precompute font indexes and maps;
- pool output buffers;
- avoid repeated Unicode normalisation and font metadata parsing;
- patch backend object generation for stable reuse.

No toolchain flag is credited until an end-to-end gate improves.

## 27. Memory and eviction

```rust
struct MemoryBudget {
    total_bytes: usize,
    l1_reserved: usize,
    l2_limit: usize,
    l3_limit: usize,
    l4_limit: usize,
}

fn evict_until_within_budget(pool: &mut SnapshotPool, budget: &MemoryBudget) {
    while pool.resident_bytes() > budget.total_bytes {
        let victim = pool.select_victim(|s| {
            score(
                s.last_used,
                s.clone_cost,
                s.rebuild_cost,
                s.bytes,
                s.scope,
                s.pin_count,
            )
        });
        pool.evict(victim);
    }
}
```

Priority:

1. retain L1 format snapshots;
2. retain high-hit L2 shared prefixes;
3. retain current project's L3;
4. evict old page checkpoints by expected saved work per byte.

---

# Part VI — Security, determinism, and failure handling

## 28. Security boundaries

- Supervisor socket is user-private.
- Runtime shards and snapshots are signed/digested.
- Project paths are canonicalised without escaping allowed roots.
- Output publication rejects symlink/path traversal.
- Engine instances run with resource limits.
- AOT/WASM instances have no ambient filesystem or network.
- Shell escape is mediated by explicit policy.
- Helper sandboxes record and restrict side effects.
- Snapshot data is untrusted on read and validated before restore.
- Cache poisoning triggers deletion and exact execution.

## 29. Determinism model

Each build records:

```rust
struct DeterminismContext {
    source_date_epoch: Option<i64>,
    wall_clock_policy: ClockPolicy,
    random_seed: SeedPolicy,
    locale: LocaleIdentity,
    timezone: TimezoneIdentity,
    environment_digest: Digest,
    host_font_policy: HostFontPolicy,
}
```

A snapshot may be reused only under the same context or under a proven equivalence transform.

## 30. Failure ladder

```text
accelerated checkpoint replay
  -> earlier checkpoint
  -> project begin-document snapshot
  -> package-prefix snapshot
  -> format-loaded snapshot
  -> tectdist exact one-shot
  -> return exact failure
```

Every escalation emits a machine-readable reason. No level invokes BasicTeX.

---

# Part VII — CI and release gates

## 31. CI layers

### Pull request

- workspace tests;
- oracle schema/ledger completeness;
- exact-lane smoke;
- accelerator differential subset;
- mutation fuzz subset;
- footprint diff;
- X100 unchanged microgate;
- no committed binary/generated-runtime gate.

### Nightly

- full package-row oracle tests;
- generated interactions;
- all engines and pipelines;
- exact vs oracle;
- accelerator vs exact;
- body/structural/unchanged performance;
- memory/leak/crash soak;
- snapshot restore fuzz;
- package shard integrity.

### Qualification

- clean signed build;
- three independent sessions per platform;
- frozen oracle and runtime manifests;
- required trial counts;
- full O100;
- X10/X100 scenario gates;
- footprint and RSS gates;
- SBOM, licences, signatures;
- raw evidence attached immutably.

## 32. Release matrix

Initial platforms:

```text
macOS arm64
macOS x86_64, while supported
Linux x86_64
Linux arm64
```

A platform is not listed as supported until exact lane, accelerated lane, oracle coverage, performance, and packaging gates all pass.

## 33. Claim rules

Allowed examples:

> 58x faster on unchanged rebuilds and 12x faster on local body edits across the published O100 edit corpus on macOS arm64.

> 10.7x lower warm-clean aggregate latency on the qualified BasicTeX-oracle package scope.

Not allowed:

- “100x faster LaTeX” based only on unchanged output;
- a clean-build claim using project snapshots;
- excluding fallback/exact-lane samples from the aggregate;
- calling reference-blocked package probes “unsupported” without reproducing the oracle result;
- implying BasicTeX is installed or used at runtime.

---

# Part VIII — Milestones and executable gates

## M0 — Roadmap reset and repository hygiene

**Goal:** remove ambiguity and stop prototype work from being mistaken for the product architecture.

Deliverables:

- this plan is canonical;
- old plans marked superseded;
- generated status derived from gate artefacts;
- committed engine binaries removed from future source history;
- BasicTeX runtime/fallback references catalogued;
- prototype fork server moved under `experiments/native-fork`;
- no root generated formats;
- architecture decision records for snapshot runtime and runtime pack.

Gate:

```text
all workspace tests green
no production dependency on BasicTeX paths
no newly committed executable/runtime blobs
```

## M1 — Oracle/runtime split

**Goal:** build and run without BasicTeX installed.

Deliverables:

- `OracleRunner` moved behind test-only feature/package;
- `RuntimePack` abstraction;
- `TECTDIST_RUNTIME_ROOT` replaces production BasicTeX root variables;
- exact-lane tools resolve from tectdist pack;
- CI job proves uninstalling/hiding BasicTeX does not affect candidate execution;
- exact lane compared to oracle.

Gate:

```text
candidate host contains no BasicTeX/MacTeX/TeX Live
all exact-lane core corpus cases pass
oracle host still reports zero mismatch
```

## M2 — Lightweight signed runtime pack

**Goal:** meet footprint gates with an independently assembled deployment.

Deliverables:

- `tectdist-pack` builder;
- package/file index;
- seekable signed shards;
- bootstrap installer;
- lazy fetch and offline complete pack;
- SBOM/licence report;
- release asset pipeline.

Gate:

```text
bootstrap <= declared budget
complete pack <= declared budget
all files have upstream provenance and digest
cold missing-shard failure is explicit
offline pack passes exact corpus
```

## M3 — SnapshotRuntime feasibility

**Goal:** make a go/no-go runtime decision using pdfTeX.

Deliverables:

- common `SnapshotRuntime` API;
- AOT WASM pdfTeX built from pinned source;
- host VFS imports;
- exact-lane differential;
- format-loaded capture/clone;
- performance and RSS evidence;
- ArenaRuntime design spike only if required.

Gate: all feasibility conditions in Section 13.3.

Decision output:

```text
ADOPT_WASM_AOT
ADOPT_ARENA
HYBRID_PDFTEX_NATIVE_OTHER_WASM
```

## M4 — pdfTeX X10-X100

**Goal:** pass unchanged, local-edit, and structural-edit gates for pdfTeX.

Deliverables:

- semantic begin-document hook;
- L1-L3 snapshots;
- project journal;
- actual dependency/read intervals;
- page checkpoints;
- PDF object graph;
- exact escalation;
- shadow verification.

Gate:

```text
X100-U pass
X10-L pass
X10-S pass
zero exact/accelerated mismatches
mutation/fuzz pass
```

## M5 — XeTeX and `xdvipdfmx`

**Goal:** equivalent snapshot/replay architecture without relying on unsafe native fork state.

Deliverables:

- XeTeX AOT/Arena engine;
- project/system font policy;
- font index and resolution parity;
- XDV page graph;
- incremental `xdvipdfmx`;
- Unicode/font corpus.

Gate: O100 XeTeX subset plus X10 edit scenarios.

## M6 — LuaHBTeX

**Goal:** support Lua callbacks and luaotfload under the same host model.

Deliverables:

- LuaHBTeX runtime;
- snapshot-safe Lua state;
- callback/action manifest;
- luaotfload/font cache identity;
- Lua corpus and mutation tests.

Gate: O100 Lua subset plus X10 edit scenarios.

## M7 — Helpers and all output pipelines

**Goal:** complete exact and accelerated pipeline coverage.

Deliverables:

- BibTeX, MakeIndex, MetaPost, MetaFont, dvips, tex4ht;
- action broker observation;
- safe prefork/cache paths;
- DVI/PS/HTML graph support.

Gate: every oracle pipeline and helper case has zero mismatch.

## M8 — O100 closure

**Goal:** eliminate untested and unclassified package rows.

Deliverables:

- generated package test class for every TLPDB row;
- engine-aware probes;
- pair/triad interactions;
- real projects;
- failure equivalence;
- visual and semantic validation.

Gate:

```text
372/372 classified (or exact current oracle row count)
0 untested
0 unexplained
0 mismatches
```

## M9 — X10 warm-clean

**Goal:** pass X10-W using project-neutral state only.

Deliverables:

- package-prefix snapshot DAG;
- workload-driven global snapshot selection;
- project-neutral action/resource reuse;
- clean-state verifier;
- warm-clean qualification corpus.

Gate: X10-W with no project-specific state present.

## M10 — Release qualification

All gates pass simultaneously on signed artefacts, and install/upgrade/uninstall paths are verified.

---

# Part IX — Ordered issue backlog

The agent should execute this sequence. Every item has an artefact and a gate; no item should be retried indefinitely without producing a reduced reproducer or an architecture decision.

## Architecture and hygiene

- **O100-001:** mark previous plans superseded and generate status from evidence.
- **O100-002:** inventory every production reference to BasicTeX paths and fallback execution.
- **O100-003:** add a CI static gate prohibiting production BasicTeX dependencies.
- **O100-004:** remove committed engine binaries and generated formats; publish artefacts through CI.
- **O100-005:** move native fork work to an experiment module and preserve benchmark tests.
- **O100-006:** split supervisor monolith into protocol, service, journal, scheduler, actions, runtime, and telemetry modules.

## Exact runtime and pack

- **PACK-001:** define `RuntimePackManifest` schema.
- **PACK-002:** build oracle-TLPDB-to-upstream-runfile resolver.
- **PACK-003:** implement deterministic shard builder.
- **PACK-004:** implement signed seekable shard reader.
- **PACK-005:** build minimal bootstrap and offline complete pack.
- **PACK-006:** create SBOM/licence/provenance output.
- **PACK-007:** build pinned exact native pdfTeX/XeTeX/LuaHBTeX tools in CI.
- **PACK-008:** route exact lane entirely through tectdist runtime.
- **PACK-009:** prove candidate operation with all system TeX installations hidden.

## Snapshot runtime

- **VM-001:** define `SnapshotRuntime`, `HostState`, `StopCondition`, and `Snapshot` APIs.
- **VM-002:** import/reproduce pinned TeX-to-WASM engine build as a clean patch series.
- **VM-003:** replace ambient WASI filesystem with tectdist VFS imports.
- **VM-004:** AOT compile pdfTeX and implement exact one-shot execution.
- **VM-005:** run full pdfTeX oracle differential.
- **VM-006:** implement custom page-backed linear memory.
- **VM-007:** implement format-loaded snapshot capture/clone.
- **VM-008:** run feasibility gates and write ADR.
- **VM-009:** implement ArenaRuntime spike if VM-008 does not adopt WASM.
- **VM-010:** delete or freeze non-selected runtime experiments.

## Journal and dependencies

- **JOURNAL-001:** implement cross-platform project watcher abstraction.
- **JOURNAL-002:** track event continuity and overflow.
- **JOURNAL-003:** add incremental content hashing and periodic full audit.
- **JOURNAL-004:** replace whole-tree unchanged gate.
- **VFS-001:** implement layered logical filesystem.
- **VFS-002:** embed exact Kpathsea lookup initially.
- **VFS-003:** record file opens, reads, seeks, and intervals.
- **VFS-004:** emit exact build manifest.
- **VFS-005:** map file changes to checkpoint read epochs.

## pdfTeX acceleration

- **PDF-001:** add semantic begin-document stop hook.
- **PDF-002:** capture L1 format snapshot.
- **PDF-003:** capture shared L2 prefix events and DAG.
- **PDF-004:** capture L3 project snapshot.
- **PDF-005:** add shipout checkpoint hook.
- **PDF-006:** define strong state digest and mutation tests.
- **PDF-007:** implement checkpoint replay.
- **PDF-008:** implement suffix convergence.
- **PDF-009:** expose logical PDF objects.
- **PDF-010:** implement deterministic PDF assembly.
- **PDF-011:** pass X100-U.
- **PDF-012:** pass X10-L.
- **PDF-013:** pass X10-S.

## XeTeX and LuaHBTeX

- **XE-001:** build exact AOT/Arena XeTeX.
- **XE-002:** implement font host interfaces and policy.
- **XE-003:** add XDV page/resource events.
- **XE-004:** make `xdvipdfmx` object-aware.
- **XE-005:** pass XeTeX O100 and X10 gates.
- **LUA-001:** build exact AOT/Arena LuaHBTeX.
- **LUA-002:** snapshot Lua VM and callbacks.
- **LUA-003:** integrate luaotfload index/cache identity.
- **LUA-004:** pass Lua O100 and X10 gates.

## Actions and outputs

- **ACT-001:** expand action key to observed environment and dependencies.
- **ACT-002:** sandbox and observe exact helper execution.
- **ACT-003:** implement preforked BibTeX/MakeIndex where beneficial.
- **ACT-004:** cover MetaPost/MetaFont/dvips/tex4ht.
- **ACT-005:** add arbitrary shell action barrier semantics.
- **OUT-001:** replace current model-only checkpoint/output records with runtime records.
- **OUT-002:** make page identities transitive over resources.
- **OUT-003:** validate output store against poisoning/corruption.
- **OUT-004:** implement DVI/PS/HTML assembly.

## Oracle and qualification

- **ORACLE-001:** classify every package row by test type.
- **ORACLE-002:** generate engine-aware probes.
- **ORACLE-003:** generate font/map/hyphenation/configuration tests.
- **ORACLE-004:** eliminate “untested.”
- **ORACLE-005:** expand deterministic interaction generation.
- **ORACLE-006:** run exact-vs-oracle.
- **ORACLE-007:** run accelerated-vs-exact.
- **ORACLE-008:** add shadow differential and reproducer minimisation.
- **PERF-001:** implement exclusive stage tracing.
- **PERF-002:** enforce footprint/RSS gates.
- **PERF-003:** qualify X100-U.
- **PERF-004:** qualify X10-L and X10-S.
- **PERF-005:** build and qualify package-prefix DAG for X10-W.
- **REL-001:** produce signed release evidence and claims.

---

# Part X — Agent execution protocol

## 34. One issue, one proof

Each implementation issue must state:

```text
Hypothesis
Changed layer
Correctness oracle
Performance denominator
Acceptance threshold
Kill/escalation condition
Expected artefacts
```

Example:

```text
Hypothesis:
  AOT linear-memory clone can replace pdfTeX's format load.

Correctness:
  zero mismatch over pdfTeX oracle corpus and mutation suite.

Performance:
  clone+entry p50 <= 1.0 ms; one-shot overhead <= 15%.

Kill condition:
  after a minimised profile shows unavoidable runtime overhead above gate,
  write ADR and start ArenaRuntime; do not continue unbounded tuning.
```

## 35. Experiments are not production

Experiments live under `experiments/` and are never automatically packaged. Promotion requires:

- reproducible build;
- no committed executable;
- full differential;
- security review;
- release-platform support;
- measured gain;
- maintenance owner.

## 36. Blocker lifecycle

When blocked:

1. create a minimal reproducer;
2. record exact revision, build command, and observed output;
3. identify the layer that owns the missing capability;
4. evaluate at least two architecture alternatives;
5. write a decision or open a bounded upstream task;
6. continue on an independent milestone.

Repeating the same failing build/debug loop without a new hypothesis is not progress.

## 37. Evidence discipline

Every performance commit records:

- candidate SHA and binary digest;
- runtime-pack digest;
- engine/module digest;
- oracle digest;
- machine/power state;
- raw paired samples;
- correctness pass;
- exclusive stage breakdown;
- footprint/RSS delta.

Projected gains are never summed into a product claim.

---

# Part XI — First continuation sequence

The next agent should execute these items in order.

1. **Commit the roadmap reset** — this document.
2. **Add an architecture test that production crates do not reference BasicTeX paths or variables.**
3. **Introduce `RuntimePack` and `ExactLane` traits without changing current behaviour.**
4. **Move BasicTeX execution behind a test-only `OracleRunner`.**
5. **Build the first tectdist-owned exact pdfTeX runtime from pinned source and oracle run files.**
6. **Switch one pdfTeX corpus case from BasicTeX execution to the exact internal lane; then switch the full pdfTeX subset.**
7. **Implement the deterministic compact runtime-pack builder and publish size evidence.**
8. **Define the `SnapshotRuntime` API and add a fake runtime exercising capture/restore invariants.**
9. **Build the pinned pdfTeX WASM/AOT feasibility module with host VFS.**
10. **Run and record the VM feasibility decision.**
11. **In parallel, replace the unchanged-rebuild full-tree hash with the project journal.**
12. **Begin semantic begin-document and shipout checkpoints only after the runtime decision.**

This sequence gives the agent productive work immediately, removes the BasicTeX runtime coupling, reduces deployment size, and prevents further dependence on the current XeTeX fork-resume blocker.

---

# Part XII — Risks and mitigations

| Risk | Consequence | Mitigation / decision gate |
|---|---|---|
| AOT WASM one-shot overhead is too high | warm-clean regression | 15% feasibility gate; use ArenaRuntime or hybrid |
| WASM engine differs from native TeX Live | O100 failure | pinned source, exact host imports, full oracle differential |
| XeTeX system-font semantics differ | user-visible output mismatch | explicit host-font policy and font identity in snapshots |
| Lua callbacks hold non-snapshot host state | unsafe replay | host-handle manifest, checkpoint barriers, exact escalation |
| Page suffix looks equal but state differs | stale later output | strong engine/aux/dependency/output state convergence |
| Output object reuse breaks references/tags | invalid PDF | transitive object identity, deterministic reassembly, parser+raster validation |
| Watcher misses a change | stale output | continuity tracking, periodic audit, exact build on overflow |
| Lazy package fetch harms offline/reproducible builds | failed compile | signed offline complete pack and explicit network policy |
| Package shards grow too large | lightweight goal missed | per-release size gate, access-based shard partitioning |
| Arbitrary shell escape is uncacheable | no X10 for some projects | exact execution and barrier; do not weaken compatibility |
| Engine patches become unmaintainable | upgrade deadlock | small stable hook ABI, upstream patches, generated patch tests |
| Snapshot RSS grows unbounded | poor desktop behaviour | cost-aware LRU, configurable hard caps, worker isolation |
| Oracle probes are invalid | false compatibility signal | engine-aware test generation and failure classification |
| Committed evidence bloats repository | slow clones | concise Git summaries; raw bundles on releases/CI storage |
| Runtime service crash | compile unavailable | short-lived client restarts supervisor; exact one-shot service fallback within tectdist |

---

# Part XIII — Definitions of done

## 38. Lightweight deployment done

- no BasicTeX, MacTeX, or system TeX dependency;
- bootstrap and complete-pack gates pass;
- no package/docs/source outside the oracle scope;
- no committed engine binaries;
- signed manifests, SBOM, and licences exist;
- lazy and offline installations both pass O100.

## 39. O100 done

- every oracle package row is classified and tested;
- zero untested rows;
- zero unexplained reference failures;
- zero candidate mismatches;
- every command, engine, format, helper, font/config family, and output pipeline in scope passes;
- exact lane runs on a TeX-free host;
- accelerated lane is shadow-equivalent to exact lane.

## 40. X100-U done

- unchanged p50/p95 gates pass on every supported platform;
- missed-event and output-tamper tests force execution;
- result is labelled unchanged rebuild;
- client-visible total includes validation.

## 41. X10 edit done

- local and structural edit gates pass independently;
- visible changes appear in output;
- cross-references converge;
- fallback/exact samples remain in the aggregate;
- mutation and shadow suites have zero stale output.

## 42. X10 warm-clean done

- no project-specific state exists before each sample;
- only allowed global state is warm;
- suite median and confidence interval pass;
- package-prefix snapshots are project-neutral and fully keyed;
- footprint/RSS gates pass simultaneously.

## 43. Release done

The same signed artefacts pass:

```text
O100
X100-U
X10-L
X10-S
X10-W, when claimed
footprint
memory
security
reproducibility
install / upgrade / uninstall
```

Only then may public documentation make the corresponding claims.

---

# Appendix A — Core pseudocode

## A.1 Compile router

```rust
fn compile(request: ClientRequest) -> Result<ClientResponse> {
    let spec = BuildSpec::from_request(request)?;
    let runtime = runtime_registry.resolve(&spec.profile)?;
    let project = project_registry.open(&spec.cwd)?;

    if let Some(hit) = unchanged_fast_path(&project, &spec) {
        return validate_and_respond(hit);
    }

    let deltas = project.journal.changed_since(project.last_build_generation)?;

    let route = accelerator.plan(&spec, &project, &deltas);
    let candidate = match route {
        AccelerationPlan::Replay(plan) => accelerator.replay(plan),
        AccelerationPlan::ProjectSnapshot(plan) => accelerator.from_project_snapshot(plan),
        AccelerationPlan::GlobalPrefix(plan) => accelerator.from_global_prefix(plan),
        AccelerationPlan::FormatSnapshot(plan) => accelerator.from_format(plan),
        AccelerationPlan::Ineligible(reason) => run_exact_with_reason(&spec, &runtime, reason),
    };

    match candidate {
        Ok(result) if validator.accepts(&spec, &result)? => {
            publisher.publish_atomic(&spec.output, &result.artifacts)?;
            project.commit_success(&spec, &result)?;
            Ok(ClientResponse::from(result))
        }
        Ok(result) => {
            quarantine(result.lineage);
            let exact = run_exact_with_reason(
                &spec,
                &runtime,
                "accelerated validation failed",
            )?;
            publisher.publish_atomic(&spec.output, &exact.artifacts)?;
            project.commit_success(&spec, &exact)?;
            Ok(ClientResponse::from(exact))
        }
        Err(error) => {
            let exact = run_exact_with_reason(&spec, &runtime, error.to_string())?;
            publisher.publish_atomic(&spec.output, &exact.artifacts)?;
            project.commit_success(&spec, &exact)?;
            Ok(ClientResponse::from(exact))
        }
    }
}
```

## A.2 Snapshot capture

```rust
fn capture_checkpoint(
    runtime: &dyn SnapshotRuntime,
    instance: &EngineInstance,
    host: &HostState,
    meta: EngineCheckpointMeta,
) -> Result<EngineCheckpoint> {
    ensure!(host.actions.all_quiescent());
    ensure!(host.outputs.snapshot_safe());
    ensure!(host.handles.all_snapshot_capable());

    let runtime_snapshot = runtime.capture(
        instance,
        host,
        SnapshotReason::Shipout(meta.sequence),
    )?;

    Ok(EngineCheckpoint {
        id: checkpoint_ids.next(),
        runtime_snapshot: snapshot_store.put(runtime_snapshot)?,
        source_cursor: host.inputs.current_source_cursor(),
        input_stack: host.inputs.snapshot_stack(),
        dependency_generation: host.vfs.dependency_generation(),
        semantic_state_digest: meta.semantic_state_digest,
        aux_state_digest: host.aux.digest(),
        output_state_digest: host.outputs.digest(),
        shipped_page_ids: host.outputs.shipped_pages(),
        safety: CheckpointSafety::Safe,
    })
}
```

## A.3 Strong convergence

```rust
fn strongly_converged(new: &EngineCheckpoint, old: &EngineCheckpoint) -> bool {
    new.sequence == old.sequence
        && new.semantic_state_digest == old.semantic_state_digest
        && new.aux_state_digest == old.aux_state_digest
        && new.dependency_generation == old.dependency_generation
        && new.output_state_digest == old.output_state_digest
        && new.input_stack == old.input_stack
}
```

## A.4 Oracle comparator

```python
def compare_case(case, oracle_runner, candidate_runner):
    oracle = oracle_runner.run(case)
    exact = candidate_runner.run_exact(case)
    accel = candidate_runner.run_accelerated(case)

    exact_cmp = compare_observations(oracle, exact, case.equivalence)
    accel_cmp = compare_observations(exact, accel, case.equivalence)

    return {
        "case": case.id,
        "oracle_vs_exact": exact_cmp,
        "exact_vs_accelerated": accel_cmp,
        "pass": exact_cmp.pass_ and accel_cmp.pass_,
        "routes": {
            "exact": exact.route,
            "accelerated": accel.route,
        },
    }
```

## A.5 Package shard lookup

```rust
fn open_package_file(path: &TeXPath, runtime: &RuntimePack) -> Result<VfsFile> {
    let record = runtime.index.lookup(path)?;
    let shard = runtime.shards.ensure_local(record.shard_id)?;
    let bytes = shard.read_verified(record.offset, record.length, record.digest)?;
    Ok(VfsFile::immutable(path.clone(), bytes))
}
```

## A.6 Action caching

```rust
fn run_or_restore_action(req: ActionRequest) -> Result<ActionResult> {
    let tool = exact_tools.resolve(req.tool)?;
    let provisional = ActionKey::provisional(tool.digest(), &req);

    if let Some(record) = action_store.lookup(provisional) {
        if record.inputs.iter().all(input_still_matches)
            && record.policy == req.policy
        {
            return action_store.restore(record);
        }
    }

    let observed = action_sandbox.run(tool, req)?;
    let final_key = ActionKey::from_observation(&observed);

    if observed.cacheability == Cacheable {
        action_store.commit(final_key, &observed)?;
    }

    Ok(observed.result)
}
```

---

# Appendix B — Architecture decision templates

## B.1 Snapshot runtime ADR

```text
Decision:
  WASM_AOT | ARENA | HYBRID

Correctness evidence:
  ...

One-shot overhead:
  ...

Snapshot clone latency:
  ...

Memory:
  ...

Toolchain/reproducibility:
  ...

Security:
  ...

Rejected alternatives:
  ...

Maintenance owner:
  ...
```

## B.2 Acceleration feature promotion

```text
Feature:
  page checkpoint / prefix snapshot / output reuse / helper reuse

Exact lane comparator:
  ...

Eligible population:
  ...

Ineligibility behaviour:
  tectdist exact lane

Mutation coverage:
  ...

Performance gain:
  ...

Rollback switch:
  ...

Release gate:
  ...
```
