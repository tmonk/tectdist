# tectdist BT100/X10: BasicTeX Compatibility and 10× Execution Plan

**Status:** Revised successor to `docs/FULL_COMPATIBILITY_X10_PLAN.md`  
**Repository:** `tmonk/tectdist`  
**Audit branch:** `perf`  
**Audit head:** `bd9c37ee43041421e6fbf11f324436290e314f7d`  
**Audit date:** 24 August 2026  
**Hard requirement BT100:** complete compatibility with the exact packages, formats, engines, tools, and default configuration shipped by a pinned BasicTeX release, with no exception inside that manifest  
**Hard requirement X10:** at least a 10× end-to-end latency reduction in the declared BasicTeX benchmark scenarios, with correctness, validation, helper stages, and fallback work included  
**Distribution constraint:** the core release must not embed, fetch, test, or claim compatibility with the full TeX Live archive  
**Architecture decision:** the resident supervisor, exact-engine fork servers, project snapshots, dependency-aware replay, and incremental output work remain required for X10  
**Release rule:** no “BasicTeX compatible” or “10× faster” claim is permitted until BT100 and the applicable X10 gate pass simultaneously on the same release binary, BasicTeX image, platform, and commit

---

## 1. Executive decision

The compatibility target is narrowed from the complete TeX Live package universe to **BasicTeX parity**.

The reference is the exact package closure installed by a pinned BasicTeX release. On non-macOS qualification hosts, the equivalent TeX Live `scheme-small` installation is reduced or augmented to the same package manifest. BasicTeX is the MacTeX project’s small TeX distribution and is explicitly described as the cross-platform `scheme-small` equivalent. It provides the standard TeX engines and tools required for ordinary TeX and LaTeX work without installing the complete TeX Live archive.

The new product goal is:

> **tectdist is a drop-in BasicTeX-compatible distribution that produces correct, fully resolved outputs at least 10× faster than the pinned BasicTeX reference in the declared clean-build and edit-build scenarios.**

This changes the programme materially:

- The release is not required to ship or test every CTAN/TeX Live package.
- The package ledger contains only packages present in the pinned BasicTeX manifest.
- Packages installed later with `tlmgr` are outside BT100 unless promoted into a separately versioned extension profile.
- Biber, biblatex, Xindy, Asymptote, Pygments, PythonTeX, Japanese engine families, ConTeXt, and other ecosystems are not assumed to be core requirements. Their status is determined only by the captured BasicTeX manifest.
- The current `biblatex` benchmark is no longer automatically part of the core X10 gate.
- The full-package qualification factory is replaced by a much smaller BasicTeX compatibility factory.
- The runtime and package image must remain close to the BasicTeX footprint rather than growing toward MacTeX or `scheme-full`.

The 10× requirement remains difficult. The completed performance programme has already reduced wrapper and orchestration costs, and the QFT result shows that large one-shot builds have reached raw Tectonic performance. The X10 architecture therefore still requires initialized engine processes, exact preamble snapshots, dependency-aware replay, and incremental PDF/DVI/XDV output. Narrowing the package universe makes these mechanisms practical to qualify; it does not make another round of CLI micro-optimisation sufficient.

---

## 2. Goal and scope

## 2.1 BT100 compatibility contract

Let:

- `B` be a pinned BasicTeX package image;
- `H` be a supported platform;
- `I` be an invocation using a command, engine, format, package, or tool present in `B`;
- `P` be a project whose TeX dependencies are all resolvable from `B`, `TEXMFHOME`, `TEXMFLOCAL`, or the project tree;
- `E` be the declared external environment and prerequisites.

The compatibility rule is:

```text
if BasicTeX(B, H, I, P, E) succeeds,
then tectdist(B, H, I, P, E) must succeed with semantically equivalent results.

if BasicTeX(B, H, I, P, E) fails,
tectdist must not hide the failure through a stub, silent package substitution,
or a different engine.
```

Semantic equivalence includes every applicable property:

- Exit status and fatal/non-fatal diagnostic class.
- Exact requested engine semantics.
- Format selection.
- PDF, DVI, XDV, PostScript, HTML, SyncTeX, log, and auxiliary artifacts supported by the pinned image.
- Page count and rendered appearance within the declared visual tolerance.
- Extracted text, links, destinations, outlines, citations, references, indexes, and tagging structure.
- Shell-escape command behaviour and produced files.
- Output directory, job name, recorder, interaction, and environment semantics.
- Kpathsea search order and user/project TEXMF overlays.
- Rerun convergence and final resolved state.

BT100 has the following consequences:

1. Every package in the pinned BasicTeX manifest has a compatibility ledger row.
2. No package inside that manifest may be blacklisted or marked “not relevant.”
3. Explicit `pdflatex`, `xelatex`, and `lualatex` commands use their real semantic engines.
4. A real helper is required whenever the BasicTeX reference invokes one.
5. A slow exact fallback is allowed, but it is visible, tested, and included in X10 measurements.
6. A package absent from the BasicTeX manifest is not part of BT100 merely because it exists in a TeX Live network repository.
7. The core release never installs extra packages behind the user’s back.

## 2.2 Authoritative reference universe

The authoritative reference is not a hand-written list. It is generated from a clean BasicTeX installation and frozen into the repository.

Required artefacts:

```text
reference/basictex-2026/
  installer.sha512
  installed-packages.txt
  texlive.tlpdb
  files.sha256
  binaries.txt
  formats.txt
  fmtutil-list.txt
  updmap-state.txt
  kpathsea-vars.json
  package-closure.json
  platform-manifest.json
  licence-report.json
```

Generate the package set using the installed TeX Live database rather than assuming that `scheme-small` is byte-identical on every platform or update date.

The lock includes:

- Package name and TeX Live revision.
- Installed run files.
- Installed binary package for the platform.
- Installed fonts and maps.
- Generated formats.
- Configuration state.
- Exact executable identities.

The repository must be able to reproduce the image from an immutable TeX Live mirror or from archived package containers.

## 2.3 Included core capabilities

The manifest decides the final list, but the BasicTeX 2026 reference is expected to include the standard TeX toolchain, including the principal pdfTeX, XeTeX, and LuaTeX engines. The 2026 BasicTeX release also includes core LaTeX tagging support and `tex4ht`.

The core programme therefore prepares for:

- TeX and e-TeX.
- LaTeX and development formats shipped by the image.
- pdfTeX/pdfLaTeX.
- XeTeX/XeLaTeX.
- LuaTeX/LuaLaTeX/LuaHBTeX aliases present in the image.
- MetaFont and MetaPost.
- BibTeX if present.
- MakeIndex if present.
- DVI generation and `dvips` if present.
- `tex4ht`/HTML workflows if present.
- Kpathsea and TeX Live maintenance tools present in the image.
- The complete default BasicTeX package and font set.

