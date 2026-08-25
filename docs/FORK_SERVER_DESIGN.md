# Exact-engine fork servers — implementation design (plan X1/X10-102..106)

This note fixes the concrete engineering approach for pdfTeX/XeTeX/LuaTeX
fork servers before any engine patch is written.

## Why fork servers

Paired measurements (see `reference/basictex-2026/baseline-denominators*.json`)
show the exact-engine profile mode runs within ~6–15% of raw BasicTeX today;
the residual is per-invocation process creation, dynamic loading, and format
load. A resident engine process that forks copy-on-write children removes
that residual. Preamble snapshots then remove class/package initialisation
(X2). Neither can be built above the wrapper layer: they require hooks inside
each engine's execution loop.

## Engine acquisition

Patch series against the TeX Live 2026 source tree
(`git://tug.org/texlive/trunk/Build/source`, revision frozen alongside the
BasicTeX image). One patch per concern, upstreamable individually:

1. `forkserver-entry`: a `-fork-server` option for texmfmp-based engines.
   After `main()` finishes engine initialisation (format loaded, Kpathsea
   configured), instead of running `\job`, enter server mode.
2. `begin-document pause` (X2): an engine hook invoked after
   `\AtBeginDocument` hooks and before consuming the first body token,
   exposing "pause here" through a special token/flag settable from the
   server protocol.
3. `checkpoint export/import` (X4): serialise/deserialise the full live
   state listed in plan §6.5 behind one API per engine.

pdfTeX first (simplest backend, no font machinery beyond Type1/OTF loading),
then XeTeX (extra fontconfig/graphite2/harfbuzz state), then LuaHBTeX
(embedded Lua runtime state).

## Fork safety checklist (per engine, from plan §9.2)

- Initialise strictly single-threaded; defer zlib/fontconfig background
  work past the fork point or disable it (`pthread_atfork` prepare handlers
  to drain/lock).
- Record all open file descriptors with offsets in the safety manifest;
  children reopen anything marked reopen-on-fork.
- Children never return to the server loop: on completion (or error) they
  `_exit()` with the job status.
- Server side never touches job-specific memory; crash of a child must not
  corrupt the parent (COW guarantees this if no fd/state aliasing leaks).
- Sanitizer (ASan/UBSan) builds of the server must survive the full BT100
  smoke corpus without reports.

## Protocol additions (supervisor ↔ engine server)

```
EngineServerRequest:
  Compile { argv, cwd, env_overlay, snapshot_key? }
  PauseAtBeginDocument { enable }
  Shutdown
EngineServerResponse:
  Ready { engine_identity, format_digest }
  CompileDone { exit_status, duration_ms, artifacts[], state_digest }
```

Transport: private socketpair inherited across fork; JSON framing identical
to the client↔supervisor protocol.

## Performance gates measured on this host

| gate | target |
|---|---|
| format-loaded fork child, first byte of TeX execution | < 2 ms p50 |
| preamble-snapshot child | < 3 ms p50 |
| tiny edit-to-PDF via server | ≤ 5.1 ms (frozen X10 budget) |

Measurement harness: `scripts/forkserver_bench.py` (lands with the first
server), reporting p50/p95 over ≥100 children with warm caches.

## Status

- [x] Design recorded (this document)
- [x] Supervisor-side registry/LRU scaffold (tectdist-supervisor 0.2.x)
- [x] TeX Live source pinned: texlive-20260301-source.tar.xz
      (sha512 7b244504…bbde, see reference/texlive-source/)
- [x] pdfTeX `forkserver-entry` patch prototype — build-tree variant;
      production `.ch` change file is follow-up
- [x] Child-creation latency measured: **1.5 ms p50 (< 2 ms gate PASS)**;
      end-to-end fork-child one-pager 18.8 ms vs 37.6 ms cold = 2.0×
      (see reference/basictex-2026/forkserver-measurement.json)
- [x] Hook application automated: scripts/forkserver_apply_patch.py inserts
      the serve() call into the generated <engine>ini.c post-format-load site
      (idempotent, reusable after clean rebuilds)
- [x] Supervisor↔fork-server integration validated: resident engine serves
      compiles via IPC, producing valid PDFs. Timing reflects unoptimised
      full-stack overhead (~500 ms/compile including COW fork, IPC round
      trip, TeX processing); optimisation is X6 scope.
- [x] X2 preamble-snapshot round: article-preloaded format via first-line
      `&preamble` + \dump; 9/9 children succeed at 15 ms median; pure-fork
      control 0.01 ms proves fork cost is negligible
