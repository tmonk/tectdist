# tectdist X10: Order-of-Magnitude LaTeX Performance Plan

**Status:** Proposed after audit of the `perf` branch  
**Audit basis:** `tmonk/tectdist` `perf`, inspected 24 August 2026  
**Audited branch head:** `20b98feb7c970467bcdd4bb3192860e44c9df556`  
**Current measured baseline:** 3.497 s aggregate warm-clean time versus 4.100 s for TeX Live 2026 `latexmk` on the seven-project compact corpus  
**Primary objective:** make `tectdist` the fastest measured route from supported LaTeX source to a correct, fully resolved PDF  
**Stretch objective:** deliver an order-of-magnitude latency reduction in explicitly defined workloads  
**Phase D status:** remains parked by default; any resident service, cross-invocation cache, or incremental compiler requires the explicit X10-D decision gate in this plan

---

## 1. Executive conclusion

The `perf` branch has successfully removed the old wrapper bottleneck. It has a native Rust dispatcher, an embedded Tectonic executor, direct in-process `latexmk` compatibility, generated-artifact index detection, differential tests, a paired benchmark runner, and performance workflows.

The remaining problem is no longer primarily `tectdist` startup. The measured work is now dominated by:

1. Tectonic/XeTeX processing and PDF generation.
2. Bibliography processing, especially external Biber.
3. A wasteful index/glossary pipeline that completes one embedded build, runs an indexer, and starts a second embedded build.
4. Repeated configuration, bundle, format-cache, and session construction.
5. A single-backend strategy that uses Tectonic's XeTeX-derived engine even for workloads where pdfTeX is faster.
6. Engine-level I/O, hashing, file lookup, font, and XDV-to-PDF costs.

The current aggregate is 3.497 seconds. A literal 10x target is therefore no more than 350 milliseconds for all seven claim documents combined. The one-page `biblatex` case alone is currently 1.996 seconds. The tiny document is 167 milliseconds, so a 10x tiny target is below 17 milliseconds. The ITP3 QFT stress document is 41.548 seconds, so a 10x clean-build target is approximately 4.15 seconds.

Those targets cannot be reached by further CLI parsing, LTO, allocation tuning, or small Rust refactors. They require removal or reuse of entire stages:

- Avoid external Biber on the common path.
- Avoid repeated TeX and PDF passes.
- Select a faster engine backend for documents that do not need XeTeX.
- Reuse initialized format, preamble, dependency, and output state for repeated builds.
- Upstream or maintain deep engine changes in Tectonic/XeTeX and `xdvipdfmx`.
- For universal 10x clean builds, pursue a new engine execution model rather than a wrapper optimisation programme.

The programme therefore has three performance lanes:

| Lane | Product mode | Phase D dependency | Credible target |
|---|---|---:|---|
| **A. Fastest one-shot compiler** | Fresh process, no tectdist-managed project cache | No | Lowest clean-build aggregate; approximately 2x is the first hard gate, 3x is a stretch target |
| **B. Fastest backend portfolio** | Select the fastest correct engine for each requested semantic mode | No | Win tiny, index, Unicode, bibliography, and large-document classes rather than accepting backend-specific losses |
| **C. X10 repeated-build mode** | Initialized engine state, preamble snapshots, dependency graph, and verified reuse | Yes, explicit X10-D approval | 10x or better on unchanged, small-edit, and many structural-edit workflows |

A 10x claim must always name the workload. The plan must never turn an unchanged-output cache hit into an undisclosed “clean compile” result.

---

## 2. Definition of success

### 2.1 Product claim

The defensible final position is:

> **tectdist is the fastest measured end-to-end LaTeX compiler for correct, fully resolved PDFs across its published corpus and supported platforms.**

A stronger claim such as “10x faster” may be published only for scenario cells that individually satisfy that ratio with confidence intervals and complete correctness.

The project must not claim to be universally fastest for every TeX dialect, document, engine semantic, cache state, operating system, or machine.

### 2.2 A complete result

A timed result counts only when all applicable checks pass:

- Exit status is zero.
- A non-empty, parseable PDF exists.
- `qpdf --check` or an equivalent structural check passes.
- Expected pages and semantic text are present.
- Cross-references, citations, table of contents, and PDF outlines have converged.
- Required BibTeX, Biber, index, and glossary stages have completed.
- No actionable rerun warning remains.
- No unsupported stage has been silently skipped.
- Output directory, job name, SyncTeX, shell-escape, and compatibility semantics are correct.
- A cached or resumed result is invalidated whenever any relevant input changes.

### 2.3 Required benchmark scenarios

The benchmark report must keep these populations separate:

| Scenario | Required state |
|---|---|
| `cold-empty-cache` | Empty bundle and format cache, controlled package source |
| `warm-clean` | Warm compiler/package cache, no project output or project-specific snapshot |
| `warm-existing-output` | Existing ordinary TeX intermediates retained |
| `unchanged-rebuild` | Same project and inputs, all prior state retained |
| `source-comment-edit` | Source bytes change without changing PDF semantics |
| `source-visible-edit` | A visible local text or equation edit |
| `source-structural-edit` | A section/reference/citation change |
| `bibliography-edit` | `.bib`, citation set, sorting, or style changes |
| `index-edit` | Indexed terms change |
| `batch` | Multiple independent projects compiled with declared concurrency |
| `large-clean` | Real book, thesis, TikZ, or equation-heavy clean builds |

The current `source-small-edit` operation appends a comment to a newly copied project. That tests a clean build of modified bytes, not incremental compilation. It must be renamed or redesigned.

---

## 3. Baseline and 10x performance budget

### 3.1 Current warm-clean medians

| Document | Current Rust median | 10x budget | Current outcome versus TeX Live |
|---|---:|---:|---|
| `tiny` | 166.858 ms | 16.7 ms | Loses by 36.7 ms |
| `references` | 173.877 ms | 17.4 ms | Wins by 21.0 ms |
| `paper` | 351.175 ms | 35.1 ms | Wins by 133.0 ms |
| `bibtex` | 218.427 ms | 21.8 ms | Wins by 165.9 ms |
| `biblatex` | 1996.432 ms | 199.6 ms | Wins by 335.4 ms, but dominates total time |
| `index` | 340.426 ms | 34.0 ms | Loses by 74.6 ms |
| `thesis` | 249.949 ms | 25.0 ms | Wins by 32.8 ms |
| **Aggregate** | **3497.144 ms** | **349.7 ms** | **14.71% aggregate win** |

### 3.2 Consequences of the budget

A 10x aggregate result requires all of the following, not merely one of them:

- Biber and the surrounding TeX reruns must fall from roughly two seconds to approximately 100–200 milliseconds, or be safely bypassed through reuse.
- Tiny startup plus a complete one-page typeset and PDF write must fall below approximately 17 milliseconds.
- Index generation must stop paying for two full embedded build sessions and two PDF-producing pipelines.
- Large clean documents must spend dramatically less time in the TeX/XeTeX and XDV-to-PDF engines.
- The product must choose pdfTeX or another faster backend when XeTeX semantics are not required.