Nothing is added to this list merely because a full MacTeX installation supplies it.

## 2.4 Explicitly outside BT100

Unless present in the frozen BasicTeX manifest, the following are outside the core compatibility and X10 claims:

- Packages installed after the base image with `tlmgr install`.
- `scheme-medium`, `scheme-full`, and arbitrary CTAN package collections.
- ConTeXt.
- pTeX/upTeX and Japanese collections.
- Biber and biblatex.
- Xindy.
- Asymptote.
- Pygments/minted.
- PythonTeX.
- Ghostscript and conversions that BasicTeX does not itself install.
- GUI applications.
- Non-TeX external software not included in the BasicTeX image.

These may be offered as **extension profiles**, but an extension profile has its own manifest, compatibility report, size, and performance claims. Extension failures do not weaken BT100, and extension packages must not be silently pulled into the core image.

## 2.5 `tlmgr` and extension mode

BasicTeX normally allows users to add packages with `tlmgr`. tectdist must make the boundary explicit.

Core mode:

```text
tectdist profile = basictex-2026
```

- Uses only the locked BasicTeX package image and user/project overlays.
- Passes BT100 and X10 gates.
- Is immutable except for a deliberate profile upgrade.

Extended mode:

```text
tectdist profile = basictex-2026+user
```

- May install additional TeX Live packages into a separate overlay.
- Records the package overlay manifest in `tectdist doctor --json`.
- Preserves exact engine and Kpathsea behaviour.
- Does not inherit the BT100 or X10 claim for packages outside the core manifest.
- Can be promoted into a named, tested extension profile later.

`tlmgr info`, `search`, and read-only package inspection should remain available. Package installation must never mutate the signed base image.

---

## 3. X10 performance contract

## 3.1 X10-E: normal edit-to-output performance

After the first successful project build, the default invocation must be at least 10× faster than the pinned BasicTeX reference for each declared scenario that applies to the project:

- Unchanged rebuild.
- Visible local text edit.
- Local equation edit.
- Structural edit.
- Cross-reference edit.
- BibTeX database or citation edit when BibTeX is in the core manifest.
- Index edit when MakeIndex is in the core manifest.
- Included-file edit.
- Figure replacement using formats and tools in the core manifest.
- XeLaTeX font or Unicode edit.
- LuaLaTeX document edit.
- DVI, PostScript, or HTML workflow edit where supported by the image.

Every result must include validation and output publication time. A cached-output lookup is measured and labelled as an unchanged rebuild, never as a clean compile.

## 3.2 X10-C: runtime-warm, project-clean performance

With the BasicTeX image, formats, font indexes, and resident services warm, but with no project-specific outputs, action results, preamble snapshot, or page checkpoints, tectdist must be at least 10× faster than the BasicTeX reference for the frozen clean-build corpus.

The following state may be warm and must be declared:

- Signed BasicTeX package image.
- Parsed Kpathsea indexes.
- Loaded engine binaries.
- Loaded formats.
- Global immutable font indexes.
- Generic, project-neutral caches whose keys do not contain project content.

The following state must be absent:

- Prior project outputs.
- Project-specific auxiliary files.
- Project-specific preamble snapshots.
- Project action-cache entries.
- Project page or PDF object checkpoints.

## 3.3 Baseline reset

The previous seven-document aggregate is not the BT100 denominator because it contains workloads whose package dependencies may not be part of BasicTeX, especially the Biber/biblatex case.

Milestone B0 must:

1. Install the pinned BasicTeX reference from scratch.
2. Resolve every current corpus document against the locked manifest.
3. Mark each document as `basictex-core`, `extension`, or `invalid`.
4. Add missing engine and output cases required by BasicTeX.
5. Run paired BasicTeX-versus-tectdist measurements.
6. Freeze per-document and aggregate denominators.

The 10× budget is then defined as:

```text
x10_budget(document, scenario, platform)
    = 0.10 * median(BasicTeX reference paired samples)
```

A separate internal budget may compare against the completed `perf` candidate, but public X10 claims use the pinned BasicTeX reference.

## 3.4 Provisional engineering budget

Until the BasicTeX-only baseline is generated, the current measurements remain diagnostic:

- `tiny`: approximately 128 ms.
- `index`: approximately 175 ms.
- Current one-shot non-Biber cases are generally in the 130–320 ms range.
- The large QFT workload is approximately 30 seconds but is not assumed to belong to the BasicTeX package universe.

The first architecture proof should demonstrate:

- Format-loaded child creation below 2 ms p50.
- Preamble-snapshot child creation below 3 ms p50.
- A complete one-page BasicTeX-native PDF below the frozen 10× budget.
- A local edit in a 50-page BasicTeX-native book below the frozen 10× budget.

## 3.5 Shell escape boundary

BT100 preserves shell escape to the extent that the pinned BasicTeX reference provides it.

Arbitrary user commands can perform unbounded work. Therefore:

- Official helpers included in the BasicTeX image are part of X10.
- User commands are executed exactly and included in end-to-end timing.
- Reports show compiler time and user-command time separately.
- No universal acceleration ratio is promised for the body of arbitrary user programs.
- The package or project is never excluded merely for using shell escape.

---

## 4. Audit of the current `perf` head

## 4.1 Work to retain

The latest branch already provides the correct foundation:

- Untraced timed benchmark paths.
- Native `wait4` supervision for wall time, CPU, and RSS.
- Release-binary SHA-256 provenance.
- Balanced AB/BA pairing and regression gates.
- Buffered trace publication.
- Engine-stage observation with approximately complete stage attribution.
- `EngineContext` reuse.
- Integrated XDV-first index/glossary scheduling.
- Embedded MakeIndex.
- Negative immutable-bundle lookup caching.
- Mutation tests covering same-size/same-mtime edits.
- Tectonic revision and bisect tooling.
- ThinLTO/fat-LTO evidence and PGO tooling.
- Backend capability scaffolding.
- Bibliography parser and differential-test scaffolding.
- Immutable benchmark evidence bundles.

These remain active unless superseded by exact BasicTeX engine integration.

## 4.2 Scope changes required

### 4.2.1 Rename the compatibility objective

Replace `C100`/“universal TeX Live” language with `BT100`/“pinned BasicTeX image.”

### 4.2.2 Stop treating Biber as the core ceiling

The current `biblatex` result dominates the old aggregate. It is not a core blocker unless Biber and biblatex appear in the frozen BasicTeX manifest.

Actions:

- Retain `tectdist-bib` as optional extension research.
- Remove the `biblatex` document from the BT100 aggregate unless the manifest proves it is core.
- Keep exact external Biber fallback for extended profiles.
- Do not spend core milestone capacity on a full Biber rewrite.

### 4.2.3 Implement only manifest-required engines

The previous universal plan required pTeX/upTeX and every major TeX family. The BasicTeX plan requires only engines actually shipped in the reference image.