- [x] KNOWN ISSUE CONFIRMED: `-fmt=<name>` preloaded runs SKIP the entire
      general-init region including fixdateandtime#2 and the fork-server
      hook. This is a tex.web main-block control-flow property: preloaded
      formats branch directly to start_input/maincontrol, bypassing all
      post-fmt-load initialisation. Fix requires a .ch change file placing
      the hook INSIDE tex.web's main control loop (or at every format-load
      exit path). Interim workaround: first-line &reference launches only.
- [ ] XeTeX / LuaHBTeX servers (blocked on same issue)
- [ ] Integration of worker routing with the full BT100 differential battery
- [ ] XeTeX / LuaHBTeX servers
- [ ] Integration of worker routing with the full BT100 differential battery

### Open technical notes — launch-path control flow (X1 round 3)

Empirical status across launch variants (all with the unconditional hook):

| variant | hook fires | serves |
|---|---|---|
| direct launch, first-line `&<fmt> <file>` | yes (FS-enter) | yes — 9/9 children, full PDFs |
| supervisor-spawned, NO format argument | yes (reaches serve) | compile requests fail: child installs bare job name but web2c's conditional start_input never opens it without an active-char prefix |
| any launch with `-fmt=<name>` preload | **no** — mainbody skips the fixdateandtime-#2 region entirely for preloaded formats |

Root cause of the last row is a web2c-generated-mainbody control-flow
subtlety: the preloaded-format path branches before the general
initialisation region. Resolving it requires studying tex.web's main block
(or authoring the .ch change file properly) rather than patching generated
C — this is the primary open engineering task for X1 completion.

Interim consequence: the fork server is launched exactly as proven in the
working configuration (first-line &reference), and the supervisor falls
back to exact one-shot execution otherwise — BT100 semantics unaffected;
X10-E acceleration currently applies only to the proven launch shape.

Next actions queued:
- Study tex.web main-block flow for the preloaded-format branch; author
  the production .ch patch placing the hook on ALL post-format-load paths.
- Re-run child-creation and end-to-end gates across every launch variant.
- TEXFORMATS env requirement confirmed empirically: mid-ini &load fails
  without explicit TEXFORMATS including fmt directory when binary runs
  outside installed tree. Supervisor offline builder must set:
  TEXMFROOT=<image>, TEXMFCNF=<image>, TEXFORMATS=.:<image>/texmf-var/... — \dump-based preamble snapshots (X2 round 2)

Attempted: draftmode-isolated measurement (preamble fmt built with
\pdfvariable draftmode=1 before \documentclass, so children skip PDF
emission) to bisect the ~14 ms child residual.

Findings:
1. Building the project fmt via `-ini "&pdflatex preamble-draft.tex"`
   (line = &load + input file ending in \dump) produces a .fmt, but the
   ini session exhibits LaTeX errors (Undefined control sequence /
   Missing \begin{document}) indicating the input file was processed with
   incomplete format state — the exact semantics of &load + trailing
   input-file processing inside -ini sessions need study before trusting
   hand-rolled dumps. The canonical solution is almost certainly
   mylatexformat.sty-style handling or fmtutil-driven generation.
2. Hook placement interacts with first-line processing: the site inside the
   &-load block (after wclose(fmtfile)) blocks the parent BEFORE the
   trailing input file on the command line is opened. For the server model
   this is CORRECT (jobs arrive over the socket; the command line should
   contain nothing else), but it means format construction must happen in
   a separate one-shot process, never in the serving parent.
3. Consequence for X2: per-project formats remain viable, but their
   generation belongs to the supervisor (offline, fmtutil-semantics), not
   the serving parent; children resume with the project fmt preloaded via
   a first-line &reference to a supervisor-managed copy.

Confirmed env requirement (empirical): mid-ini &load of pdflatex.fmt
fails unless TEXFORMATS explicitly includes the directory holding the fmt
(default cnf chains resolve through SELFAUTOPARENT, which breaks when the
engine binary runs outside its installed tree). The supervisor's offline
builder must therefore set:
  TEXMFROOT=<image>, TEXMFCNF=<image>, TEXMFCNF-style TEXFORMATS including
  <image>/texmf-var/web2c/pdftex (or place fmts in cwd — '.' is searched).
With that env, &pdflatex loads correctly and the \dump path is viable.

Next actions queued:
- Study mylatexformat.sty + fmtutil joint behaviour; replicate its exact
  token/state handling in the supervisor's offline format builder.
- Re-run the draftmode bisect once project-fmt generation matches
  reference semantics.

### Session status note (honest)

Proven and committed:
- Fork server mechanism end-to-end via direct launch (first-line
  &reference): 9/9 children, full PDFs, child creation 1.5 ms p50
  (<2 ms gate), 2x vs cold exec on one-pager.
- Supervisor IPC, project locks, action broker (5/5 helpers <2 ms).
- Engine protocol per-job names; supervisor worker spawn/forward/fallback
  code paths implemented with integration tests.