The first one-shot milestone should target **2x aggregate improvement**, with an aspirational **3x**. The 10x objective is retained as a research and repeated-build goal until evidence demonstrates that it is achievable for strict clean builds.

### 3.3 Gain ledger

Every optimisation issue must maintain a non-overlapping gain ledger:

| Work item | Baseline stage time | Proposed mechanism | Expected affected workloads | Measured result | Confidence |
|---|---:|---|---|---:|---|
| Example: index pipeline | To be measured | One session, one final PDF conversion | index, glossary | Pending | Pending |

Projected gains must not be added together when they target the same time. The release report must use measured end-to-end results, never a sum of optimistic microbenchmark estimates.

---

## 4. Audit findings on the current `perf` branch

## 4.1 Measurement issues that must be fixed first

### 4.1.1 Timed runs enable asymmetric tracing

The benchmark runner sets `TECTDIST_TRACE_FILE` for every timed process. The native candidate honours it; TeX Live does not. The candidate's `trace_span()` implementation obtains wall-clock timestamps, opens the trace file, appends one JSON line, and closes it for each span. The embedded path emits several spans per compile.

This means the current wall time includes candidate-only filesystem instrumentation. It is not a production-path measurement and can materially distort the tiny result.

**Required correction:**

1. Run the timed trial with tracing disabled.
2. Run one separate untimed diagnostic repetition with tracing enabled.
3. Alternatively, buffer all spans in memory and perform one write after the measured engine interval, while still publishing both traced and untraced process totals.
4. Never infer a product regression from a traced microbenchmark.

### 4.1.2 Performance CI benchmarks the Python implementation

The PR and nightly workflows run `python make_links.py` and benchmark `./bin/pdflatex`. They do not build `target/release/tectdist` and therefore do not protect the native implementation reported in `BENCHMARKS.md`.

**Required correction:**

```sh
cargo build --release --locked
python make_links.py --target "$PWD/target/release/tectdist"   # add this capability
```

Every performance job must record and benchmark the exact release binary SHA-256.

### 4.1.3 The nightly job is not qualification

The nightly workflow is named qualification but does not invoke `--qualification`, does not require the TeX Live independent competitor, and does not enforce the bundle/format provenance fields that qualification mode requires.

**Required correction:** create separate jobs named `smoke`, `regression`, and `qualification`; only the latter may update public benchmark evidence.

### 4.1.4 Resource measurements contaminate or misrepresent samples

The runner should be reviewed for:

- Cache-tree walks inside the wall-clock interval.
- `RUSAGE_CHILDREN` peak RSS, which is a cumulative maximum rather than a clean per-child delta.
- Process counts inferred from candidate-specific trace spans.
- Engine-pass counts that report one embedded session even when Tectonic internally performs multiple TeX/BibTeX/PDF stages.

Use `wait4`, per-process sampling, platform-native counters, or an external supervisor. The wall-clock timer must cover only process launch through process completion.

### 4.1.5 The claim corpus is too small and synthetic

The claim corpus's “thesis” is three pages and the representative paper is one page. These are useful correctness fixtures, but they do not ensure leadership on real theses, journal templates, books, TikZ-heavy works, image-heavy works, or large bibliographies.

The ITP3 QFT fixture is valuable, but its published result is one pair and therefore exploratory.

---

## 4.2 Runtime bottlenecks in the current implementation

### 4.2.1 Configuration and bundle setup are repeated every invocation

`EmbeddedTectonicExecutor::execute()` currently performs these operations for every compile:

1. Create output directory.
2. `PersistentConfig::open(false)`.
3. `default_bundle(false)`.
4. `format_cache_path()`.
5. Construct a new `ProcessingSessionBuilder`.
6. Create a new processing session.
7. Run the complete driver.

Some of these costs may be small, but they must be measured separately and removed from repeated stages within the same process.

### 4.2.2 Index and glossary builds create a second complete session

The first embedded session produces `.idx` or `.glo` and a PDF. `tectdist` then runs an external indexer and invokes the embedded executor again. The second invocation reopens configuration and bundle state and runs another complete pipeline. This explains why the index case loses to TeX Live.

The correct architecture is one orchestrated processing pipeline with the index/glossary callback between TeX passes and one final PDF conversion.

### 4.2.3 Biber dominates the aggregate

The `biblatex` result is approximately 57% of the seven-document aggregate. The embedded engine still depends on external Biber semantics. Biber is a sophisticated Perl application with XML/Unicode/collation and style processing. An external Biber process plus repeated TeX work cannot fit within the X10 aggregate budget.

Biber must therefore have three paths:

1. A native fast path for a rigorously defined common subset.
2. A safe external fallback for full compatibility.
3. If X10-D is approved, a persistent or content-addressed reuse path for repeated builds.

### 4.2.4 Engine-stage observability is incomplete

The executor currently reports an `engine.pass` event around `session.run()`. Tectonic's processing session may internally run TeX repeatedly, run BibTeX, invoke Biber, and run the XDV-to-PDF stage. Those stages need distinct events and counters.

No engine optimisation should start until the branch can answer, per document:

- Time loading the format.
- Time reading bundle resources.
- Time in each TeX pass.
- Time in BibTeX or Biber.
- Time in index/glossary processing.
- Time in `xdvipdfmx`/PDF generation.
- Time in font lookup, shaping, and subsetting.
- Time hashing files and comparing rerun inputs.
- Time flushing each output artifact.

### 4.2.5 The single XeTeX-derived backend cannot win every workload

The tiny and index competitors use TeX Live pdfTeX. `tectdist` uses Tectonic's XeTeX-derived engine for traditional engine aliases. That is an architectural disadvantage on some simple documents and a semantic mismatch for documents that genuinely depend on pdfTeX or LuaTeX behaviour.

To be the fastest LaTeX compiler rather than merely the fastest Tectonic wrapper, `tectdist` needs a backend portfolio.

### 4.2.6 Tectonic has known performance-regression signals

Upstream users have reported that older Tectonic releases such as 0.8.2 were materially faster than later releases in some documents. Upstream discussion points to changes in XeTeX/`xdvipdfmx` and avoidable file-size I/O as investigation areas. Older profiling also reported significant digest/hash overhead.

The branch must not assume that the current pinned engine is the fastest correct Tectonic revision. A controlled version and commit bisect is mandatory.

---

## 5. Target architecture

## 5.1 One-shot architecture, active

```text
argv[0]
  -> zero-allocation command classification
  -> typed CompilationPlan
  -> backend selector
       -> embedded pdfTeX backend
       -> embedded Tectonic/XeTeX backend
       -> embedded LuaHBTeX backend, later
       -> external compatibility fallback
  -> integrated stage scheduler
       TeX pass
       optional bibliography/index callback
       convergence check
       one final PDF conversion
  -> artifact writer
  -> correctness/status result
```