The expected priority is:

1. pdfTeX/pdfLaTeX.
2. XeTeX/XeLaTeX.
3. LuaTeX/LuaLaTeX.
4. TeX/e-TeX/LaTeX DVI paths.
5. MetaPost/MetaFont and other manifest tools.

### 4.2.4 Replace full-package tests with a finite ledger

The compatibility factory now covers the BasicTeX package closure, not the entire TeX Live database. This should reduce qualification from thousands of packages to a tractable, release-locked set.

### 4.2.5 Retain the stateful X10 direction

The QFT control result shows that one-shot orchestration is already close to raw engine performance. Exact engine fork servers, snapshots, and incremental replay remain necessary for an order-of-magnitude result.

---

## 5. Architectural principles

### 5.1 BasicTeX manifest is the boundary

No package is core because it is popular, useful, or available from CTAN. A package is core only when it is present in the frozen BasicTeX manifest.

### 5.2 Exact engine semantics

Explicit aliases never switch semantic engines:

| Command | Required semantics |
|---|---|
| `pdflatex`, `pdftex` | pdfTeX |
| `xelatex`, `xetex` | XeTeX |
| `lualatex`, `luatex`, `luahbtex` | the Lua engine supplied by the image and requested alias |
| `latex`, `tex`, `etex` | classic TeX/e-TeX and DVI semantics |
| generic `tectdist` | explicit configuration or a proven-safe selector; never overrides an explicit alias |

### 5.3 Exact fallback before native replacement

The actual BasicTeX executable is the compatibility authority. A native replacement may become default only after differential qualification across all affected BT100 cases.

### 5.4 Generic state reuse

Acceleration should snapshot exact engine state after arbitrary BasicTeX package initialization. It must not be based on package allowlists.

### 5.5 Validation before reuse

Every snapshot, auxiliary result, external action, page, font object, and final output is reused only when all relevant dependencies and runtime identities match.

### 5.6 Fallback counts against X10

A correct fallback is preferable to a wrong fast path, but its time remains in the benchmark aggregate.

### 5.7 Small distribution as a release invariant

The build must fail if the core package image expands beyond the locked BasicTeX closure.

Suggested packaging gate:

```text
core TeX payload compressed size
    <= max(200 MiB, 1.5 * official BasicTeX installer size)
```

Any exception requires an explicit package-manifest change, size report, and compatibility justification.

---

## 6. Target system architecture

```text
traditional TeX command
        |
        v
native tectdist client
        |
        | authenticated local IPC
        v
tectdist supervisor
        |
        +--> BasicTeX profile resolver
        |      locked package image
        |      exact engine + format
        |
        +--> project state manager
        |      dependency graph
        |      preamble snapshot
        |      page checkpoints
        |      output object graph
        |
        +--> exact-engine fork servers
        |      pdfTeX
        |      XeTeX
        |      LuaTeX/LuaHBTeX
        |      TeX/e-TeX DVI path
        |
        +--> core stage broker
        |      BibTeX
        |      MakeIndex
        |      MetaPost/MetaFont
        |      dvips
        |      tex4ht
        |      manifest-listed shell helpers
        |
        +--> content-addressed store
        |      BasicTeX files and formats
        |      preamble snapshots
        |      action outputs
        |      fonts/images
        |      PDF/DVI/XDV/HTML objects
        |
        +--> validator
               convergence
               output semantics
               exact fallback escalation
```

## 6.1 Short-lived client

The native command:

1. Determines the exact semantic contract from `argv[0]`.
2. Parses compatible flags without changing semantics.
3. Selects the locked BasicTeX profile.
4. Connects to the per-user supervisor.
5. Streams diagnostics.
6. Publishes outputs atomically.
7. Falls back to exact one-shot BasicTeX execution when the service is unavailable.

## 6.2 Per-user supervisor

The supervisor owns:

- Worker lifecycle and crash isolation.
- BasicTeX profile identity.
- Snapshot and action-cache indexes.
- Project locks and cancellation.
- Resource limits.
- Telemetry.
- Fallback escalation.

The service is user-private. Project state is isolated by user and project identity.

## 6.3 Exact-engine fork servers

One fork-server family exists for each:

```text
BasicTeX image + engine build + format + platform ABI + security policy
```

A fork server:

1. Starts the exact engine implementation.
2. Initializes Kpathsea.
3. Loads the exact format.
4. Reaches a verified fork-safe point.
5. Forks copy-on-write children for snapshot construction and compilation.

The first implementation may use a small patch series against TeX Live engine sources. Long term, the patches should be upstreamed or assigned a named maintainer.

## 6.4 Project preamble snapshots

The engine runs through class/package loading and `\AtBeginDocument` hooks, then pauses before the first body token.

The snapshot key includes:

- BasicTeX image digest.
- Engine and format identities.
- Preamble token execution digest.
- All class/package/config/font files read.
- User and project TEXMF overlays.
- Command-line flags.
- Relevant environment and locale.
- Shell-escape effects before the snapshot.
- Driver and backend configuration.

A pristine parent snapshot is never mutated by a build.

## 6.5 Page and state checkpoints

For long documents, record sparse checkpoints at shipout and structural boundaries.

Each checkpoint includes:

- Source/input position.
- TeX memory and control-sequence state.
- Registers, marks, inserts, and output-routine state.
- Font/backend state.
- Auxiliary records.
- Dependency epochs.
- Output object references.
- Strong convergence digest.

An edit restores the nearest safe preceding checkpoint and replays until state convergence is proven.

## 6.6 Incremental output assembly

Support object-level reuse for every core output path:

- pdfTeX PDF objects.
- XeTeX XDV pages and `xdvipdfmx` resources.
- LuaTeX PDF objects.
- DVI pages.
- PostScript pages generated by `dvips`.
- tex4ht HTML assets and dependency graph.

Reused objects must pass structural and semantic validation.

## 6.7 Core external-stage broker

Every process invoked by a core BasicTeX workflow is routed through a broker that can:

- Run the exact BasicTeX binary.
- Use a preforked exact implementation.
- Restore a validated action result.
- Invoke a qualified in-process replacement.
- Record inputs, outputs, environment, network, and side effects.

No core helper may be replaced by a success-returning stub.

---

## 7. BasicTeX runtime substrate

## 7.1 Immutable base image

Build a content-addressed runtime containing only the frozen BasicTeX closure:

- Run files from the installed TLPDB.
- Platform engine/tool binaries.
- Generated formats.
- Fonts and maps installed by BasicTeX.
- Kpathsea configuration.
- TeX Live package database.
- Licences and provenance.

Do not include:

- Full package documentation and sources unless BasicTeX installs them.
- Packages absent from the manifest.
- GUI applications.
- Ghostscript unless explicitly added as a separate extension profile.
- A network mirror of the full TeX Live archive.

## 7.2 Cross-platform equivalence