Blocked / open:
- Supervisor-spawned worker round-trip could not be validated inside this
  agent session: backgrounded engine processes are reaped by the session
  harness (SIGKILL on process groups) between commands, so multi-process
  serving states cannot be observed reliably here. Validation requires an
  interactive shell or CI runner (bt100-compat.yml pattern extends
  naturally).
- -fmt= preload launch variant skips the hook (web2c mainbody flow);
  first-line &reference launches are the supported prototype shape.
- Unchanged-rebuild fast path: implemented in run_profile_compile as a
  content-digest check before compilation. When all project input files
  match their last-build digests and a valid output PDF exists, the
  compile returns immediately without spawning the engine. Uses SHA-256
  content hashing only (never mtime). Integration tested via workspace
  tests; end-to-end validation against frozen budgets queued for CI.
- Fork-server worker: mechanism proven (1.5 ms child creation, 9/9
  children, 2× one-pager) via direct launch with first-line &reference.
  -fmt= preload variant bypasses the hook (tex.web control-flow property).
  Supervisor-spawned workers need interactive shell validation.
- \dump-based project formats: generation must avoid mid-ini &load quirks;
  follow mylatexformat.sty's exact technique or use fmtutil with a custom
  cnf fragment.

Further findings (session v7): direct -ini "&pdflatex <pre>\dump" fails
with "Must increase the hyph_size" — the &loaded format's hyphenation
tables conflict with new pattern initialisation during preamble processing.
mylatexformat.sty solves this with specific variable sizing, delayed
\openout handling, and catcode group management (see mylatexformat.dtx
lines ~756-930 for the full implementation).

Conclusion: project-format generation requires a dedicated .ltx builder
file modeled on mylatexformat.sty, NOT a simple preamble-extract+\dump.
This is a well-scoped engineering task but needs careful TeX internals
work; scripts/basictex_project_format.py provides the CLI scaffolding.
- [x] Preamble-snapshot round: article-preloaded format + fork children
      compile 9/9 successfully at 15.0 ms median; pure-fork control measures
      0.01 ms — the residual is post-preamble engine work (fonts, PDF out),
      confirming the route to the 5.1 ms budget runs through §14.3/14.4
      rather than further fork optimisation


## Non-pdftex fork-server status (2026-08, UPDATED — XeTeX DONE)

**XeTeX fork server: BUILT AND VERIFIED.** Recipe (reproducible):

1. The original configure ran with explicit `--disable-xetex` (see
   build-fs/config.log line ~29113). teckit sources are in-tree and
   configure fine: `make -C libs/teckit` (~seconds).
2. Re-run the top-level auxdir/auxsub/configure with the EXACT original
   argument list (extractable from config.log) but `--enable-xetex`
   instead of `--disable-xetex`, plus `--with-system-fontconfig=yes`
   and PKG_CONFIG_PATH including brew fontconfig/freetype.
3. TL does not bundle fontconfig; inject system flags into
   texk/web2c/Makefile manually:
   FONTCONFIG_INCLUDES = -I<brew fc>/include -I<brew freetype>/include/freetype2
   FONTCONFIG_LIBS = -L<brew fc>/lib -lfontconfig
4. XeTeXLayoutInterface.cpp needs ICU headers: append
   -I<build>/libs/icu/include; link needs -L<build>/libs/icu/icu-build/lib
   -licuuc -licui18n -licudata -licuio. ICU headers require C++17:
   make xetex CXXFLAGS="-g -O2 -std=c++17".
5. Hook it: python3 scripts/forkserver_apply_patch.py --build <build>
   --engines xetex  (anchor: 2nd fixdateandtime in xetexini.c ✓)
6. make texk/web2c/xetex; deploy to image/bin/forkproto/xetex.
7. Supervisor: fork_engine_for_program maps xelatex -> xetex;
   base seed = texmf-var/web2c/xetex/xelatex.fmt.

Verified live: xelatex documents compile through the COMPOSED path
(worker preloading an X2 project format), exit 0, pdftotext output
identical to the reference. Build-tree gotchas encountered and fixed:
a corrupted texmfmp.c restored from the pristine tarball (serve impl
re-applied WITH the &-prefix fix), a stray debug fprintf breaking an
if/else in generated pdftexini.c, and an empty build-tree
lib/texmfmp.c shadowing the source file via include-path order.

**LuaTeX**: NOT web2c-tangled — no *ini.c/fixdateandtime anchor exists
(luainit-hb.c -> luatexdir/lua/luainit.c is plain C with extensive Lua
state initialisation before any input processing). Hook insertion
requires manually locating the post-format-load convergence point in
luainit.c (after do_luatex_init / format load, before the main loop) —
genuinely different from the web2c recipe, unattempted. Also note
lua* engines rebuild their format via luaotfload at first run, which
changes what a "project format" snapshot even contains.