Properties:

- One native process for the default path.
- One configuration and resource context per invocation.
- No duplicate final PDF conversion.
- No external tool where an audited in-process implementation exists.
- Exact requested engine semantics preserved for explicit aliases.
- Generic `tectdist` command may choose the fastest proven-compatible backend.
- External fallback remains automatic and visible when a native fast path cannot prove support.

## 5.2 X10 stateful architecture, parked pending X10-D approval

```text
short-lived CLI
  -> authenticated local socket
  -> isolated compiler worker
       initialized engine and format
       immutable bundle index
       project dependency graph
       optional preamble/engine snapshot
       content-addressed bibliography/index state
       page/output checkpoints
  -> validated result or one-shot fallback
```

This is not part of the active one-shot milestones. It may start only after the X10-D gate in Section 15.

---

## 6. Workstream X0: repair the benchmark and regression system

**Priority:** immediate  
**Reason:** every later decision depends on trustworthy measurements

### X0.1 Separate timed and diagnostic executions

For every sample pair:

1. Prepare isolated projects.
2. Execute an untraced timed build.
3. Validate the output.
4. Execute an untimed traced build on a separate identical project when stage data is needed.
5. Store both records with explicit `measurement_class`.

Acceptance:

- Candidate and competitor timed paths receive equivalent environment overhead.
- No trace file is opened by the candidate in the timed path.
- Repeated untraced tiny results are stable within an established noise envelope.

### X0.2 Replace inferred resource metrics

Implement a small native benchmark supervisor under `crates/tectdist-bench`:

- `posix_spawn` or `Command` launch.
- `wait4` resource collection on Unix.
- Per-process user/system CPU.
- Per-process peak RSS where the platform supports it.
- Child process tree observation through platform APIs or explicit executor events.
- Wall clock around child execution only.
- Optional `procfs`, `dtrace`, Instruments, or `perf` adapters outside qualification timing.

### X0.3 Build the real candidate in CI

PR smoke:

```sh
cargo build --release --locked
python -m benchmarks.runner.cli \
  --candidate ./target/release/tectdist \
  --document tiny --document index --document biblatex \
  --scenario warm-clean --trials 5 --warmups 2
```

Nightly regression:

- Native candidate.
- Previous accepted native baseline.
- Direct Tectonic control.
- TeX Live `latexmk` independent control.
- Full compact corpus plus at least three real documents.

Release qualification:

- `--qualification` enabled.
- Clean tagged revision.
- Explicit bundle and format identities.
- Three independent sessions per supported platform.
- Raw samples retained immutably.

### X0.4 Balance pair order

Use exact AB/BA stratification rather than unconstrained random order. At 30 pairs, each tool runs first 15 times. Randomise the sequence of those balanced pairs and record the seed.

### X0.5 Add baseline gates

A PR fails when:

- Any correctness oracle fails.
- Aggregate p50 regresses by more than the greater of 3% or the platform noise floor.
- p95 regresses by more than 5% with statistical support.
- A stage count increases unexpectedly.
- A claimed fast path falls back to an external tool unexpectedly.

---

## 7. Workstream X1: full engine observability

**Priority:** immediate after X0

### X1.1 Add an upstreamable driver observer

Introduce an observer interface around Tectonic's processing driver:

```rust
trait ProcessingObserver {
    fn stage_start(&mut self, stage: Stage, metadata: &StageMetadata);
    fn stage_end(&mut self, stage: Stage, result: &StageResult);
    fn file_event(&mut self, event: FileEvent);
    fn external_command(&mut self, command: &CommandEvent);
}
```

Required stages:

- Persistent configuration open.
- Bundle index open.
- Format cache lookup.
- Format load/generation.
- Each TeX pass.
- BibTeX.
- Biber.
- Index/glossary.
- XDV-to-PDF conversion.
- Font discovery.
- Font load/subset/embed.
- Image decode/embed.
- Output flush.
- Dependency digesting.

### X1.2 Use a memory trace sink

When tracing is enabled:

- Allocate one bounded event buffer.
- Record monotonic timestamps only.
- Write one trace payload at process completion.
- Include a dropped-event count if the buffer fills.
- Compile all tracing branches out of a `max-performance` profile for qualification comparisons.

### X1.3 Produce per-document flamegraphs

Mandatory profiles:

- `tiny`.
- `index`.
- `biblatex`.
- Representative paper.
- Real thesis/book.
- ITP3 QFT.

Use macOS Instruments and Linux `perf`. Store symbols, build IDs, folded stacks, and flamegraphs with benchmark artifacts.

### X1.4 Establish stage budgets

No optimisation issue may enter implementation without a profile showing that its target consumes at least one of:

- 5% of aggregate corpus time.
- 10% of a claim-relevant workload.
- A fixed 5 ms on the tiny path.

Exceptions require an explicit correctness or architecture justification.

---

## 8. Workstream X2: immediate one-shot fast-path corrections

These are low-risk improvements that should land before deeper engine work.

### X2.1 Remove duplicate setup

- Create the output directory once.
- Resolve configuration, bundle, and format-cache path once per process.
- Pass an `EngineContext` into all stages.
- Reuse the same context for index/glossary continuation.
- Avoid canonicalisation and environment lookup after plan construction.

Proposed model:

```rust
struct EngineContext {
    config: PersistentConfig,
    bundle: Box<dyn Bundle>,
    format_cache: PathBuf,
    observer: ObserverHandle,
}
```

If upstream types prevent safe reuse, add a tectdist-owned wrapper or upstream the minimum API change.

### X2.2 Make output retention intentional

The current executor always enables `keep_logs(true)` and `keep_intermediates(true)`.

Measure and define three policies:

- `compat`: emit traditional expected artifacts.
- `minimal`: PDF plus requested SyncTeX/log outputs.
- `internal`: retain intermediates in memory until the final successful result.

The default must preserve documented compatibility, but intermediate data need not be written, reread, and hashed more than required.

### X2.3 Avoid repeated artifact probing

Replace fixed post-run `is_file()` checks with actual output events from the Tectonic memory/filesystem layer. The executor should receive the generated artifact set directly.

### X2.4 Remove polling from external tool waits

Replace the 5 ms `try_wait` sleep loop with a blocking wait plus an OS timeout mechanism, a watchdog thread, or platform process timer. This removes quantisation and unnecessary wakeups from short index tools.

### X2.5 Remove hot-path status formatting

- Do not construct normal diagnostic strings in quiet mode.
- Do not print the `latexmk: Running` compatibility line in `-silent` mode.
- Avoid terminal detection and colour setup when stdout/stderr are not terminals.
- Store static command tables as perfect matches or generated enums rather than repeated string scans where profiles justify it.