BasicTeX is a macOS installer. For Linux:

1. Install TeX Live `scheme-small`.
2. Compare its installed package list with the macOS BasicTeX manifest.
3. Add or remove packages until the macro/font closure matches.
4. Substitute only platform binary packages.
5. Record a shared logical image digest plus a platform-binary digest.

BT100 requires equivalent TeX files and formats across platforms, not byte-identical executables.

## 7.3 Exact Kpathsea semantics

Integrate real Kpathsea or exact manifest tools for:

- Recursive TEXMF lookup.
- `ls-R` databases.
- `kpsewhich`.
- `mktex*` tools present in the image.
- `fmtutil` and format discovery.
- `updmap` and font-map lookup.
- `TEXMFHOME`, `TEXMFLOCAL`, `TEXMFVAR`, and system trees.
- Program-name-specific paths.
- Brace expansion and empty path components.

Fast path:

- Memory-map immutable indexes.
- Keep parsed configuration in fork servers.
- Version mutable overlays.
- Cache negative lookups only within a validated generation.

## 7.4 Engine portfolio

Ship exact engines present in the BasicTeX manifest.

Expected core set:

- pdfTeX/e-pdfTeX.
- XeTeX.
- LuaTeX/LuaHBTeX as installed.
- TeX/e-TeX.
- MetaFont and MetaPost.

No pTeX/upTeX, ConTeXt, or other engine family is included unless the manifest contains it.

Tectonic may remain as an optional generic compiler, but it is not used to emulate explicit BasicTeX engine aliases.

## 7.5 Output pipelines

Qualify only pipelines available from the locked image:

- Direct PDF from pdfTeX and LuaTeX.
- XDV plus `xdvipdfmx` for XeTeX.
- DVI from TeX/LaTeX.
- PostScript through `dvips` if installed.
- MetaPost outputs.
- HTML/MathML through `tex4ht` if installed.
- SyncTeX when supported.

Ghostscript-dependent conversion is an optional extension if Ghostscript is not part of BasicTeX.

## 7.6 Driver policy

If `latexmk` is not present in the BasicTeX manifest, it is not part of BT100. tectdist may still ship a small driver pack as an added product feature.

Reference benchmarking does not need `latexmk`. Each document manifest defines the exact BasicTeX command sequence required to reach a fully resolved result, for example:

```text
pdflatex
pdflatex
```

or:

```text
pdflatex
bibtex
pdflatex
pdflatex
```

The benchmark timer includes the complete sequence.

The tectdist `latexmk` compatibility command must either:

- Implement the declared supported interface exactly; or
- Delegate to an upstream `latexmk` extension pack.

It is not allowed to expand the BasicTeX package claim implicitly.

## 7.7 User and project overlays

BT100 includes:

- `TEXMFHOME`.
- `TEXMFLOCAL`.
- Project-local `.sty`, `.cls`, `.tex`, `.bib`, fonts, and assets.

A local package is compatible when its dependencies resolve within the BasicTeX image or declared project/user overlays. Installing arbitrary remote dependencies moves the runtime into extended mode.

---

## 8. BasicTeX compatibility qualification factory

## 8.1 Package ledger

Generate a row for every package in the frozen BasicTeX package database:

```text
package
TeX Live revision
licence
installed files
supported engines/formats
upstream tests
shipped examples/documentation tests
external prerequisites
reference result
tectdist result
fallback path
snapshot result
X10 result
```

No core package row may be missing, excluded, or untested at release.

## 8.2 Test source hierarchy

For each core package, discover tests in this order:

1. Upstream `l3build` tests.
2. Package-maintained tests.
3. Shipped documentation builds.
4. Shipped examples.
5. `.dtx` driver.
6. Generated minimal load cases.
7. Curated family tests.

A minimal `\usepackage{...}` test is only the fallback when no real example exists.

## 8.3 Reference-green rule

A test enters the required set when it succeeds under the pinned BasicTeX reference. tectdist must then produce an equivalent result.

Reference failures remain recorded to ensure that tectdist does not hide or reinterpret them.

## 8.4 Package interactions

Because the package universe is small, run stronger interaction coverage than the universal plan could afford:

- All package pairs where combined loading is valid.
- Three-way covering arrays across package families.
- Class/package ordering cases.
- pdfTeX/XeTeX/LuaTeX variants.
- Tagging and hyperref interactions when present.
- BibTeX and index interactions when present.
- DVI/dvips and tex4ht interactions when present.

## 8.5 BasicTeX real-world corpus

Build a corpus that uses only the frozen BasicTeX image:

- Plain TeX document.
- Standard LaTeX article.
- Report/book with references and table of contents.
- AMS-style mathematics where installed.
- BibTeX bibliography.
- Index.
- pdfLaTeX document.
- XeLaTeX Unicode/font document using image-provided fonts.
- LuaLaTeX document.
- DVI and `dvips` workflow.
- MetaPost workflow.
- tex4ht HTML workflow.
- Tagged PDF workflow for the 2026 core tagging packages.
- A 50–100 page BasicTeX-native stress document.

Documents requiring non-core packages are extension tests and do not enter BT100.

## 8.6 Oracles

Use layered comparison:

- Exit status and diagnostic class.
- Normalised logs.
- Auxiliary files.
- PDF structure and page count.
- Extracted text, links, outlines, and tagging structure.
- Rasterised page comparison.
- DVI/XDV/PostScript validation.
- HTML DOM and asset comparison.
- Shell-escape actions and outputs.
- Deterministic object comparison where possible.

## 8.7 BT100 release gate

A release passes BT100 only when:

- 100% of reference-green package tests pass.
- 100% of required interaction cases pass.
- 100% of the BasicTeX real-world corpus passes.
- Every manifest command has a tested tectdist path or exact fallback.
- No core helper is a stub.
- Explicit aliases use exact engine semantics.
- The same logical package image passes on every supported platform.
- Core package payload matches the locked manifest exactly.

---

## 9. Engine snapshot programme

## 9.1 Implementation order

1. pdfTeX.
2. XeTeX.
3. LuaTeX/LuaHBTeX.
4. TeX/e-TeX DVI path.
5. Manifest-listed secondary engines/tools.

pdfTeX is the quickest proof for tiny-document latency. XeTeX and LuaTeX then validate Unicode/font and runtime-state complexity.

## 9.2 Fork-safe initialization

Each server must:

- Initialize in one thread.
- Load Kpathsea and the format.
- Avoid non-fork-safe background threads before the fork point.
- Reopen unsafe handles in children.
- Register appropriate `atfork` hooks.
- Pass sanitizer and stress tests.
- Recover from child crashes.

## 9.3 Semantic preamble boundary

Pause after:

- Class and package loading.
- Preamble inputs.
- Font and language initialization.
- `\AtBeginDocument` hooks.

Pause before the first body token. Do not detect this boundary with source regexes.

