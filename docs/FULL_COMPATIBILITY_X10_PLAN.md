# tectdist C100/X10: Universal Compatibility and 10× Execution Plan

**Status:** SUPERSEDED by `docs/BASICTEX_X10_PLAN.md`, which itself supersedes this file (see its header). Retained for architectural background only; its C100 universal-universe gate is no longer the active compatibility target.

**Original status:** Proposed successor to `docs/ORDER_OF_MAGNITUDE_PERFORMANCE_PLAN.md`  
**Repository:** `tmonk/tectdist`  
**Audit branch:** `perf`  
**Audit head:** `bd9c37ee43041421e6fbf11f324436290e314f7d`  
**Audit date:** 24 August 2026  
**Hard requirement C100:** full compatibility with every LaTeX package in the declared reference universe, with no package blacklist and no silent semantic substitution  
**Hard requirement X10:** at least a 10× end-to-end latency reduction in the declared benchmark scenarios, with correctness and fallback work included  
**Architecture decision:** the previous Phase D park is superseded; a resident supervisor, exact-engine fork servers, project snapshots, and incremental execution are mandatory  
**Release rule:** no universal compatibility or 10× claim is permitted until C100 and X10 pass simultaneously on the same release binary, package image, platform, and commit

---

## 1. Executive decision

The completed performance programme was valuable and should be retained. It fixed the measurement path, added native supervision and stage attribution, reused Tectonic configuration and bundle state, integrated MakeIndex, added an engine revision matrix, implemented a conservative backend model, and established auditable evidence.

It also established the limit of the present architecture:

- The seven-document warm-clean aggregate improved from 3.497 seconds to approximately 2.818 seconds, a 19.4% reduction.
- `tiny` improved to approximately 128 ms.
- `index` improved to approximately 175 ms.
- `biblatex` remains approximately 1.833 seconds.
- The 51-page QFT workload is approximately 30.27 seconds and statistically indistinguishable from direct Tectonic.
- ThinLTO and fat LTO are effectively equivalent end to end.

The wrapper and orchestration layers are therefore no longer the dominant opportunity. A 10× result cannot come from further CLI tuning, Rust allocation work, link-time options, or another round of small bundle lookup optimisations. It requires avoiding or reusing whole units of work.

The new programme changes the product from:

> a fast compatibility layer over one embedded Tectonic engine

to:

> a fully compatible TeX execution environment that runs the exact requested engines and tools, while accelerating them through persistent initialized state, copy-on-write snapshots, dependency-aware replay, external-stage reuse, and incremental PDF assembly.

This is the only architecture that can pursue both hard requirements without trading correctness for speed.

---

## 2. What the two requirements mean

The phrases “every package” and “10×” need machine-testable definitions. Without a bounded reference environment, “every package” changes daily. Without named cache and edit states, “10×” can be made either impossible or misleading.

### 2.1 C100 compatibility contract

For a pinned reference environment \(R\), invocation \(I\), project \(P\), and supported platform \(H\):

```text
if ReferenceTeXLive(R, I, P, H) produces a successful result,
then tectdist(R, I, P, H) must produce a semantically equivalent result.
```

The reference environment includes:

- The complete pinned TeX Live package image.
- The exact requested engine and format.
- The exact helper programs and versions.
- User fonts and declared external prerequisites.
- Environment variables, locale, shell-escape policy, and configuration.
- User and project TEXMF overlays.
- Network inputs when the reference build legitimately uses them.

A result is semantically equivalent only when all applicable properties agree:

- Exit status and fatal/non-fatal error behaviour.
- Requested engine semantics.
- PDF, DVI, PostScript, SyncTeX, log, and auxiliary artifacts.
- Page count and rendered page appearance within the declared visual tolerance.
- Extracted text, links, destinations, outlines, citations, references, indexes, and glossaries.
- Shell-escape command behaviour and produced files.
- Output-directory, job-name, recorder, interaction, and environment semantics.
- Rerun convergence and final resolved state.

C100 has the following non-negotiable consequences:

1. No package denylist.
2. No `claim = false` escape hatch for package compatibility.
3. No substitution of XeTeX for an explicit `pdflatex` request.
4. No substitution of Tectonic for an explicit LuaHBTeX, pLaTeX, or upLaTeX request.
5. No informational stub when a package requires a real helper.
6. No partial `latexmk` implementation as the final compatibility authority.
7. No bounded bibliography subset as the final Biber implementation.
8. A transparent fallback may use the exact reference executable, but fallback must remain correct, visible in telemetry, and included in performance measurements.

“Every package” means every package that is successful in the pinned reference environment. Broken upstream examples and packages whose declared external prerequisites are absent do not become successful merely because tectdist is installed; tectdist must match the reference verdict and diagnostics.

### 2.2 X10 performance contract

Two distinct 10× gates are required.

#### X10-E: default edit-to-PDF performance

After the first successful project build, the default `pdflatex`, `xelatex`, `lualatex`, `latexmk`, or `tectdist` invocation must be at least 10× faster than the pinned TeX Live reference for:

- Unchanged rebuild.
- Visible local text or equation edit.
- Structural edit.
- Citation edit.
- Bibliography database edit.
- Index and glossary edit.
- Figure replacement.
- Included-file edit.

This is the first mandatory X10 release gate because it reflects normal authoring work and can exploit validated prior state.

#### X10-C: runtime-warm, project-clean performance

With the package image, formats, and resident engine services warm, but with no project-specific output or project snapshot, tectdist must be at least 10× faster than the reference for a clean project build.

X10-C is required before the unqualified phrase “10× faster LaTeX compiler” may be used.

Cold installation, package download, and first-ever service startup are measured separately and may not be hidden inside pre-provisioning.

### 2.3 Current numerical budgets

Using the completed programme as the engineering baseline:

| Workload | Current | 10× budget |
|---|---:|---:|
| `tiny` | 128.0 ms | 12.8 ms |
| `index` | 175.4 ms | 17.5 ms |
| `biblatex` | 1833.4 ms | 183.3 ms |
| Seven-document aggregate | approximately 2818 ms | at most 281.8 ms |
| ITP3 QFT, 51 pages | 30.27 s | at most 3.03 s |

For comparison, 10× versus the older 4.100-second TeX Live aggregate permits 410 ms. The programme should use the stricter 281.8 ms internal budget so that “10×” cannot depend on choosing a weaker historical denominator.

### 2.4 Logical boundary for arbitrary shell escape