### X2.6 Add a true maximum-performance build

```toml
[profile.max-performance]
inherits = "release"
lto = "fat"
codegen-units = 1
panic = "abort"
strip = "symbols"
debug = 1
incremental = false
```

The debug line table is retained in a separate symbol artifact if stripping is necessary for release. Compare ThinLTO and fat LTO rather than assuming one is faster.

Acceptance for X2:

- No behavioural difference in the differential battery.
- Tiny untraced median improves.
- Index setup overhead is reduced even before the integrated index scheduler lands.
- No stage is duplicated solely because `tectdist` reconstructs the executor.

---

## 9. Workstream X3: Tectonic version matrix and regression archaeology

**Priority:** high  
**Reason:** the fastest correct engine revision may not be the currently pinned one

### X3.1 Build a reproducible engine matrix

Test, with the same compiler and dependencies where possible:

- Current `tectdist` pinned Tectonic 0.17.0 tag.
- Latest upstream main commit approved by correctness tests.
- Current released component set.
- Tectonic 0.16.x and 0.15.x.
- Historical 0.12.x, 0.9.x, 0.8.2, and 0.7.1 where they can be adapted to a controlled current bundle.
- Intermediate commits around any discovered performance discontinuity.

Separate:

- Engine code.
- XeTeX reference-source changes.
- `xdvipdfmx` changes.
- Bundle implementation.
- Rust dependency/toolchain changes.

### X3.2 Use the current bundle with historical engines

Old public package endpoints must not invalidate the experiment. Create a compatibility adapter or local immutable bundle mirror so the engine comparison changes only the engine revision.

### X3.3 Automate performance bisecting

Create `scripts/bisect_tectonic_perf.py` that:

1. Builds a selected Tectonic commit with a pinned toolchain.
2. Runs tiny, paper, QFT, and one font-heavy case.
3. Applies correctness gates.
4. Classifies the commit as good, bad, or unbuildable.
5. Emits stage and flamegraph comparisons at the boundary.

### X3.4 Evaluate current bundle improvements

Upstream `tectonic_bundles` 0.4.2 introduced concurrent first-build prefetch and less frequent remote rechecking. Test it explicitly for `cold-empty-cache`; do not assume the monolithic Tectonic tag includes or benefits from every component-level improvement.

### X3.5 Pin by evidence

The release may temporarily pin an exact upstream commit or reviewed patch stack when:

- It passes the full correctness corpus.
- It materially improves the claim corpus.
- Security and bundle compatibility are documented.
- An upstream PR exists or a maintenance owner is named.

---

## 10. Workstream X4: Tectonic I/O, digest, and rerun engine

**Priority:** high after profiling

Tectonic records file access patterns and content digests to decide whether reruns are required. This is valuable for correctness, but historical profiles and upstream reports suggest that hashing and file-size I/O can consume substantial time.

### X4.1 Split integrity hashes from convergence hashes

Package and bundle integrity may require cryptographic verification. In-session rerun equality does not necessarily require SHA-2.

Design:

- Keep strong published integrity hashes for downloaded artifacts.
- Use BLAKE3, XXH3-128, or direct byte equality for in-session circular-file comparison, selected after collision and correctness review.
- Include length in every equality record.
- Fall back to byte comparison on matching short digests for small `.aux`, `.toc`, `.out`, and `.bcf` files if required.

### X4.2 Hash only files that affect convergence

Do not compute or retain change digests for immutable package inputs merely because they were read. Classify:

- Immutable bundle resources.
- Primary and transitive source inputs.
- Circular rerun files.
- Temporary files.
- Final outputs.

Only circular and stage-dependency files need repeated equality checks within a single build.

### X4.3 Eliminate redundant file opens and metadata calls

- Fix `getfilesize` paths that open and close a file only to obtain metadata.
- Cache metadata for files already open in the I/O layer.
- Batch canonicalisation and stat operations.
- Intern path identities.
- Avoid repeatedly resolving the same bundle member.

### X4.4 Reduce bridge overhead

Profile Rust/C bridge calls. Where hot:

- Read larger blocks.
- Cache input handles.
- Avoid UTF-8/path conversion on each callback.
- Replace string-keyed event maps with interned IDs and compact records.
- Pre-size common maps from previous corpus observations without embedding document-specific assumptions.

### X4.5 Memory-map immutable data

Benchmark memory mapping for:

- Format files.
- Bundle indexes.
- Large package resources.
- Fonts.
- Reused images.

Do not map tiny files indiscriminately; use thresholds derived from profiles.

Acceptance:

- Identical rerun decisions across a mutation corpus.
- No stale output under adversarial same-size/same-mtime changes.
- At least one profile-proven reduction in engine CPU or system calls.

---

## 11. Workstream X5: integrated index and glossary pipeline

**Priority:** immediate after X1  
**Goal:** turn the current index loss into a clear win

### X5.1 Add stage interception inside the processing session

The driver needs a callback after a TeX pass has produced `.idx`/`.glo` and before final convergence/PDF emission.

Desired flow:

```text
load context once
run TeX pass
if .idx changed:
    run index stage
if .glo changed:
    run glossary stage
continue TeX convergence
run XDV-to-PDF exactly once
write final artifacts
```

### X5.2 Prevent duplicate PDF generation

The first index-discovery pass must stop at an intermediate output or defer `xdvipdfmx`. It must not produce a final PDF that will immediately be discarded.

### X5.3 Port MakeIndex to an in-process library

Options, in order:

1. Expose the already pinned MakeIndex C source through a narrow library API.
2. Port the core algorithm to safe Rust with differential tests against MakeIndex 2.12.
3. Retain the external binary only as a fallback for unsupported options/styles.

Required compatibility fixtures:

- Basic sorting.
- Ranges.
- Encapsulation.
- Custom `.ist` styles.
- Unicode/upmendex fallback.
- Glossaries-generated styles.

### X5.4 Keep intermediate files in memory

Pass `.idx` to the index stage and `.ind` back to the TeX I/O layer without disk round trips when compatibility does not require those files to be externally visible before completion. Emit final compatibility artifacts once.

Acceptance:

- One Tectonic configuration context.
- One final PDF conversion.
- No polling delay.
- Index corpus median beats TeX Live with confidence.
- Full external MakeIndex differential suite passes.

---

## 12. Workstream X6: bibliography acceleration

**Priority:** highest aggregate opportunity

## 12.1 Decompose the current `biblatex` path

Instrument:

- First TeX pass and `.bcf` production.
- Biber process startup.
- BCF XML parse.
- `.bib` parse.
- Unicode normalisation and collation.
- Data model validation.
- Sorting, label/name calculation.
- `.bbl` generation and write.
- Subsequent TeX passes.
- Final PDF conversion.

The plan must not assume that Biber startup is the entire two-second cost.

## 12.2 One-shot native Biber fast path