## 9.4 Snapshot safety manifest

Record:

- Open files and offsets.
- Temporary files.
- Pipes and sockets.
- Child processes.
- Thread state.
- Locale, clock, and randomness state.
- Shell-escape actions.
- Font library caches.

Each resource type is classified as:

- Safe to inherit.
- Close and reopen.
- Recreate.
- Replay.
- Snapshot invalid.

The objective is zero snapshot exclusions across the BT100 corpus.

## 9.5 Snapshot storage

Initial:

- In-memory copy-on-write parents.
- LRU by resident memory.
- One parent per exact snapshot key.

Later:

- Serialized restartable snapshots.
- Compressed dirty-page deltas.
- Shared immutable pages.
- Signed generic snapshots for common BasicTeX preambles.

## 9.6 Performance gates

- Format-loaded fork child: below 2 ms p50.
- Preamble-snapshot fork child: below 3 ms p50.
- Tiny edit build: at or below its frozen X10 budget.
- Snapshot false-negative invalidation: zero.
- Snapshot memory remains within declared per-user limits.

---

## 10. Bibliography, index, and core helper programme

## 10.1 BibTeX

If BibTeX is present in the BasicTeX manifest, use the exact implementation:

- Prefork or link the real BibTeX engine.
- Preserve `.bst` language behaviour.
- Cache exact results by `.aux`, `.bib`, `.bst`, environment, and engine identity.
- Reuse unchanged `.bbl` output only after dependency validation.

The existing bibliography differential harness can be expanded for BibTeX.

## 10.2 Biber and biblatex

Biber is not a core blocker unless present in the frozen BasicTeX manifest.

Policy:

- Core profile: no Biber dependency unless the manifest contains it.
- Extended profile: exact external or preforked Biber, separately qualified.
- `tectdist-bib`: remains optional research and differential infrastructure.
- The BT100 aggregate excludes Biber/biblatex extension cases.

## 10.3 MakeIndex

Retain embedded MakeIndex if the image includes MakeIndex and the implementation remains byte/semantic compatible.

Qualify:

- Custom styles.
- Multiple indexes supported by the core packages.
- Encodings and locale behaviour present in BasicTeX.
- Exact diagnostics and exit codes.

## 10.4 MetaPost and MetaFont

Use exact binaries or prefork services for workflows present in the image. Capture generated inputs/outputs and reuse deterministic results when validated.

## 10.5 `dvips` and `tex4ht`

Provide exact stage adapters for:

- DVI to PostScript through `dvips`.
- tex4ht HTML generation and its helper scripts.

The action key includes every configuration, font map, input, executable, environment value, and generated asset.

## 10.6 Performance gates

Final values are frozen from paired BasicTeX measurements. Initial targets:

- Unchanged BibTeX/MakeIndex/MetaPost action restore: below 2 ms p50.
- Changed compact index action: below its X10 budget.
- Changed compact BibTeX action: below its X10 budget.
- Core helper output equivalence: 100%.

---

## 11. External action broker

## 11.1 Generic action model

```rust
struct ActionKey {
    profile: BasicTeXProfileId,
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

## 11.2 Dependency capture

Use:

- Linux sandbox/interposition or audited filesystem tracing.
- macOS audited interposition and filesystem event capture.
- A conservative sandbox-and-hash fallback.

A result may be reused only when every observed input and runtime identity agrees.

## 11.3 Clock, network, and randomness

- Do not assume deterministic behaviour.
- Include declared time and seed in action keys.
- Re-run when freshness is semantic.
- Never replay untracked side effects.

## 11.4 Adapter priority

Only manifest-relevant helpers are core priorities:

1. BibTeX.
2. MakeIndex.
3. MetaPost/MetaFont.
4. `dvips`.
5. `tex4ht` and its scripts.
6. Other helpers found in the BasicTeX manifest.
7. Generic shell escape.

Biber, Xindy, Pygments, PythonTeX, Asymptote, Ghostscript, and other tools are extension work unless the manifest includes them.

---

## 12. Dependency graph and invalidation

Every completed build records:

- BasicTeX profile and image digest.
- Engine and format.
- Every file read and written.
- Environment reads.
- Font lookups.
- Core helper actions.
- Network/time/randomness policy.
- Engine checkpoints.
- Auxiliary convergence state.
- Output object graph.

Use metadata only as a cheap candidate filter. Compute a content digest before reuse. Same-size/same-mtime mutation tests remain mandatory.

Every mutable TEXMF or project overlay has a generation and content index. Watchers improve latency but never replace digest validation.

---

## 13. Page-level incremental execution

## 13.1 Earliest affected checkpoint

Map source and generated dependencies to:

- Preamble.
- Body token range.
- Engine checkpoint.
- Output pages.
- Auxiliary records.
- Helper actions.
- PDF/DVI/XDV/HTML objects.

## 13.2 Replay and convergence

After restoring the preceding checkpoint:

1. Replay changed input.
2. Produce new page and state digests.
3. Compare with stored checkpoints.
4. Reuse the suffix only when engine state and dependencies match.
5. Continue replay or fall back to a full exact build on uncertainty.

Visual equality alone is insufficient; engine state must converge.

## 13.3 Cross-reference convergence

Track labels, citations, contents lists, outlines, index inputs, and page labels separately. Re-run only stages whose input records changed.

## 13.4 Large BasicTeX document gate

Create a 50–100 page stress document using only BasicTeX packages. It must exercise:

- References and contents.
- Mathematics.
- Multiple included files.
- Images or MetaPost assets available within the profile.
- pdfTeX, XeTeX, or LuaTeX variants where practical.

For visible local and structural edits, each variant must meet its frozen X10-E budget with full output validation.

The existing QFT fixture remains an optional engine stress test. It is not a BT100 release gate when it requires extension packages.

---

## 14. Runtime-warm clean-build research

X10-C cannot use project-specific state.

## 14.1 Tokenised immutable-file cache

Cache tokenised representations of immutable BasicTeX `.sty`, `.cls`, `.def`, and format inputs, keyed by engine and tokenisation context.

Because the package universe is finite, the cache can be fully prebuilt and exhaustively validated for the locked image.

## 14.2 Generic BasicTeX preamble catalogue

Provide signed snapshots for exact common sequences drawn from the installed package set:

- Plain TeX.
- Standard article/report/book classes.
- Core mathematics stack.
- Standard pdfLaTeX setup.
- Standard XeLaTeX font setup.
- Standard LuaLaTeX setup.
- Core tagging stack.
- tex4ht setup.

Selection is exact by executed preamble digest, never heuristic.

## 14.3 Engine hot loops

Profile and patch:

- Control-sequence lookup.
- Token expansion.
- String pool.
- Arena allocation and memory layout.
- File lookup.
- Rerun digests.
- Line breaking and math processing.
- Font loading and subsetting.
- PDF/XDV/DVI output.

Use PGO and architecture-specific builds only when held-out end-to-end results improve.

## 14.4 Output backend parallelism

Investigate:

- Parallel image decoding.
- Parallel font parsing/subsetting.
- Page-parallel XDV conversion.
- Shared immutable font/image caches.
- Incremental HTML asset publication.

## 14.5 X10-C gate

- Every BasicTeX clean-build corpus cell is at least 10× faster than its paired reference median.
- Aggregate is at least 10× faster.
- No project-specific snapshot/output/action result exists before timing.
- Global state is fully disclosed.
- BT100 passes on the same binary and image.

---

## 15. Protocol and identity model

```rust
struct CompileRequest {
    protocol_version: u32,
    profile: BasicTeXProfileId,
    invocation: Invocation,
    semantic_contract: SemanticContract,
    cwd: PathBuf,
    environment: Vec<(OsString, OsString)>,
    stdin: Option<BlobId>,
    output_policy: OutputPolicy,
    diagnostic_mode: DiagnosticMode,
    cancellation_token: CancellationToken,
}