A package can invoke arbitrary user code through shell escape. Such a command can intentionally wait, access a network service, train a model, or perform unbounded computation. No compiler can guarantee a fixed acceleration ratio for arbitrary external computation while preserving its behaviour.

The enforceable contract is therefore:

- C100 includes arbitrary shell-escape compatibility.
- X10 includes the complete official TeX/LaTeX helper ecosystem and every deterministic external action represented in the qualification corpus.
- Arbitrary user commands are measured end to end and never hidden, but the universal compiler ratio is reported both including and excluding the explicitly labelled user-command span.
- A package is never excluded merely because it uses shell escape.
- Official package helpers must receive adapters, prefork services, or action-cache support until their corpus cells meet X10.

---

## 3. Audit of the current branch

### 3.1 Work to retain

The following completed work becomes the foundation of this programme:

- Untraced timed measurements and separate diagnostic repetitions.
- Native `wait4` benchmark supervision.
- Balanced AB/BA pairing and regression gates.
- Release-binary provenance.
- Buffered trace output.
- Engine stage observation.
- `EngineContext` reuse.
- Integrated XDV-first index/glossary scheduling.
- Embedded MakeIndex.
- Negative bundle-open caching and mutation tests.
- Tectonic revision and bisect tooling.
- ThinLTO evidence and PGO tooling.
- Backend capability data structures.
- Bibliography parser and differential scaffolding.
- Immutable evidence bundles.

These components should not be rewritten unless a measured requirement demands it.

### 3.2 Work that is no longer sufficient

#### Tectonic cannot be the universal semantic substrate

The current product documentation still describes every engine alias as Tectonic/XeTeX-based and excludes pdfTeX- and LuaTeX-specific behaviour, DVI/PostScript workflows, complete `latexmk`, and several real helper paths. That is incompatible with C100.

#### The backend portfolio is a selector skeleton

The current backend model names pdfTeX and LuaHBTeX, but they are not shipped or qualified. `ExternalFallback` is the only exact semantic answer for those contracts. C100 requires actual production backends, not source scanning that guesses whether another engine is “close enough.”

#### The bibliography fast path is intentionally partial

`tectdist-bib` currently implements a bounded parser/emitter subset and deliberately falls back for unsupported styles, fields, data models, sourcemaps, and related features. That is useful test infrastructure but cannot become the C100 bibliography authority.

#### One-shot execution has reached the raw engine

The QFT result is within noise of direct Tectonic. That proves that removing the remaining wrapper cost cannot approach 10× on engine-dominated documents.

#### Current evidence is not the final X10 comparison

The final compact evidence primarily compares the candidate with direct Tectonic and derives the approximately 2.818-second total against an earlier audited baseline. The new programme needs fresh, same-session pairings against the exact TeX Live reference for every release gate.

---

## 4. Architectural principles

### 4.1 Reference semantics first

The exact engine requested by the command name is the semantic authority:

| Command | Required engine semantics |
|---|---|
| `pdflatex`, `pdftex` | pdfTeX |
| `xelatex`, `xetex` | XeTeX |
| `lualatex`, `luatex`, `luahbtex` | LuaTeX/LuaHBTeX as requested |
| `latex`, `tex`, `etex` | classic TeX/e-TeX and DVI semantics |
| `platex`, `uplatex` | pTeX/upTeX family |
| generic `tectdist` | explicit configuration or a proven-safe selector; never changes an explicit alias |

Acceleration must occur below this boundary. The product must not obtain speed by changing engine semantics.

### 4.2 Use the real implementation as the fallback

For every engine and helper, the compatibility fallback is the actual pinned reference implementation. Native replacements may be selected only after exhaustive differential qualification.

### 4.3 Generic state reuse, not package allowlists

The main acceleration mechanism must snapshot exact engine state after arbitrary package initialization. It must not depend on a hard-coded list of “supported packages.” Package-specific adapters are allowed for external helper acceleration, but absence of an adapter must never break compatibility.

### 4.4 Validation before reuse

Every reused snapshot, action result, page, font object, or bibliography artifact must be keyed by every relevant dependency and validated before publication.

### 4.5 Fallback counts

A slow exact fallback is preferable to a fast wrong result, but fallback time counts against X10. The programme is complete only when the fallback paths used by the qualification corpus also meet the performance budget.

### 4.6 No benchmark state ambiguity

Every result records:

- Runtime service state.
- Engine/format state.
- Project snapshot state.
- Output/intermediate state.
- Action-cache state.
- Package-tree identity.
- External tool identity.
- Whether a fallback occurred.

---

## 5. Target system architecture

```text
traditional command name
        |
        v
native tectdist client
        |
        | authenticated local IPC
        v
tectdist supervisor
        |
        +--> semantic resolver
        |      exact engine + format + package image
        |
        +--> project state manager
        |      dependency graph
        |      preamble key
        |      page checkpoints
        |      output object graph
        |
        +--> engine fork server
        |      pdfTeX
        |      XeTeX
        |      LuaHBTeX
        |      pTeX/upTeX
        |      classic TeX/e-TeX
        |
        +--> stage broker
        |      BibTeX/Biber
        |      MakeIndex/Xindy
        |      glossaries
        |      MetaPost/Asymptote
        |      Pygments/PythonTeX
        |      Ghostscript/dvips/dvisvgm
        |      arbitrary shell escape
        |
        +--> content-addressed store
        |      package files
        |      formats
        |      snapshots
        |      action outputs
        |      fonts/images
        |      PDF objects
        |
        +--> validator
               convergence
               artifact semantics
               fallback escalation
```

### 5.1 Short-lived client

The existing native command remains the user-facing executable. It:

1. Determines the exact semantic contract from `argv[0]`.
2. Normalises compatibility flags without changing semantics.
3. Connects to the per-user supervisor.
4. Streams diagnostics and status.
5. Receives the final artifact result.
6. Falls back to exact one-shot execution when the service is unavailable.

The one-shot fallback preserves C100. It is not expected to meet X10.

### 5.2 Per-user supervisor

The supervisor owns:

- Worker lifecycle and crash isolation.
- Package and runtime identities.
- Snapshot and action-cache indexing.
- Project locks.
- Cancellation of superseded builds.
- Resource limits.
- Telemetry.
- Compatibility fallback escalation.

The socket is user-private and authenticated. No project can read another project’s source or outputs.

### 5.3 Exact-engine fork servers

There is one fork-server family per:

```text
engine build + format + package image + platform ABI + security policy
```

A fork server:

1. Starts the real engine implementation.
2. Loads the exact format.
3. Initializes Kpathsea and font configuration.
4. Reaches a fork-safe point before background threads.
5. Creates copy-on-write children for project snapshot construction and compilation.

The initial implementation should use patched upstream engine sources and preserve their global-state semantics. Linking the engines as libraries is preferable long term, but a minimally patched fork-server entry point is the quickest exact-semantic path.

### 5.4 Project preamble snapshots

For an exact preamble sequence, the engine runs through class/package loading and all `\AtBeginDocument` hooks, then pauses immediately before the first body token.

The snapshot captures the live process state rather than trying to reimplement package initialization. This is the universal package fast path.

The snapshot key includes:

- Engine and format identities.
- TeX Live/package image digest.
- Complete preamble token stream and included preamble files.
- Every package/class/config/font file read.
- Command-line flags and relevant environment.
- Locale, timezone, build-date policy, and random seed policy.
- Shell-escape actions performed before the snapshot.
- User TEXMF overlays.
- Font configuration and installed font identities.
- Driver/backend configuration.

A snapshot child is forked for each compile. The pristine snapshot parent is never mutated by a build.

### 5.5 Page and state checkpoints

Preamble snapshots alone cannot reduce a 30-second body-heavy document to three seconds. The engine must expose safe checkpoints at shipout and selected structural boundaries.

Each checkpoint records:

- Input stack and source location.
- TeX memory, eqtb, hash table, string pool, registers, marks, inserts, and output routine state.
- Font and backend state.
- Read/write dependency epochs.
- Auxiliary-file state.
- Cross-reference and citation state.
- Page/PDF object graph identifiers.
- A strong state digest for convergence validation.

On an edit:

1. Find the earliest checkpoint whose dependency set intersects the changed input.
2. Restore the preceding checkpoint.
3. Replay forward.
4. Compare the new state digest with later stored checkpoints.
5. When state convergence is proven, reuse the unchanged suffix.
6. If convergence cannot be proven, continue replaying to the end.
7. If any invariant fails, perform an exact full build.

Sparse checkpoints should be used initially to bound memory. The cadence can adapt to document structure and measured replay cost.

### 5.6 Incremental PDF assembly

Reusing TeX pages is insufficient if the entire PDF backend runs again. The PDF layer must support object-level reuse.

The content store records:

- Page content streams.
- Font programs and subsets.
- Image objects.
- Annotations, links, destinations, and outlines.
- Resource dictionaries.
- Metadata and trailer state.

A new PDF is assembled from changed objects plus validated unchanged objects. Object numbering may be rewritten; semantic identity matters, not byte identity.

For XeTeX:

- Parse XDV into page units.
- Cache font and image transformations.
- Process independent pages concurrently where resource dependencies permit.
- Run one final merge.

For pdfTeX and LuaHBTeX:

- Intercept backend object creation.
- Retain stable logical object IDs across builds.
- Reuse unchanged page and resource objects.

### 5.7 Exact external-stage broker

All process execution is routed through the stage broker. The broker can:

- Run the exact reference binary.
- Use a preforked exact implementation.
- Restore a validated cached result.
- Invoke a fully qualified native replacement.
- Record all inputs, outputs, environment, network, and side effects.

No tool is replaced by a stub when a package requires real behaviour.

---

## 6. Universal package and runtime substrate

### 6.1 Pinned full TeX Live image

Create an immutable, content-addressed image containing the complete supported TeX Live scheme:

- `texmf-dist`.
- Formats.
- Font maps and configuration.
- Engine binaries and runtime libraries.
- Scripts and helper tools.
- `texlive.tlpdb`.
- Package licences and provenance.
- Platform-specific executables.

Distribution options:

1. `tectdist-full`: offline full image.
2. Thin bootstrap plus content-addressed package chunks fetched on demand.
3. Enterprise/local mirror mode.

All modes resolve to the same image identity. On-demand distribution must never change package versions within an image.

### 6.2 Exact Kpathsea semantics

The current partial `kpsewhich` and maintenance stubs are insufficient. Integrate the real Kpathsea library or exact TeX Live tools for:

- `kpsewhich`.
- Recursive TEXMF lookup.
- `ls-R`.
- `mktex*`.
- `fmtutil`.
- `updmap`.
- Font map lookup and generation.
- `TEXMFHOME`, `TEXMFLOCAL`, `TEXMFVAR`, `TEXMFSYSVAR`, and related variables.
- Engine/program-name-specific paths.
- Brace expansion and path-element semantics.
- User and project overlays.

Fast path:

- Memory-map `ls-R` and configuration indexes.
- Keep parsed Kpathsea state in the fork server.
- Add a generation counter for mutable overlays.
- Cache negative lookups only within a validated generation.

### 6.3 Real engine portfolio

Ship and qualify:

- pdfTeX/e-pdfTeX.
- XeTeX.
- LuaTeX/LuaHBTeX.
- TeX/e-TeX.
- pTeX/e-pTeX.
- upTeX/e-upTeX.
- Required DVI/PDF drivers.

Tectonic may remain an optional generic backend, but it is not the semantic foundation of explicit aliases.

### 6.4 Complete output pipelines

Support the pipelines packages expect:

- Direct PDF.
- DVI.
- XDV.
- PostScript.
- `dvips`.
- `dvipdfmx`.
- `xdvipdfmx`.
- `dvisvgm`.
- Ghostscript conversions.
- PSTricks workflows.
- MetaPost-generated assets.

### 6.5 Upstream `latexmk` as compatibility authority

Ship the exact upstream `latexmk` corresponding to the reference image.

Two layers are used:

- Upstream `latexmk` parses complete rc syntax, custom dependencies, engine commands, and edge-case options.
- tectdist intercepts the concrete engine/tool invocations and services them through the accelerated supervisor.

The existing native `latexmk` parser may remain as a fast parser for proven common cases, but any unsupported or ambiguous configuration delegates to upstream `latexmk`. The fallback is automatic and included in timing.

### 6.6 Helper and language runtime packs

Package or discover the official external ecosystems used by LaTeX packages:

- Biber and BibTeX.
- MakeIndex, Xindy, and glossary tooling.
- Perl runtime.
- Python and Pygments.
- Asymptote.
- MetaPost.
- Ghostscript.
- gnuplot.
- Image conversion tools.
- Java or other declared package prerequisites where redistributable.

Non-redistributable tools are represented by signed adapters that validate a user-installed executable and incorporate its identity into action keys.