Create `tectdist-bib` as a separately testable crate. It should implement a deliberately bounded subset first:

- BCF parsing for common biblatex versions.
- BibTeX data parsing.
- Common entry types and fields.
- Standard sorting templates.
- Unicode normalisation.
- Common name/label generation.
- Standard locale handling.
- `.bbl` emission byte-compatible or semantically compatible with Biber for supported fixtures.

Use differential testing against the declared Biber version over thousands of generated and real bibliography fixtures.

Fast-path contract:

- The native path runs only when it can prove support for every requested feature.
- Unknown sourcemaps, data models, collation options, remote data sources, custom handlers, or unsupported style features trigger external Biber.
- Fallback is automatic, visible in diagnostics, and recorded in benchmark results.
- No partial native output may be mixed with fallback output.

## 12.3 Optimise the external fallback

- Ship a non-self-extracting, architecture-native Biber installation rather than a PAR package where possible.
- Precompile Perl modules during packaging.
- Set stable cache and locale paths.
- Avoid repeated environment discovery.
- Pass BCF/BIB paths directly and suppress unnecessary logging in quiet mode.
- Measure Perl startup separately from Biber work.

## 12.4 Integrate bibliography into one scheduler

Like index processing, bibliography should occur inside one engine context, and the final PDF conversion should run once. Tectonic already orchestrates BibTeX; extend or wrap the driver so Biber becomes an observed stage rather than an opaque child process.

## 12.5 Stateful options, blocked on X10-D

If X10-D is approved:

- Content-address `.bbl` results by BCF, bibliography inputs, style/configuration, locale, Biber implementation, and environment identity.
- Keep a persistent native or Perl bibliography worker.
- Start bibliography work from a validated previous BCF while the next TeX pass runs, then discard it if the new BCF differs.

Acceptance targets:

- One-shot common-subset `biblatex` median below 500 ms as the first gate.
- Stateful repeated bibliography build below 150 ms as an X10-D gate.
- 100% fallback correctness for unsupported features.
- No material regression to ordinary non-bibliography builds.

---

## 13. Workstream X7: backend portfolio and automatic selection

**Priority:** strategic  
**Reason:** no single TeX engine is fastest or semantically correct for every workload

### X7.1 Implement explicit backend interfaces

```rust
trait LatexBackend {
    fn capabilities(&self) -> CapabilitySet;
    fn plan(&self, invocation: &Invocation) -> Result<BackendPlan>;
    fn execute(&self, plan: &BackendPlan, observer: &mut dyn Observer)
        -> Result<ExecutionResult>;
}
```

Initial backends:

1. Embedded Tectonic/XeTeX.
2. Minimal embedded or tightly packaged pdfTeX.
3. External TeX Live fallback.
4. LuaHBTeX backend after the first two are qualified.

### X7.2 Preserve explicit command semantics

- `pdflatex` should use a true pdfTeX-compatible backend when that backend is shipped and qualified.
- `xelatex` should use XeTeX/Tectonic semantics.
- `lualatex` should use LuaHBTeX semantics when available.
- The generic `tectdist` command may use an automatic backend selector.

Do not silently run a different semantic engine for an explicit alias merely because it benchmarks faster.

### X7.3 Build a conservative feature detector

Detect features such as:

- `fontspec`, `unicode-math`, XeTeX primitives.
- Lua code and LuaTeX primitives.
- pdfTeX driver assumptions and packages.
- Shell escape and externalisation.
- Backend-specific image and font requirements.

The detector is an optimisation hint, not a proof of TeX semantics. Unknown or dynamically constructed package loads select the requested/default safe backend.

### X7.4 Learn only from verified local history

An optional selector may remember which backend previously compiled a project correctly and fastest, keyed by source/configuration identity. This is cross-invocation state and remains blocked on X10-D.

### X7.5 Benchmark each backend class

The public report must include:

- Same-backend comparisons where semantics match.
- End-to-end “best correct backend” product comparisons.
- Backend selected and reason.
- Fallback rate.
- Output semantic-difference checks.

Acceptance:

- Tiny no longer loses because every document is forced through XeTeX.
- Backend selection never changes explicit alias semantics.
- Generic mode chooses the fastest qualified backend on the claim corpus.

---

## 14. Workstream X8: PDF, fonts, graphics, and large-document pipeline

**Priority:** profile-driven, essential for QFT and real books

### X8.1 Run PDF conversion only after convergence

Verify that intermediate TeX passes do not perform avoidable PDF work. For every multi-stage path, generate XDV/auxiliary state first and run final PDF construction once.

### X8.2 Pipeline XDV and PDF work

Research whether the XDV producer and PDF consumer can operate as a bounded streaming pipeline. Requirements:

- Deterministic output.
- Correct font subsetting.
- Error propagation and cancellation.
- No duplicate page storage.

### X8.3 Cache process-local font state

Within one invocation or batch:

- Cache fontconfig query results.
- Cache font file metadata and mappings.
- Avoid reopening the same font for each pass.
- Reuse shaping/layout configuration where safe.
- Delay subsetting until the final glyph set is known.

Cross-invocation font caches beyond normal OS/fontconfig caches are blocked on X10-D.

### X8.4 Parallelise independent finalisation

After TeX has fixed page content, investigate parallel execution of:

- Image decode and recompression.
- Independent font subsetting.
- Page content compression.
- Object stream compression.
- PDF object serialization with deterministic ordering.

Parallelism must not alter reproducible output metadata or object ordering unless the output oracle explicitly allows a semantically equivalent deterministic form.

### X8.5 Add large-document memory discipline

- Stream large images.
- Avoid full-document copies of XDV/PDF buffers.
- Use arenas for short-lived node data.
- Reuse buffers between passes.
- Record allocation and peak-RSS profiles.

Acceptance:

- ITP3 QFT has statistically qualified results, not one smoke pair.
- At least one real 100+ page document is part of the release gate.
- PDF correctness and reproducibility remain intact.

---

## 15. Workstream X9: compiler, linker, and CPU optimisation

This work follows stage profiling. It cannot substitute for architectural work.

### X9.1 Profile-guided optimisation

Train Rust and native C/C++ portions on a balanced corpus:

1. Instrumented build.
2. Run tiny, paper, biblatex, index, fonts, graphics, thesis, and QFT.
3. Merge profile data.
4. Rebuild with profile use.
5. Validate on held-out documents to prevent overfitting.

### X9.2 Architecture-specific bottles

Evaluate safe per-platform tuning:

- Apple arm64 baseline suitable for supported Apple Silicon.
- Linux arm64 baseline.
- Linux x86-64 portable baseline and optional x86-64-v3 bottle.
- Runtime dispatch for isolated SIMD routines where packaging cannot assume a newer CPU.

### X9.3 Link-time optimisation across language boundaries