struct RuntimeIdentity {
    tectdist_build: Digest,
    basictex_image: Digest,
    platform_binary_image: Digest,
    engine: EngineIdentity,
    format: Digest,
    kpathsea_config: Digest,
    tool_pack: Digest,
    overlay_manifest: Option<Digest>,
    platform_abi: String,
    security_policy: Digest,
}

struct SnapshotKey {
    runtime: RuntimeIdentity,
    preamble_execution_digest: Digest,
    dependency_manifest_digest: Digest,
    environment_digest: Digest,
    font_environment_digest: Digest,
    side_effect_manifest_digest: Digest,
}
```

Every result reports:

- BasicTeX profile and whether it is core or extended.
- Exact engine and format.
- Fast path or fallback.
- Snapshot hit/miss reason.
- Replayed source/page ranges.
- Reused output objects.
- Helper action hits/misses.
- Stage durations.
- Validation result.

---

## 16. Milestones

## Milestone B0 — Contract and baseline reset

Deliverables:

- Add this plan to `docs/`.
- Supersede universal/full-TeX-Live compatibility language.
- Rename the compatibility gate to BT100.
- Freeze the BasicTeX release and installer digest.
- Capture the exact installed package manifest.
- Classify the current benchmark corpus.
- Create the BasicTeX-only baseline and X10 budgets.

Exit gate:

- Reference image reproducible.
- Core/extension boundary machine-readable.
- BasicTeX-only denominators frozen.

## Milestone B1 — BasicTeX substrate

Deliverables:

- Immutable BasicTeX image.
- Matching Linux `scheme-small` image.
- Exact Kpathsea integration.
- Exact manifest engines and formats.
- Exact core output pipelines.
- User/project TEXMF overlays.
- Core payload size gate.

Exit gate:

- Package manifest matches the reference.
- No accidental non-core package in the image.
- Existing differential suite passes with exact alias semantics.

## Milestone B2 — BT100 compatibility factory

Deliverables:

- Package ledger.
- Test discovery.
- Package interactions.
- Real-world BasicTeX corpus.
- PDF/DVI/XDV/PS/HTML oracles as applicable.
- Sharded CI.

Exit gate:

- Every core package has a verdict.
- Initial BT100 report has no exclusions.

## Milestone X1 — Supervisor and fork servers

Deliverables:

- Per-user supervisor and authenticated IPC.
- Exact one-shot fallback.
- pdfTeX fork server.
- XeTeX fork server.
- LuaTeX fork server.
- TeX/e-TeX DVI fork server as required.

Exit gate:

- Format-loaded child startup below 2 ms p50.
- Full semantic differential tests pass.
- Crash/cancellation/restart tests pass.

## Milestone X2 — BasicTeX preamble snapshots

Deliverables:

- Semantic begin-document checkpoint.
- Snapshot manifest and key.
- COW child execution.
- Invalidation and eviction.
- Signed common BasicTeX snapshots.

Exit gate:

- Snapshots work across every BT100 package case.
- Zero stale-output failures.
- Tiny edit workload meets X10-E.

## Milestone X3 — Core helper acceleration

Deliverables:

- Generic action broker.
- Exact BibTeX acceleration if present.
- Embedded/exact MakeIndex if present.
- MetaPost/MetaFont adapter.
- `dvips` adapter.
- `tex4ht` adapter.
- Generic shell-escape capture.

Exit gate:

- Every core helper differential passes.
- Every core helper benchmark meets its X10-E budget.

## Milestone X4 — Page checkpoints and replay

Deliverables:

- Engine checkpoint API.
- Dependency mapping.
- Sparse storage.
- Replay and suffix convergence.
- Full-build escalation.

Exit gate:

- Large BasicTeX-native local and structural edits meet X10-E.
- No incorrect page reuse under mutation/fuzz tests.

## Milestone X5 — Incremental output graphs

Deliverables:

- PDF page/resource graph.
- XDV page/resource graph.
- DVI/PS page graph where applicable.
- HTML asset graph.
- Font/image reuse.
- Final output merge and oracle.

Exit gate:

- Unchanged output suffixes do not trigger complete backend conversion.
- All output oracles pass.

## Milestone X6 — Runtime-warm clean acceleration

Deliverables:

- Tokenised BasicTeX file cache.
- Generic snapshot catalogue.
- Engine hot-loop patches.
- Output backend parallelism.
- PGO/architecture qualification.

Exit gate:

- X10-C passes across the BasicTeX clean corpus.
- Patches are upstreamed or have named maintenance owners.

## Milestone R — Simultaneous BT100/X10 release qualification

Deliverables:

- Clean release commit.
- Signed BasicTeX images.
- Multi-platform BT100 report.
- X10-E and X10-C evidence.
- Security, licence, recovery, and size audits.

Exit gate:

- BT100 and X10 pass together.
- Core package manifest has no exclusions.
- Core payload remains within the size gate.
- No hidden setup, stale result, or unmeasured fallback.

---

## 17. CI and evidence

## 17.1 Pull requests

Run:

- Rust/C/C++ unit tests.
- Differential command battery.
- Snapshot mutation suite.
- Deterministic BasicTeX package shard.
- Package interaction smoke set.
- Compact X10-E smoke.
- Release-binary and BasicTeX-image provenance.
- Core payload package/size gate.
- No traced timing path.

## 17.2 Nightly

Run:

- Rotating core package shards.
- Full compact BasicTeX corpus.
- Several real-world core documents.
- Snapshot invalidation mutations.
- Core helper differentials.
- Service restart/cache-corruption tests.
- X10-E gates.

## 17.3 Weekly

Run:

- Complete BasicTeX package ledger.
- Full package interaction matrix or covering array.
- Every core engine and output path.
- Large BasicTeX-native documents.
- X10-C subset.
- Sandbox/security tests.

## 17.4 Release qualification

On macOS arm64, macOS x86-64 where supported, Linux x86-64, and Linux arm64:

- Full BT100 set.
- Full BasicTeX real-world corpus.
- Three independent performance sessions.
- At least 30 paired trials for ordinary cases.
- At least 15 paired trials for expensive cases.
- Same logical BasicTeX package image.
- p50, p95, CPU, RSS, process count, bytes read/written, snapshot/action hit rate.
- Immutable raw evidence.

## 17.5 Evidence rules

- Same binary and BasicTeX image for compatibility and performance.
- Extended-profile packages never enter core aggregates.
- Fallback cells remain in results.
- Service startup and snapshot construction are separately reported.
- No unchanged rebuild is labelled clean compile.
- No core package row disappears between releases.
- Dirty-worktree results are engineering-only.

---

## 18. Security, correctness, and recovery

- Per-build shell-escape sandbox.
- Exact trusted/untrusted policy.
- User-private supervisor socket.
- Content-addressed, digest-verified storage.
- Atomic publication.
- Separate project namespaces.
- Signed release snapshots and BasicTeX image.
- Child-only snapshot mutation.
- Random shadow full builds.
- Automatic exact fallback on uncertainty.
- Corrupt cache entries are deleted and rebuilt.
- Extended-profile overlays are never merged into the signed core image.

Record for reproducibility:

- BasicTeX profile and image digest.
- Platform binary digest.
- Engine and format.
- User/project overlays.
- Snapshot key.
- Helper actions.
- Build time/random policy.
- Platform ABI.

---

## 19. Risk register

| Risk | Impact | Mitigation |
|---|---|---|
| BasicTeX package contents change during the year | Claim drift | Freeze installer and TLPDB revisions per release |
| `scheme-small` differs from macOS BasicTeX | Cross-platform mismatch | Generate exact package closure from the macOS manifest |
| Core image grows toward full TeX Live | Violates product goal | Package-manifest and compressed-size CI gates |
| A user installs extra packages | Ambiguous compatibility claim | Separate extended profile and report overlay identity |
| Engine fork safety | Crash or corrupt state | Single-thread fork point, atfork handling, sanitizers, isolation |
| Preamble side effects | Unsafe snapshot reuse | Resource manifest, conservative invalidation, exact fallback |
| Lua runtime state | Snapshot complexity | Lua-specific adapter and stress tests |
| Page checkpoint state incomplete | Stale output | Strong state digest, replay widening, shadow full builds |
| Incremental PDF/XDV/DVI reuse is wrong | Semantic corruption | Structural, visual, link, font, and tagging oracles |
| Arbitrary shell escape | Security and uncacheable work | Broker, sandbox, dependency capture, exact execution |
| Full clean-build 10× remains unreachable | Missed X10-C | Deep engine patches; publish only X10-E until X10-C passes |
| Optional Biber work consumes core capacity | Delays BT100/X10 | Treat Biber as extension unless manifest proves otherwise |
| Upstream patch burden | Long-lived fork | Small patch series, upstream PRs, named owners |
| Extension tests accidentally enter core report | Misleading evidence | Profile identity enforced by result schema and report generator |

---

## 20. Issue backlog

### Contract and BasicTeX image

- **BT100-001** Add BT100/X10 plan and supersede universal compatibility language.
- **BT100-002** Archive and hash the BasicTeX installer.
- **BT100-003** Generate installed package, file, binary, format, and licence manifests.
- **BT100-004** Build matching Linux `scheme-small` closure.
- **BT100-005** Add package-image equality and compressed-size gates.
- **BT100-006** Add core versus extended profile identities.
- **BT100-007** Implement immutable base plus mutable overlay policy.
- **BT100-008** Integrate exact Kpathsea.
- **BT100-009** Remove implicit engine substitution from explicit aliases.
- **BT100-010** Implement exact core output pipelines.

### Compatibility factory

- **BT100-020** Generate the core package ledger.
- **BT100-021** Discover upstream tests and examples.
- **BT100-022** Add package pair matrix and three-way covering arrays.
- **BT100-023** Build PDF/DVI/XDV/PS/HTML oracles.
- **BT100-024** Build the BasicTeX real-world corpus.
- **BT100-025** Add tagging structure oracle.
- **BT100-026** Add sharded compatibility CI.
- **BT100-027** Generate no-exclusion BT100 report.
- **BT100-028** Classify the existing benchmark corpus by profile.
- **BT100-029** Freeze paired BasicTeX X10 denominators.

### Stateful runtime

- **X10-100** Implement supervisor protocol and private socket.
- **X10-101** Implement exact one-shot BasicTeX fallback.
- **X10-102** Build pdfTeX fork server.
- **X10-103** Build XeTeX fork server.
- **X10-104** Build LuaTeX/LuaHBTeX fork server.
- **X10-105** Build TeX/e-TeX DVI fork server as required.
- **X10-106** Add fork safety, cancellation, and crash tests.
- **X10-110** Add semantic begin-document pause.
- **X10-111** Build snapshot resource manifest.
- **X10-112** Build snapshot key and invalidation.
- **X10-113** Add COW snapshot LRU.
- **X10-114** Add signed generic BasicTeX snapshots.

### Core helpers

- **X10-120** Add generic action broker.
- **X10-121** Add exact BibTeX prefork/in-process path if present.
- **X10-122** Qualify embedded MakeIndex if present.
- **X10-123** Add MetaPost/MetaFont action adapter.
- **X10-124** Add `dvips` adapter.
- **X10-125** Add `tex4ht` adapter.
- **X10-126** Add generic shell-escape dependency capture.
- **X10-127** Add manifest-driven helper discovery.

### Incremental engine and output

- **X10-140** Define complete engine checkpoint state.
- **X10-141** Implement sparse shipout checkpoints.
- **X10-142** Map dependencies to checkpoints.
- **X10-143** Implement forward replay and suffix convergence.
- **X10-144** Add cross-reference convergence records.
- **X10-145** Add speculative replay research.
- **X10-150** Define stable PDF object graph.
- **X10-151** Add XDV page/resource graph.
- **X10-152** Add DVI/PS page graph.
- **X10-153** Add tex4ht HTML asset graph.
- **X10-154** Cache fonts and images.
- **X10-155** Implement output merge oracles.

### Clean-build research

- **X10-160** Add tokenised BasicTeX immutable-file cache.
- **X10-161** Build signed common preamble snapshots.
- **X10-162** Profile engine hot loops.
- **X10-163** Qualify fast convergence equality.
- **X10-164** Add cross-language PGO.
- **X10-165** Add page-parallel XDV conversion.
- **X10-166** Qualify runtime-warm clean X10.

### Optional extension profiles

- **EXT-001** Define extension profile schema.
- **EXT-002** Add exact Biber/biblatex profile if desired.
- **EXT-003** Add Ghostscript/PSTricks profile if desired.
- **EXT-004** Add minted/Pygments profile if desired.
- **EXT-005** Add language collection profiles if desired.

### Release

- **REL-100** Run full BT100 qualification.
- **REL-101** Run X10-E qualification.
- **REL-102** Run X10-C qualification.
- **REL-103** Audit core image size and licensing.
- **REL-104** Audit sandbox, snapshots, and cache security.
- **REL-105** Publish immutable evidence and scoped claim text.

---

## 21. Recommended pull-request order

1. **Contract reset:** add this plan and rename the compatibility gate to BT100.
2. **Reference capture:** archive BasicTeX, generate manifests, and freeze the package closure.
3. **Corpus reclassification:** remove non-core package cases from the core aggregate and generate new paired baselines.
4. **Profile enforcement:** immutable `basictex-2026` image plus separate user extension overlay.
5. **Exact aliases and Kpathsea:** establish BasicTeX semantics before performance work.
6. **BT100 ledger and oracles:** prove the finite compatibility universe.
7. **Supervisor scaffold:** IPC, lifecycle, exact fallback.
8. **pdfTeX fork server:** validate the tiny-document X10 mechanism.
9. **Semantic preamble snapshots:** test every core package.
10. **XeTeX and LuaTeX fork servers:** complete the major engine set.
11. **Core helper broker:** BibTeX, MakeIndex, MetaPost, `dvips`, `tex4ht` as present.
12. **Large BasicTeX document and page checkpoints:** prove body-edit acceleration.
13. **Incremental PDF/XDV/DVI/HTML graphs:** remove full output reruns.
14. **BT100 release report:** 100% core package compatibility.
15. **X10-E qualification.**
16. **Runtime-warm clean research and X10-C qualification.**
17. **Optional extension profiles only after the core gate is stable.**

Every performance PR includes:

- Before/after raw result bundle.
- Stage attribution.
- BT100 correctness result.
- Snapshot/action fallback count.
- Package-image identity.
- Non-overlapping gain ledger entry.
- Revert plan.

---

## 22. Work to stop

Do not spend core programme effort on:

- Building or distributing `scheme-full`.
- Enumerating all CTAN packages.
- Full MacTeX compatibility.
- Biber acceleration unless Biber enters a named extension profile.
- pTeX/upTeX, ConTeXt, Xindy, Asymptote, Pygments, or PythonTeX unless present in the BasicTeX manifest.
- Package allowlists inside the BasicTeX set.
- Source heuristics that change explicit engine semantics.
- More thin-versus-fat LTO work without new evidence.
- Tectonic wrapper tuning on engine-dominated documents.
- Stubs that return success.
- Hidden `tlmgr` package installs.
- Calling an unchanged-output cache hit a clean compile.
- Letting extension-profile results enter the core claim aggregate.

---

## 23. Definitions of done

## 23.1 BT100 done

- Every package in the frozen BasicTeX manifest has a public ledger row.
- Every reference-green package and interaction case passes.
- Every BasicTeX real-world project passes.
- Exact engine aliases and formats are honoured.
- Every core helper works or uses the exact BasicTeX fallback.
- No core package blacklist.
- No core helper stub.
- Logical package image is equivalent on every supported platform.
- Core payload matches the locked manifest and size gate.
- Additional user-installed packages are clearly labelled extended mode.

## 23.2 X10-E done

- Every declared BasicTeX edit scenario is at least 10× faster than its paired reference median.
- p95 is at least 8× faster.
- Fallback and helper time is included.
- No stale output under mutation, fuzz, and shadow-full-build tests.
- Large BasicTeX-native local and structural edits meet their frozen budgets.
- BT100 passes on the same binary and image.

## 23.3 X10-C done

- Every runtime-warm/project-clean BasicTeX corpus cell is at least 10× faster.
- The aggregate is at least 10× faster.
- No project-specific prior state exists.
- Global runtime state is disclosed.
- BT100 passes on the same binary and image.

## 23.4 Final product done

The same release passes BT100, X10-E, and X10-C with immutable evidence, no core package exception, no hidden setup, and no full-TeX-Live dependency.

---

## 24. Immediate next actions

1. Download and archive the exact BasicTeX 2026 installer used as the reference.
2. Install it in a clean VM and capture the complete TLPDB, file, binary, format, and configuration manifests.
3. Build a Linux `scheme-small` image with the same logical package closure.
4. Reclassify the current benchmark corpus; remove Biber/biblatex and other non-core documents from the BT100 aggregate unless the manifest includes them.
5. Add missing BasicTeX engine, DVI/dvips, MetaPost, tex4ht, and tagging cases.
6. Run the first paired BasicTeX reference qualification and freeze all X10 budgets.
7. Add CI that fails when the core image contains a package outside the BasicTeX manifest or exceeds the payload-size gate.
8. Implement the exact pdfTeX format-loaded fork-server prototype.
9. Implement the semantic preamble snapshot and prove it across the complete BasicTeX package ledger.
10. Build the 50–100 page BasicTeX-native stress document and begin page-checkpoint work.

The decisive proof points are now:

- **BT100:** can every package and tool actually shipped by BasicTeX pass without an exception?
- **Footprint:** can tectdist remain close to BasicTeX size and avoid pulling in a larger TeX Live scheme?
- **Tiny:** can an exact pdfTeX snapshot produce a complete PDF within the frozen 10× budget?
- **Major engines:** can pdfTeX, XeTeX, and LuaTeX all use the stateful fast path without changing semantics?
- **Large core document:** can checkpoint replay and incremental output meet X10-E using only BasicTeX packages?
- **Clean build:** can generic BasicTeX formats, token caches, and signed preamble snapshots meet X10-C without project-specific state?

If a proof point fails, target the measured stage. Do not compensate by expanding pre-warmed project state, changing engine semantics, silently installing packages, or weakening the compatibility gate.

---

## 25. Reference basis

The scope terminology in this plan follows the TeX Users Group documentation:

- MacTeX’s official BasicTeX 2026 listing describes BasicTeX as a much smaller distribution containing the standard TeX tools, including TeX, LaTeX, pdfTeX, MetaFont, dvips, MetaPost, XeTeX, and LuaTeX: <https://www.tug.org/mactex/currentpackages-tug.html>
- The TeX Live 2026 guide describes the `small` scheme as the cross-platform equivalent of BasicTeX: <https://www.tug.org/texlive/doc/texlive-en/texlive-en.html>
- MacTeX’s 2026 feature notes state that BasicTeX includes the three principal engines, core tagging packages, development formats, and tex4ht: <https://www.tug.org/mactex/newfeatures.html>
- TeX Live Manager remains the package-management mechanism, but packages installed after the locked BasicTeX image are intentionally treated as extension overlays in this plan: <https://www.tug.org/texlive/tlmgr.html>