### 6.7 User overlays

C100 requires user packages and local classes:

- Read-only base image.
- Mutable per-user TEXMF overlay.
- Project-local overlay.
- Explicit package install and update commands.
- Snapshot invalidation on any overlay mutation.
- Reference mode that runs the exact same overlays under TeX Live for differential diagnosis.

---

## 7. Compatibility qualification factory

### 7.1 Package ledger

Generate a row for every package in the pinned package database:

```text
package
version
licence
supported engines
upstream tests
documentation examples
external prerequisites
reference result
tectdist result
fallback path
snapshot-safe result
X10 scenario result
```

No package row may be “excluded,” “untested,” or silently skipped at release.

### 7.2 Test source hierarchy

For each package, discover tests in this order:

1. Upstream `l3build` test suite.
2. Package-maintained test scripts.
3. Documentation build.
4. Shipped examples.
5. `.dtx` driver.
6. Generated minimal load case.
7. Curated feature cases for package families.

A generated `\usepackage{...}` smoke test alone is not enough when real examples exist.

### 7.3 Reference-green rule

A case enters the required compatibility set when it succeeds under the pinned reference environment. tectdist must then succeed with equivalent semantics.

A reference failure is retained in the ledger to prove that tectdist did not hide or reinterpret it, but it does not become a tectdist compatibility failure.

### 7.4 Package combinations

Individual package tests do not expose interactions. Add:

- Pairwise combinations for the most frequently co-used packages.
- Three-way covering arrays for package families.
- Known conflict/ordering cases.
- Class/package combinations.
- Engine-specific combinations.
- Shell-escape and bibliography combinations.

### 7.5 Real-world corpus

Maintain a large, licence-compatible corpus of:

- Journal templates.
- Theses and books.
- arXiv-style projects.
- TikZ/PGFPlots documents.
- Multilingual documents.
- Music, chemistry, linguistics, and diagram packages.
- Large bibliographies.
- pLaTeX/upLaTeX projects.
- DVI/PSTricks workflows.

The compact corpus remains a developer smoke suite, not the universal compatibility proof.

### 7.6 Oracles

Use layered comparison:

- Exit and diagnostic class.
- Normalised log comparison.
- Auxiliary file comparison.
- PDF structural checks.
- Page count.
- Extracted text.
- Link/outline/destination comparison.
- Rasterised page perceptual difference.
- DVI/XDV/PostScript validation.
- Shell-escape action and output comparison.
- Deterministic PDF object comparison where possible.

### 7.7 C100 release gate

A release passes C100 only when:

- 100% of reference-green package cases pass.
- 100% of required package-combination cases pass.
- 100% of the real-world qualification corpus passes.
- No package-specific skip is present.
- No required helper is a stub.
- Explicit aliases use exact semantics.
- All fallbacks are reported and tested.
- The same package image passes on every supported platform.

---

## 8. Engine snapshot programme

### 8.1 Fork-server implementation order

Implement exact-engine acceleration in this order:

1. pdfTeX.
2. XeTeX.
3. LuaHBTeX.
4. classic TeX/e-TeX.
5. pTeX/upTeX.

pdfTeX provides the quickest path to the tiny-document budget and validates the architecture with the simplest backend. XeTeX and LuaHBTeX then exercise font, Unicode, and backend complexity.

### 8.2 Fork-safe initialization

Each engine fork server must:

- Initialize in a single thread.
- Load format and Kpathsea state.
- Avoid starting network or font-cache worker threads before the fork point.
- Register `pthread_atfork` handlers where necessary.
- Reopen non-fork-safe handles in children.
- Pass sanitizer and stress tests.
- Recover cleanly from a child crash.

### 8.3 Preamble boundary

Add an engine/format hook that pauses after:

- Class and package loading.
- Preamble inputs.
- `\AtBeginDocument` hooks.
- Font and language initialization.

It must pause before consuming the first document-body token.

Do not split the source with a text regex. The engine must identify the semantic boundary through the actual macro/input execution state.

### 8.4 Snapshot safety manifest

Record resources that cross the snapshot:

- Open files and offsets.
- Temporary files.
- Pipes and sockets.
- Child processes.
- Thread state.
- Locale state.
- Current time and randomness usage.
- Shell-escape actions.
- Fontconfig and library caches.

Each resource type has a restore policy:

- Safe to inherit.
- Close and reopen.
- Recreate from a manifest.
- Replay exact action.
- Snapshot invalid.
- Full-build fallback.

The objective is to reduce “snapshot invalid” to zero across the C100 corpus.

### 8.5 Snapshot storage

Initial implementation:

- In-memory copy-on-write parent process.
- LRU eviction by resident memory.
- One snapshot per exact preamble key.

Later implementation:

- Serialized cold snapshot for restart.
- Compressed memory-page deltas.
- Shared immutable pages across related snapshots.
- Optional prebuilt snapshots for common class/package sequences.

### 8.6 Performance gates

- Format-loaded child creation: p50 below 2 ms.
- Preamble-snapshot child creation: p50 below 3 ms.
- Tiny body plus PDF from a warm project snapshot: p50 below 12.8 ms.
- Snapshot invalidation false-negative rate: zero.
- Snapshot false-positive rebuilds: measured and reduced, but correctness wins.

---

## 9. Bibliography and index programme

### 9.1 Preserve exact Biber semantics

The primary C100 acceleration path for Biber is not a bounded rewrite. It is the real Biber implementation in a prefork service:

1. Start Perl once.
2. Load Biber modules, Unicode data, locale tables, XML modules, and configuration.
3. Stop before job-specific state.
4. Fork a child per Biber invocation.
5. Execute the exact upstream code.
6. Capture outputs and diagnostics.
7. Discard the child.

This avoids interpreter/module startup without changing Biber semantics.

### 9.2 Biber action key

The cache key includes:

- Biber binary/source identity.
- `.bcf`.
- All `.bib` files.
- `.bbx`, `.cbx`, `.lbx`, data models, sourcemaps, and configuration.
- Locale and collation versions.
- Remote-source responses or immutable content identities.
- Environment and command-line options.
- User-defined Perl extensions if allowed.

If nothing bibliography-relevant changed, the `.bbl` and related outputs are restored without running Biber.

### 9.3 Incremental Biber research

After prefork and exact action reuse:

- Retain parsed bibliography databases in the pristine parent.
- Incrementally parse changed `.bib` files.
- Recompute only affected sorting and label groups.
- Differentially compare every output against exact upstream Biber.
- Do not select the incremental implementation until the complete Biber upstream test suite and tectdist corpus are 100%.