- Compare ThinLTO and full LTO.
- Build static native dependencies where licensing and packaging permit.
- Investigate LLVM LTO across Rust and Clang-produced engine objects.
- Use BOLT or equivalent post-link optimisation on supported Linux builds.

### X9.4 Allocator and data-layout experiments

Benchmark, do not assume:

- System allocator.
- mimalloc.
- jemalloc.
- Arena allocation in the engine and PDF stage.
- Compact path/event records.

### X9.5 Split cold-network code from the hot compiler

If feature analysis shows TLS/HTTP dependencies increase binary load or startup:

- Move package acquisition into a separate helper or lazily loaded component.
- Keep the warm-clean compiler binary free of network initialisation.
- Preserve a seamless first-build experience.

Acceptance:

- Every build flag has an end-to-end corpus result.
- Held-out correctness and performance do not regress.
- Binary size, startup, and packaging costs are reported beside speed gains.

---

## 16. X10-D decision gate: state reuse and incremental compilation

**Current status:** parked  
**Decision owner:** repository owner  
**Default:** no daemon, no tectdist-managed project cache, no cross-invocation compiler state

### 16.1 Why this gate exists

A strict one-shot build must start a process, initialize an engine, load a format, execute TeX, and create a PDF. A sub-17 ms complete tiny build and a 350 ms seven-document aggregate are not technically credible without either:

- Reusing previously initialized state.
- Returning previously verified results.
- Compiling only the changed portion of a document.
- Replacing the underlying engine with a radically faster implementation.

Therefore, a practical 10x repeated-build result requires explicit reconsideration of parked Phase D.

### 16.2 Preconditions for un-parking

Do not start X10-D implementation until:

1. X0 and X1 produce trustworthy stage budgets.
2. X2 through X6 establish the one-shot ceiling.
3. A prototype demonstrates at least 3x improvement on three real documents.
4. The cache/snapshot invalidation model is reviewed.
5. The product explicitly distinguishes clean, resumed, incremental, and cache-hit results.

### 16.3 Minimum X10-D scope

If approved, unpark only a narrow `D-lite` programme first:

- Per-user local supervisor.
- Isolated worker process, not shared mutable engine state across arbitrary threads.
- Immutable bundle and format state loaded once.
- One project at a time per worker.
- Transparent one-shot fallback.
- No remote cache.
- No background network activity.
- Explicit shutdown and memory cap.

### X10-D.1 Preamble snapshot

Create a project-specific engine snapshot after a validated stable preamble or at `\begin{document}`.

Snapshot key includes:

- Engine build.
- Format and bundle identity.
- Exact preamble bytes and all preamble dependencies.
- Relevant environment.
- Fonts and configuration.
- Security/shell-escape mode.

Resume the document body from the snapshot. Fall back to full compilation when any key changes.

### X10-D.2 Dependency graph

Record every file and resource read, including package, font, image, bibliography, index style, shell command, and generated input. Use content hashes, not only timestamps.

### X10-D.3 Content-addressed stage cache

Cache independently:

- Preamble/format snapshot.
- Biber/BibTeX result.
- Index/glossary result.
- Image conversion.
- Font metadata/subset inputs.
- Final PDF only for an explicitly disclosed unchanged-build cache hit.

### X10-D.4 Page or shipout checkpoints

Research checkpoints at stable page boundaries. Recompile from the earliest invalid checkpoint and reuse earlier pages only when counters, marks, floats, references, and global assignments prove unchanged.

### X10-D.5 Speculative parallel stages

For an edit, begin work using the previous dependency manifest while validating the new one. Any mismatch invalidates speculative output before publication.

### 16.4 X10-D targets

| Scenario | Target |
|---|---:|
| Unchanged rebuild | `< 10 ms` p50 client-visible |
| Comment-only edit with unchanged PDF semantics | `< 15 ms` p50 |
| Visible local edit in a small document | `< 35 ms` p50 |
| Structural edit in a medium document | `< 100 ms` p50 where checkpoint validity permits |
| Bibliography unchanged | No Biber execution |
| Bibliography small edit | `< 150 ms` common-subset target |
| Stale-output failures | `0` across mutation, fault-injection, and crash-recovery suites |

These are research targets, not release claims.

---

## 17. Workstream X10-Clean: research path for 10x strict clean builds

If Phase D remains parked and the requirement is still 10x on fresh project outputs, the project must treat this as a new engine programme.

### X10-Clean.1 Project-specific format compilation

Investigate safe compilation of stable preambles into `.fmt`-like snapshots. This is project-specific reusable state and therefore cannot enter the active product while Phase D is parked, but it can be researched as an explicit benchmark mode.

### X10-Clean.2 TeX macro partial evaluation

Prototype an intermediate representation for hot, stable macro expansions:

- Tokenise once.
- Specialise common package and class macros.
- Compile deterministic macro paths to a compact bytecode or native code.
- Fall back to the interpreter for dynamic constructs.

Correctness must be differential against the reference engine over generated macro programs.

### X10-Clean.3 Replace hot C engine subsystems

Use profiles to choose, rather than broadly rewriting:

- Input/token scanner.
- Hash table/string pool.
- Macro expansion stack.
- Node allocation.
- Font lookup/layout.
- XDV writer.
- PDF object builder.

A Rust port is valuable only when it enables a faster data model, safer parallelism, or better optimisation. Language conversion alone is not a performance strategy.

### X10-Clean.4 Parallel document pipeline

TeX execution is globally stateful and mostly sequential. Research parallelism only at proven independence boundaries:

- Resource/package prefetch.
- Images.
- Font subsetting.
- Final page compression.
- Independent included standalone figures.
- Multi-document batch builds.

### X10-Clean.5 Backend-specialised compilation

A clean-build 10x result may be achievable on subsets through specialised backends:

- Fast pdfTeX backend for conventional ASCII/Latin documents.
- XeTeX/Tectonic backend for Unicode/fontspec.
- Pre-rendered or externally compiled TikZ figures with explicit cache disclosure.
- Native bibliography/index fast paths.

### X10-Clean.6 Research gates

Continue an experiment only when:

- It produces at least a 20% end-to-end improvement on a claim-relevant workload, or
- It demonstrates a credible route to a 2x stage improvement, and
- It passes differential semantics.

Terminate or park experiments that only improve isolated synthetic loops without moving end-to-end latency.

---

## 18. Corpus expansion and evidence programme

### 18.1 Claim corpus requirements

Before a “fastest compiler” release, include at least:

- 20 real, redistributable projects in the primary claim set.
- 50+ projects in an extended compatibility/performance set.
- A real 100+ page thesis or book.
- A substantial biblatex project.
- A large BibTeX project.
- Index and glossary projects.
- TikZ/PGFPlots.
- Graphics-heavy documents.
- Unicode/fontspec.
- Journal and conference templates.
- Multi-file projects.
- Shell-escape projects outside cache claims unless fully tracked.
- ITP3 QFT or an equivalent stress fixture.