`tectdist-bib` can supply parser and model components, but its current bounded emitter must remain non-production.

### 9.4 BibTeX

Use the actual BibTeX engine in-process or preforked. The existing Tectonic-embedded BibTeX differential harness can be expanded, but exact style-language behaviour is mandatory.

### 9.5 Index and glossary

Retain embedded MakeIndex, then add:

- Exact Xindy prefork service.
- `makeglossaries` orchestration.
- Multiple indexes.
- Custom styles.
- Nomenclature.
- Language-specific collation.
- Full differential corpus.

### 9.6 Performance gates

- Unchanged bibliography stage: below 2 ms lookup/restore.
- Small Biber job with changed `.bib`: below 100 ms p50.
- Full `biblatex` build: below 183.3 ms p50 for the compact case.
- Index build: below 17.5 ms p50 for the compact case.
- Exact upstream output equivalence: 100%.

---

## 10. External action broker

### 10.1 Generic action model

```rust
struct ActionKey {
    executable_digest: Digest,
    argv: Vec<OsString>,
    cwd_identity: Digest,
    stdin_digest: Option<Digest>,
    environment: Vec<(OsString, OsString)>,
    input_files: Vec<(PathBuf, Digest)>,
    runtime_identity: Digest,
    network_inputs: Vec<NetworkInputIdentity>,
    policy_identity: Digest,
}

struct ActionResult {
    exit_status: i32,
    stdout: BlobId,
    stderr: BlobId,
    output_files: Vec<OutputRecord>,
    side_effect_manifest: SideEffectManifest,
}
```

### 10.2 Dependency capture

Use platform-specific tracing around external tools:

- Linux: seccomp/user-notification, fanotify, eBPF, or an audited preload shim.
- macOS: an audited interposition layer and filesystem event capture.
- Portable fallback: isolated input/output sandbox with conservative whole-tree hashing.

The first execution records reads and writes. A later invocation may be reused only when every observed input and runtime identity agrees.

### 10.3 Network, clock, and randomness

Actions using network, current time, or randomness are not assumed deterministic.

Policies:

- Record immutable network response identities when permitted.
- Re-run when freshness is part of semantics.
- Include declared time and random seed in the key.
- Never replay an untracked side effect.
- Preserve exact fallback behaviour.

### 10.4 Official helper adapters

Build exact adapters and qualification cases for helper families in priority order based on package usage and latency:

1. Biber/BibTeX.
2. MakeIndex/Xindy/glossaries.
3. Pygments/minted.
4. PythonTeX.
5. MetaPost.
6. Asymptote.
7. Ghostscript/dvips/dvisvgm.
8. gnuplot.
9. Package-specific generators discovered by the package ledger.

---

## 11. Dependency graph and invalidation

### 11.1 Build manifest

Every completed build produces a manifest containing:

- Runtime and package image.
- Engine, format, and backend.
- Every file read with digest and origin.
- Every file written.
- Environment reads.
- Font lookups.
- External actions.
- Network inputs.
- Time/randomness policy.
- Engine checkpoints.
- Auxiliary convergence state.
- Final artifact graph.

### 11.2 Fast file identity

Use a two-tier approach:

- Metadata and filesystem generation for cheap candidate checks.
- Content digest before any reuse decision.

Same-size/same-mtime mutation tests remain mandatory. No cache or snapshot may rely on modification time alone.

### 11.3 Mutable overlays

Every mutable TEXMF or project overlay has a generation counter and content index. A watcher is an optimisation; correctness always falls back to digest validation.

### 11.4 Environment contract

Record all environment variables consulted by:

- Kpathsea.
- Engines.
- `latexmk`.
- Helper tools.
- Fontconfig.
- shell escape.

Unknown environment access makes the relevant snapshot/action conservative until it is captured.

---

## 12. Page-level incremental execution

### 12.1 Earliest affected point

Map each source and generated dependency to:

- Preamble.
- Body token range.
- Engine checkpoint.
- Shipped pages.
- Auxiliary records.
- External actions.
- PDF objects.

An edit invalidates only the earliest affected checkpoint and its dependants.

### 12.2 Forward replay and suffix convergence

After restoring the prior checkpoint:

1. Replay changed input.
2. Produce new page and state digests.
3. Compare with old checkpoints.
4. If state and dependency generations match, reuse the suffix.
5. Otherwise continue.

A page that looks visually identical but leaves different engine state is not a convergence point.

### 12.3 Cross-reference convergence

Cross-reference changes may affect distant pages. Track auxiliary records separately:

- Labels.
- Citations.
- TOC/LOF/LOT.
- Page labels.
- Outlines.
- Index/glossary inputs.

Re-run only the stages whose input record changed. If the final auxiliary state matches the previous build, do not perform another global pass.

### 12.4 Speculative parallel replay

Once checkpoints are reliable:

- Start speculative children from several prior checkpoints.
- Validate boundary state.
- Keep only segments whose incoming and outgoing state matches.
- Cancel invalid speculation.

This is particularly valuable for long documents after local edits.

### 12.5 QFT gate

For the 51-page QFT fixture:

- Local visible edit: at most 3.03 seconds p50.
- Structural edit near the beginning: at most 3.03 seconds p50 after project snapshot exists.
- Correct page count and full oracle.
- No reused page whose dependencies changed.
- At least 15 paired release trials and three sessions.

---

## 13. Runtime-warm clean-build research

X10-C cannot rely on project-specific prior state. It needs deeper engine work.

### 13.1 Tokenised package cache

Cache the engine’s tokenised representation of immutable `.sty`, `.cls`, `.def`, and format inputs so clean builds avoid repeated UTF-8/line/token parsing.

The cache key includes engine catcode/encoding context where tokenisation semantics depend on it.

### 13.2 Common preamble snapshots

Ship or locally build snapshots for frequent exact sequences:

- Standard classes.
- Common font/language stacks.
- Major journal templates.
- TikZ/PGFPlots stacks.
- biblatex stacks.

Selection is exact-sequence-based. A miss builds the project normally and creates a new reusable snapshot.

### 13.3 Engine macro execution profiling

Profile and optimise:

- Control-sequence lookup.
- Token expansion.
- String-pool operations.
- Memory allocation.
- input-stack transitions.
- file lookup.
- digest generation.
- line breaking.
- math processing.
- node-list operations.

Potential work includes compact tables, faster hash functions for non-integrity equality, arena layout, branch reduction, and profile-guided optimisation across C/C++/Rust.

### 13.4 PDF backend parallelism

Investigate:

- Parallel image decoding.
- Parallel font parsing/subsetting.
- Page-parallel XDV conversion.
- Shared font/image object caches.
- Faster compression settings with size gates.
- Direct output-buffer management.

### 13.5 Linkable preamble state research

Develop a project-neutral state-delta format for exact package-loading sequences. This is more complex than ordinary TeX formats because package order and preamble code are stateful. Treat it as an exact replay/checkpoint problem, never as independent package modules unless equivalence is proven.

### 13.6 X10-C gate

- Seven-document runtime-warm/project-clean aggregate at most 281.8 ms.
- Compact `tiny` at most 12.8 ms.
- Compact `biblatex` at most 183.3 ms.
- QFT at most 3.03 seconds.
- No project output, project snapshot, or action result from an earlier build.
- Global engine/format/package caches may be warm and must be declared.
- Every result passes C100.

---

## 14. Protocol and data model

### 14.1 Client request

```rust
struct CompileRequest {
    protocol_version: u32,
    invocation: Invocation,
    semantic_contract: SemanticContract,
    cwd: PathBuf,
    environment: Vec<(OsString, OsString)>,
    stdin: Option<BlobId>,
    output_policy: OutputPolicy,
    diagnostic_mode: DiagnosticMode,
    cancellation_token: CancellationToken,
}
```

### 14.2 Runtime identity

```rust
struct RuntimeIdentity {
    tectdist_build: Digest,
    texlive_image: Digest,
    engine: EngineIdentity,
    format: Digest,
    kpathsea_config: Digest,
    tool_pack: Digest,
    platform_abi: String,
    security_policy: Digest,
}
```

### 14.3 Snapshot key

```rust
struct SnapshotKey {
    runtime: RuntimeIdentity,
    preamble_execution_digest: Digest,
    dependency_manifest_digest: Digest,
    environment_digest: Digest,
    font_environment_digest: Digest,
    side_effect_manifest_digest: Digest,
}
```

### 14.4 Checkpoint record

```rust
struct CheckpointRecord {
    snapshot: SnapshotId,
    source_position: SourcePosition,
    engine_state_digest: Digest,
    dependency_epoch: Digest,
    auxiliary_state_digest: Digest,
    shipped_pages: Vec<PageObjectId>,
    pdf_state: PdfStateId,
}
```

### 14.5 Result telemetry

Every invocation reports:

- Selected exact engine.
- Fast path or fallback.
- Snapshot hit/miss/invalidation reason.
- Replayed source range and page range.
- Reused pages and PDF objects.
- External action hits/misses.
- Time per stage.
- Validation time.
- Final correctness verdict.

Telemetry is local by default and contains no document content unless explicitly enabled.

---

## 15. Milestones

## Milestone U0 — Contract reset and architecture cut

Deliverables:

- Add this plan to `docs/`.
- Mark the prior order-of-magnitude plan completed/superseded.
- Update the product contract to C100/X10.
- Unpark Phase D.
- Remove any plan language that treats 2× or 3× as the final objective.
- Establish exact engine alias rules.
- Establish current TeX Live reference image.

Exit gate:

- Architecture decision accepted.
- Reference image digest recorded.
- Benchmark scenarios and X10 denominators frozen.

## Milestone U1 — Full TeX Live substrate

Deliverables:

- Complete package image.
- Exact engine portfolio.
- Exact Kpathsea.
- DVI/XDV/PS/PDF drivers.
- Real maintenance and font tools.
- User/project TEXMF overlays.

Exit gate:

- Existing compact and differential suites pass with exact alias semantics.
- No required tool in the package corpus resolves to a stub.

## Milestone U2 — Compatibility factory

Deliverables:

- Package ledger generator.
- Reference runner.
- Package test discovery.
- Output oracles.
- Combination generator.
- Real-world corpus ingestion.
- Sharded CI.

Exit gate:

- Every package has a ledger row.
- Every reference-green case has a tectdist verdict.
- Initial C100 report generated without exclusions.

## Milestone X1 — Supervisor and exact-engine fork servers

Deliverables:

- Per-user supervisor.
- Authenticated IPC.
- pdfTeX fork server.
- XeTeX fork server.
- LuaHBTeX fork server.
- One-shot exact fallback.

Exit gate:

- Format-loaded child startup below 2 ms p50.
- Full semantic differential suite passes.
- Crash and cancellation tests pass.

## Milestone X2 — Universal preamble snapshots

Deliverables:

- Semantic begin-document checkpoint.
- Snapshot key and manifest.
- COW child execution.
- Snapshot invalidation.
- Memory limits and eviction.

Exit gate:

- Snapshot works across every reference-green package case.
- Zero stale-output failures.
- Compact tiny edit build below 12.8 ms.

## Milestone X3 — Exact external-stage acceleration

Deliverables:

- Stage broker.
- Biber prefork.
- BibTeX prefork/in-process path.
- Xindy prefork.
- Official helper action cache.
- Shell-escape trace and replay.

Exit gate:

- Compact biblatex below 183.3 ms.
- Compact index below 17.5 ms.
- 100% Biber/BibTeX/index/glossary differential tests.

## Milestone X4 — Page checkpoints and replay

Deliverables:

- Engine checkpoint API.
- Dependency-to-checkpoint mapping.
- Suffix convergence.
- Sparse checkpoint storage.
- Full-build escalation.

Exit gate:

- QFT local edit below 3.03 s.
- No incorrect page reuse in mutation/fuzz testing.
- Structural/reference edits converge correctly.

## Milestone X5 — Incremental PDF graph

Deliverables:

- Page/resource object store.
- Stable logical object identities.
- XDV page parser.
- Font/image caches.
- Changed-object assembly.

Exit gate:

- Reused TeX pages do not trigger full PDF conversion.
- PDF oracle passes across all engines.
- QFT PDF assembly within its X10 budget.

## Milestone X6 — Runtime-warm clean acceleration

Deliverables:

- Tokenised package cache.
- Common preamble snapshot catalogue.
- Engine hot-loop patches.
- PDF backend parallelism.
- Cross-language PGO.

Exit gate:

- X10-C passes on compact, real-world, and large-document corpora.
- All changes upstreamed or assigned a named maintenance owner.

## Milestone R — Simultaneous C100/X10 qualification

Deliverables:

- Clean release commit.
- Immutable binaries and images.
- Multi-platform evidence.
- Full package compatibility report.
- X10-E and X10-C reports.
- Security and licensing audit.
- Recovery/fallback report.

Exit gate:

- C100 and X10 pass together.
- No package exclusion.
- No hidden setup.
- No stale result.
- No unmeasured fallback.

---

## 16. CI and evidence

### 16.1 Pull requests

Run:

- Rust/C/C++ unit tests.
- Differential command battery.
- Snapshot mutation suite.
- 1–5% deterministic package shard.
- Package interaction smoke set.
- Compact X10-E performance smoke.
- Exact release binary provenance.
- No traced timing path.

Performance regressions fail when they exceed the larger of:

- 3%.
- 0.5 ms for micro paths.
- The bootstrapped confidence threshold.

### 16.2 Nightly

Run:

- Rotating package shards.
- Full compact corpus.
- Several real-world documents.
- All snapshot invalidation mutations.
- Biber/index/helper differentials.
- Daemon restart and cache-corruption tests.
- X10-E gates.

### 16.3 Weekly

Run:

- Complete package universe across shards.
- Package combinations.
- All exact engines.
- Large QFT/book/thesis corpus.
- X10-C subset.
- Security sandbox tests.

### 16.4 Release qualification

On macOS arm64, Linux x86-64, and Linux arm64:

- Full C100 package set.
- Full real-world corpus.
- Three independent performance sessions.
- At least 30 paired trials for ordinary cases.
- At least 15 paired trials for expensive cases.
- Fresh paired TeX Live reference.
- Same package tree and tool identities.
- p50, p95, CPU, RSS, process count, bytes read/written, snapshot/action hit rate.
- Raw evidence committed or attached immutably.

### 16.5 Evidence rules

- Same binary and image for compatibility and performance.
- Fallback cells remain in aggregate results.
- Service startup and snapshot construction are separately reported.
- No cached-output hit is labelled clean compile.
- No package case may disappear between reports.
- Dirty-worktree results are engineering evidence only.

---

## 17. Security, correctness, and recovery

### 17.1 Shell escape

Preserve the requested TeX semantics while isolating projects:

- Per-build sandbox.
- Explicit trusted/untrusted modes.
- Exact command broker.
- Network policy.
- Output ownership and path confinement.
- No cross-project cache replay without content proof.

### 17.2 Cache poisoning

- Content-address every stored object.
- Verify digests on read.
- Atomic publication.
- Separate untrusted project namespaces.
- Sign release-provided snapshots and package chunks.
- Delete corrupt entries and rebuild exactly.

### 17.3 Snapshot corruption

- Child-only mutation.
- Periodic full-build comparison.
- Random shadow full builds in nightly testing.
- Epoch invalidation on runtime changes.
- Crash-safe supervisor journal.

### 17.4 Fallback

Any validation uncertainty triggers the exact reference path. The final output is never published from an unverified partial build.

### 17.5 Reproducibility

Record:

- Runtime image.
- Engine commit.
- tool packs.
- package overlays.
- snapshot key.
- external actions.
- build date/time policy.
- random policy.
- platform ABI.

---

## 18. Risk register

| Risk | Impact | Mitigation |
|---|---|---|
| Full TeX Live image is very large | Installation and distribution cost | Chunked content-addressed delivery plus offline full image |
| Engine fork safety | Crashes or corrupt state | Single-threaded fork point, atfork handlers, sanitizers, child isolation |
| Preamble side effects | Unsafe snapshot reuse | Resource manifest and exact restore policy; fallback on uncertainty |
| Lua/native library state | Snapshot complexity | Engine-specific snapshot adapters and stress tests |
| Biber global state | Incorrect reused output | Pristine prefork parent and exact child execution |
| Arbitrary shell escape | Uncacheable work or security exposure | Broker, sandbox, dependency capture, exact execution |
| Page checkpoint state is incomplete | Stale or wrong PDF | Strong state digests, replay widening, full-build fallback |
| PDF object reuse breaks links/fonts | Semantic corruption | Object graph oracle and rendered-page differential testing |
| Upstream engine maintenance burden | Long-lived fork | Small patch series, upstream PRs, named maintainers |
| Package corpus false failures | Blocks C100 inaccurately | Reference-green rule and deterministic environment |
| Package update invalidates evidence | Claim drift | Immutable package image per release |
| Cross-platform snapshot differences | Uneven support | Platform-specific backends behind one protocol, same gates |
| Memory growth from snapshots | Poor UX | LRU, shared COW pages, quotas, telemetry |
| Fast path silently falls back often | X10 failure | Fallback ledger and performance gate includes fallback |
| Licensing of complete tool packs | Distribution risk | Automated licence inventory and optional user-provided adapters |

---

## 19. Issue backlog

### Contract and substrate

- **C100-001** Add C100/X10 contract and supersede the prior plan.
- **C100-002** Build immutable full TeX Live image and manifest.
- **C100-003** Integrate exact Kpathsea.
- **C100-004** Ship pdfTeX/e-pdfTeX.
- **C100-005** Ship XeTeX.
- **C100-006** Ship LuaTeX/LuaHBTeX.
- **C100-007** Ship TeX/e-TeX and DVI drivers.
- **C100-008** Ship pTeX/upTeX family.
- **C100-009** Replace all package-relevant stubs with real tools.
- **C100-010** Delegate full rc/custom-dependency parsing to upstream `latexmk`.
- **C100-011** Add user/project TEXMF overlays.
- **C100-012** Add complete output pipeline qualification.

### Compatibility factory

- **C100-020** Generate package ledger from `texlive.tlpdb`.
- **C100-021** Discover `l3build` and package test suites.
- **C100-022** Compile package documentation/examples.
- **C100-023** Add PDF/DVI/PS visual and semantic oracle.
- **C100-024** Add package pairwise combinations.
- **C100-025** Add three-way covering arrays.
- **C100-026** Ingest real-world corpus.
- **C100-027** Build sharded compatibility CI.
- **C100-028** Generate no-exclusion C100 report.

### Stateful runtime

- **X10-100** Implement supervisor protocol and private socket.
- **X10-101** Implement exact one-shot fallback.
- **X10-102** Build pdfTeX fork server.
- **X10-103** Build XeTeX fork server.
- **X10-104** Build LuaHBTeX fork server.
- **X10-105** Add fork safety and crash tests.
- **X10-110** Add semantic begin-document pause.
- **X10-111** Build snapshot resource manifest.
- **X10-112** Build snapshot key and invalidation.
- **X10-113** Add COW snapshot LRU.
- **X10-114** Add snapshot telemetry.