### 18.2 Held-out corpus

Keep at least 25% of documents out of PGO training and backend-selection development. Publish held-out results to demonstrate generalisation.

### 18.3 Mutation corpus

Generate systematic changes:

- Same bytes, changed timestamps.
- Changed bytes, restored timestamps and sizes.
- Included-file edits.
- Package/style edits.
- Image edits.
- Font changes.
- `.bib` and locale changes.
- Index-style changes.
- Environment and `SOURCE_DATE_EPOCH` changes.
- Shell-escape command/output changes.
- Crashes during artifact publication.

### 18.4 Platform matrix

Qualification platforms:

- macOS arm64.
- Linux x86-64.
- Linux arm64.

Add macOS x86-64 only if it remains a supported release target. Use stable, dedicated performance hosts and record power mode, thermal state, CPU model, memory, OS, filesystem, and toolchain.

### 18.5 Competitors

Mandatory:

- TeX Live `latexmk`.
- Direct Tectonic.
- Previous accepted `tectdist` release.
- Same underlying engine without tectdist orchestration where possible.

Add where controlled:

- ClutTeX.
- MiKTeX.
- Raw pdfTeX/XeTeX/LuaHBTeX only when the oracle proves a single pass is complete.

---

## 19. CI, release, and claim gates

## 19.1 PR gates

- Rust release binary built and hashed.
- Differential correctness suite passes.
- Compact untraced benchmark subset passes.
- Trace schema remains compatible.
- Stage count does not unexpectedly increase.
- Binary size and startup reported.
- No new external process on a fast path without approval.

## 19.2 Nightly gates

- Full compact corpus.
- Real-document subset.
- Direct engine controls.
- TeX Live independent control.
- Stage flamegraph on rotating workloads.
- Current upstream Tectonic main comparison.
- Automatic issue on statistically supported regression.

## 19.3 Release qualification

- Three independent sessions per platform.
- At least 30 balanced pairs for ordinary cases.
- At least 15 pairs for expensive cases.
- Raw results and traces attached immutably.
- All correctness outputs pass.
- Candidate repository is clean and tagged.
- Exact compiler, engine, bundle, format, bibliography, index, and TeX Live manifests recorded.
- Public Markdown generated from raw JSON; no manually typed percentages.

## 19.4 Claim ladder

### Current defensible claim

> On the seven-project compact corpus on the reference Apple M3 Max, the native Rust implementation had 14.71% lower aggregate warm-clean latency than TeX Live 2026 `latexmk`.

### One-shot target claim

> tectdist had the lowest aggregate correct warm-clean build latency across the published real-world corpus on all supported qualification platforms.

### Backend-portfolio target claim

> tectdist selected the fastest qualified LaTeX backend and had the lowest latency in every published workload class.

### X10 target claim

> In the published unchanged and edit-build scenarios, tectdist was at least 10x faster than the fastest independent competitor while producing an oracle-verified result.

Never shorten the last statement to “10x faster at compiling LaTeX” unless clean-build evidence also supports it.

---

## 20. Prioritised milestone sequence

## Milestone 0: make the numbers trustworthy

Issues:

- **X10-001:** split timed and traced benchmark runs.
- **X10-002:** replace per-span trace file opens with a buffered sink.
- **X10-003:** build and benchmark the Rust release candidate in PR/nightly workflows.
- **X10-004:** make nightly use the independent TeX Live control and true qualification mode.
- **X10-005:** implement balanced AB/BA pairs and per-process resource collection.
- **X10-006:** publish the exact raw result used by `BENCHMARKS.md`.

Exit gate: repeated untraced qualification reproduces the baseline within the host noise envelope.

## Milestone 1: expose the real hot stages

- **X10-010:** Tectonic processing observer.
- **X10-011:** TeX/BibTeX/Biber/PDF stage spans.
- **X10-012:** I/O, digest, font, and image counters.
- **X10-013:** automated flamegraph artifacts.
- **X10-014:** stage budget report generated per commit.

Exit gate: at least 95% of wall time is assigned to named stages on tiny, index, biblatex, and QFT.

## Milestone 2: remove duplicated one-shot work

- **X10-020:** one `EngineContext` per invocation.
- **X10-021:** eliminate duplicate output-directory and artifact probes.
- **X10-022:** conditional intermediate/log retention.
- **X10-023:** blocking external-tool timeout implementation.
- **X10-024:** one final PDF conversion invariant.

Exit gate: no duplicated configuration/session/PDF stage appears in traces unless required by document semantics.

## Milestone 3: win index and glossary

- **X10-030:** driver stage-interception API.
- **X10-031:** integrated index scheduler.
- **X10-032:** in-process MakeIndex API or Rust port.
- **X10-033:** glossary pipeline.
- **X10-034:** MakeIndex/upmendex differential corpus.

Exit gate: index and glossary cases beat TeX Live and produce one final PDF.

## Milestone 4: recover upstream engine performance

- **X10-040:** Tectonic version matrix.
- **X10-041:** historical bundle adapter.
- **X10-042:** automated performance bisect.
- **X10-043:** fast convergence digest prototype.
- **X10-044:** file-size/open optimisation.
- **X10-045:** upstream patch series.

Exit gate: fastest correct engine revision is pinned by evidence; all local patches have upstream issues or PRs.

## Milestone 5: remove the bibliography ceiling

- **X10-050:** Biber stage decomposition.
- **X10-051:** native BCF/BIB parser.
- **X10-052:** common sorting/name/label subset.
- **X10-053:** native `.bbl` emitter.
- **X10-054:** automatic external fallback.
- **X10-055:** large differential bibliography corpus.

Exit gate: common-subset one-shot `biblatex` is below 500 ms and unsupported cases remain fully correct through fallback.

## Milestone 6: backend portfolio

- **X10-060:** backend trait and capability model.
- **X10-061:** qualified pdfTeX backend prototype.
- **X10-062:** conservative feature detector.
- **X10-063:** exact explicit-alias semantics.
- **X10-064:** generic-command backend selector.
- **X10-065:** backend selection evidence and fallback telemetry.

Exit gate: tiny and conventional pdfTeX-class documents no longer lose because of a forced XeTeX backend.

## Milestone 7: large-document and build-toolchain acceleration

- **X10-070:** PDF/font/image stage optimisation.
- **X10-071:** PGO across Rust and native engine code.
- **X10-072:** architecture-specific builds.
- **X10-073:** LTO/BOLT experiment matrix.
- **X10-074:** QFT and real-book qualification.

Exit gate: one-shot aggregate is at least 2x better than the audited baseline and wins on the expanded claim corpus.

## Milestone 8: X10-D decision

Owner chooses one:

- **Remain parked:** continue one-shot engine research; do not promise a 10x repeated-build product.
- **Unpark D-lite:** implement initialized workers, snapshots, dependency graph, and verified stage reuse.

Exit gate for approval: one isolated prototype shows at least 3x on three real edit workflows with zero stale outputs.

## Milestone 9: clean-build X10 research

Proceed only if strict clean-build 10x remains a product requirement after Milestone 7.

- Macro partial evaluation.
- Project format snapshots.
- Hot engine subsystem replacement.
- Parallel PDF pipeline.
- Page/checkpoint research.

Exit gate: a prototype produces at least one 5x clean-build result on a real document and has a credible, measured path to 10x without changing semantics.

---

## 21. First twelve pull requests

1. **Benchmark untraced wall time; move tracing to a separate diagnostic repetition.**
2. **Buffer native trace events and write once.**
3. **Build `target/release/tectdist` in `perf-pr.yml` and `perf-nightly.yml`.**
4. **Add TeX Live and `--qualification` to the real qualification workflow.**
5. **Add exact TeX/Biber/PDF stage observation to the embedded driver.**
6. **Generate a per-document stage-budget report.**
7. **Reuse one engine context across an index continuation.**
8. **Defer final PDF conversion until after index/glossary completion.**
9. **Add the Tectonic version/commit matrix and historical regression bisect.**
10. **Profile and replace convergence SHA/file-open hot paths where proven.**
11. **Decompose the Biber path and publish its stage budget.**
12. **Prototype a true pdfTeX backend for the tiny and conventional-document class.**

No daemon, project cache, or incremental engine PR belongs in this first sequence.

---

## 22. Risks and controls

| Risk | Consequence | Control |
|---|---|---|
| Benchmark optimisation instead of product optimisation | Fast synthetic fixtures, slow real documents | Real and held-out corpora; stage and end-to-end gates |
| Native Biber subset diverges from Biber | Incorrect bibliographies | Capability proof, differential corpus, automatic full fallback |
| Fast digest causes false equality | Stale references/citations | Length plus robust hash, mutation tests, optional byte confirmation |
| Backend selector changes semantics | Different output or failures | Explicit aliases fixed; generic mode conservative; fallback and semantic oracle |
| Private Tectonic fork becomes unmaintainable | Security and upgrade debt | Upstream-first patching; exact pin; named maintenance owner |
| PGO overfits tiny corpus | Regression on real projects | Held-out corpus and platform qualification |
| Parallel PDF work harms reproducibility | Nondeterministic PDFs | Deterministic ordering and reproducibility tests |
| X10 cache/snapshot returns stale output | Severe trust failure | X10-D gate, content identities, adversarial invalidation tests, one-shot fallback |
| “10x” marketing hides a cache hit | Misleading claim | Scenario-specific wording and raw evidence |
| Multi-backend package becomes too large | Distribution friction | Modular bottles, optional backends, measured install/startup trade-off |

---

## 23. Work explicitly not worth prioritising

Do not spend a milestone on any of the following without a profile proving material impact:

- Further micro-optimisation of the already tiny flag translator.
- Replacing small standard-library collections for aesthetic reasons.
- Changing allocators without end-to-end evidence.
- More compression of the old Python zipapp.
- A daemon whose only benefit is removing a few milliseconds of CLI startup.
- Comparing against a single incomplete `pdflatex` pass.
- Reporting a cached final PDF as a clean compilation.
- Tuning only the seven synthetic fixtures.
- Rewriting C in Rust without a data-model or parallelism advantage.

---

## 24. Definition of done

The programme is complete only when all applicable conditions hold:

### Fastest one-shot release

- Expanded real-world corpus is public and reproducible.
- Correctness pass rate is 100%.
- Candidate has the lowest aggregate p50 and p95 on every supported platform.
- Tiny and index no longer lose for architectural reasons that `tectdist` can control.
- Direct Tectonic overhead is within measurement noise.
- One-shot aggregate is at least 2x better than the audited `perf` baseline or the evidence establishes a clearly documented engine ceiling.
- Raw results, stage traces, manifests, and binary identities are immutable.

### X10 repeated-build release, only if X10-D is approved

- At least 10x improvement in every scenario cell named in the claim.
- Unchanged and edit results are distinguished from clean builds.
- No stale output in mutation, fault-injection, crash, and dependency tests.
- Resident worker is optional, isolated, bounded, and has transparent one-shot fallback.
- Cache and snapshot identities are inspectable through `tectdist doctor --json`.

### X10 clean-build release

- At least 10x improvement over the audited baseline and the fastest independent competitor on the declared clean-build corpus.
- The result does not rely on project-specific state excluded by the scenario definition.
- Real QFT/book/thesis, bibliography, index, graphics, and Unicode cases all qualify.
- Engine-level changes are maintainable, upstreamed where practical, and covered by semantic differential tests.

---

## 25. Immediate decision

The active engineering programme should begin with X0 through X7 while keeping Phase D parked.

After the one-shot architecture has a trustworthy stage budget and reaches its measured ceiling, the repository owner should make one explicit decision:

1. **Optimise for the fastest honest one-shot LaTeX compiler**, accepting that an order-of-magnitude clean-build gain may require a multi-year engine research programme; or
2. **Approve X10-D**, enabling a narrowly scoped initialized-worker, snapshot, and verified incremental path that can credibly deliver 10x improvements in normal editor and repeated-build workflows.

The current 14.71% result is a valid foundation. The path from 15% to 10x is not more wrapper work; it is stage elimination, backend choice, engine regression recovery, bibliography replacement, and eventually state reuse or a new execution model.

---

## 26. Evidence reviewed

Repository files on the `perf` branch:

- [`BENCHMARKS.md`](../BENCHMARKS.md)
- [`docs/TECHNICAL_PLAN.md`](TECHNICAL_PLAN.md)
- [`docs/NATIVE_MIGRATION.md`](NATIVE_MIGRATION.md)
- [`crates/tectdist-engine/src/lib.rs`](../crates/tectdist-engine/src/lib.rs)
- [`crates/tectdist-cli/src/main.rs`](../crates/tectdist-cli/src/main.rs)
- [`benchmarks/corpus/manifest.toml`](../benchmarks/corpus/manifest.toml)
- [`benchmarks/runner/cli.py`](../benchmarks/runner/cli.py)
- [`.github/workflows/perf-pr.yml`](../.github/workflows/perf-pr.yml)
- [`.github/workflows/perf-nightly.yml`](../.github/workflows/perf-nightly.yml)

Upstream technical references:

- [Tectonic releases](https://github.com/tectonic-typesetting/tectonic/releases)
- [Tectonic driver API](https://docs.rs/tectonic/latest/tectonic/driver/)
- [Tectonic performance regression discussion](https://github.com/tectonic-typesetting/tectonic/discussions/1268)
- [Historical Tectonic versus XeLaTeX performance issue](https://github.com/tectonic-typesetting/tectonic/issues/452)
- [Biber repository and architecture](https://github.com/plk/biber)