### External stages

- **X10-120** Add generic action broker.
- **X10-121** Add Biber prefork service.
- **X10-122** Add exact Biber action key.
- **X10-123** Add BibTeX in-process/prefork path.
- **X10-124** Add Xindy prefork service.
- **X10-125** Integrate glossaries and nomenclature.
- **X10-126** Add minted/Pygments adapter.
- **X10-127** Add PythonTeX adapter.
- **X10-128** Add MetaPost/Asymptote adapters.
- **X10-129** Add Ghostscript/DVI adapters.
- **X10-130** Add generic shell-escape dependency capture.

### Incremental engine and PDF

- **X10-140** Define complete engine checkpoint state.
- **X10-141** Implement sparse shipout checkpoints.
- **X10-142** Map dependencies to checkpoints.
- **X10-143** Implement forward replay.
- **X10-144** Implement suffix-state convergence.
- **X10-145** Add speculative segment execution.
- **X10-150** Define stable logical PDF object graph.
- **X10-151** Reuse unchanged page objects.
- **X10-152** Cache fonts and images.
- **X10-153** Add page-parallel XDV conversion.
- **X10-154** Implement final PDF merge oracle.

### Clean-build research

- **X10-160** Add tokenised immutable package cache.
- **X10-161** Build common preamble snapshot catalogue.
- **X10-162** Profile engine macro hot loops.
- **X10-163** Replace convergence digest with qualified fast equality.
- **X10-164** Add cross-language PGO.
- **X10-165** Prototype linkable preamble-state deltas.
- **X10-166** Qualify runtime-warm clean X10.

### Release

- **REL-100** Run full C100 qualification.
- **REL-101** Run X10-E qualification.
- **REL-102** Run X10-C qualification.
- **REL-103** Audit licensing and redistribution.
- **REL-104** Audit sandbox and cache security.
- **REL-105** Publish immutable evidence and claim text.

---

## 20. Recommended pull-request order

1. **Contract reset:** add this plan, unpark Phase D, freeze reference and denominators.
2. **Exact semantic aliases:** remove all implicit engine substitution from explicit commands.
3. **Full package image and Kpathsea:** establish the compatibility substrate.
4. **Real tool replacement:** remove package-relevant stubs and wire exact helpers.
5. **Compatibility ledger:** enumerate every package and produce the first reference report.
6. **Supervisor scaffold:** client IPC, exact one-shot fallback, lifecycle tests.
7. **pdfTeX fork server:** format-loaded snapshot and tiny benchmark.
8. **Semantic preamble checkpoint:** arbitrary-package COW snapshot.
9. **Biber prefork and action cache:** attack the current dominant compact stage without reducing semantics.
10. **XeTeX/LuaHBTeX fork servers:** extend snapshot support to Unicode engines.
11. **Page checkpoint prototype:** local edits in QFT.
12. **Incremental PDF object graph:** remove full backend reruns.
13. **External helper adapters:** reach zero slow fallback in qualification cases.
14. **Full C100 package report:** no exclusions.
15. **X10-E qualification:** all edit scenarios.
16. **Runtime-warm clean research:** token caches, common snapshots, engine patches.
17. **X10-C qualification and release.**

Each performance PR must include:

- Before/after raw bundle.
- Stage attribution.
- Correctness result.
- Snapshot/action fallback count.
- Non-overlapping gain ledger entry.
- Multi-platform implications.
- Revert plan.

---

## 21. Work to stop

Do not spend further primary effort on:

- CLI parser micro-optimisation.
- Thin versus fat LTO absent new evidence.
- Replacing Biber with a small supported subset.
- Source-text heuristics that switch explicit engine semantics.
- More Tectonic wrapper reductions on QFT.
- Package allowlists.
- Stubs that return success.
- Aggregate claims derived from old competitor sessions.
- Calling an unchanged-output cache hit a clean compile.

These can consume engineering time without moving either hard requirement.

---

## 22. Definitions of done

### 22.1 C100 done

- Every reference-green package case passes.
- Every required package combination passes.
- Every real-world project passes.
- Exact engines and outputs are honoured.
- All official helper stages work.
- No package blacklist.
- No required stub.
- Same result on every supported platform.
- Public package ledger has no missing row.

### 22.2 X10-E done

- Every declared edit scenario is at least 10× faster than paired TeX Live p50.
- p95 is at least 8× faster.
- Fallbacks and external stages are included.
- No stale output across mutation and fuzz testing.
- QFT local and structural edits are at most 3.03 seconds.
- Compact biblatex is at most 183.3 ms.
- Compact tiny is at most 12.8 ms.

### 22.3 X10-C done

- Runtime-warm/project-clean aggregate is at most 281.8 ms.
- QFT clean project is at most 3.03 seconds.
- No project-specific snapshot or previous output is present.
- Global runtime state is disclosed.
- C100 still passes on the same build.

### 22.4 Final product done

The same release passes C100, X10-E, and X10-C, with immutable evidence and no exception language.

---

## 23. Immediate next actions

During the first implementation cycle:

1. Freeze the full TeX Live reference image and produce its manifest.
2. Replace the current backend semantics rule so explicit aliases never switch engines.
3. Generate the complete package ledger.
4. Prototype a pdfTeX format-loaded fork server.
5. Measure child creation, tiny body execution, and direct PDF output against the 12.8 ms budget.
6. Prototype an exact Biber prefork parent and measure the compact biblatex case.
7. Add daemon-aware benchmark scenarios and state labels.
8. Build the semantic `\begin{document}` snapshot hook.
9. Add one real package-heavy project to prove arbitrary-package snapshotting.
10. Begin the QFT page-checkpoint prototype immediately; it is the critical proof that the programme can reduce engine-dominated work rather than merely startup.

The decisive proof points are:

- **Tiny:** can an exact pdfTeX snapshot produce the final one-page PDF below 12.8 ms?
- **Biblatex:** can exact preforked/cached Biber plus a project snapshot complete below 183.3 ms?
- **QFT:** can checkpoint replay and PDF object reuse complete a visible edit below 3.03 seconds?
- **C100:** can the package ledger reach 100% without package-specific exclusion?

If any proof point fails, the next work must target the failed stage directly. The programme must not compensate by weakening the workload, hiding setup, changing engine semantics, or dropping packages.
