# Changelog

All notable changes to tectdist are documented here.  The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
`VERSION` lives in `src/tectdist/version.py`.

## [0.2.0] - 2026-08-08

Packaging rework: biber is now BUILT FROM SOURCE inside the Homebrew formula
(the plk/biber v2.17 source plus 119 sha256-pinned CPAN module resources,
mirroring homebrew-core's own biber formula) instead of prebuilt binaries —
no binary bundling, no linux/arm64 stub (a real biber 2.17 on all four
platforms), and no install-time tectonic pin.  The tectonic↔biblatex↔biber
pairing is DECLARED in `src/tectdist/pairing.py` (mirrored by the formula's
`TECTONIC_VERSION`, guarded equal by a battery release gate) and enforced at
RUNTIME: every `tectdist` invocation compares the actual tectonic against the
declaration and fails fast with instructions when brew's tectonic moves
(`tectdist doctor` prints the full report).  New deps: perl, libxml2, libxslt,
openssl@3, pkgconf.  The weekly pairing watcher now reads the declared pairing
and also checks the formula mirrors it.  First installs build biber from
source (~10-20 minutes); tap bottles are a documented follow-up.

## [0.1.0] - 2026-08-08

First release: the complete Tectonic-backed TeX distribution.

### Changed

- **Full rewrite in Python 3 (stdlib-only, ≥ 3.9).**  The former bash
  dispatcher is gone.  All logic now lives in the `src/tectdist` package
  (`dispatcher.py`, `flags.py`, `latexmk.py`, `tools.py`, `version.py`);
  `bin/tectdist` is a thin launcher and the symlink farm is unchanged, so
  bare `pdflatex`, `latexmk`, `kpsewhich`, … keep working drop-in.
- **Project renamed from `texdist` to `tectdist`.**  The package is
  `src/tectdist/`, the launcher is `bin/tectdist` (the symlink farm points
  at it), the Homebrew formula is `Formula/tectdist.rb` (class `Tectdist`),
  and all `--version` output reports `tectdist 0.1.0`.  Behaviour is
  unchanged — this is a rename only.
- **Compilable single-file executable.**  `python3 build.py` produces
  `dist/tectdist`, a self-contained zipapp that behaves identically to the
  source tree (same dispatch, same `--version`, same farm semantics).
- **Tooling is Python now.**  `make-links.sh`/`install.sh` are replaced by
  `make_links.py`/`install.py`, and a new `uninstall.py` cleanly removes the
  PATH entry.  No bash remains in the repository.
- **Homebrew formula** (`Formula/tectdist.rb`): tap-ready, declares
  `tectonic`, `ghostscript`, `poppler` and `qpdf` as dependencies, installs
  the zipapp plus the tool farm without shadowing the dependency binaries,
  and now also bundles `biber` 2.17 as a real binary resource (below).

### Changed

- **biblatex works out of the box — `biber` 2.17 is bundled.**  The formula
  installs the official prebuilt biber 2.17 binary as a bundled resource,
  self-hosted as a sha256-pinned release asset (users only ever download
  from github.com, never from SourceForge).  `bin/biber` is the real
  binary, matched to the biblatex 3.17 that Tectonic 0.17 bundles (bcf
  3.8); the farm no longer symlinks it.  On linux/arm64 (no official biber
  2.17 binary exists) the formula installs an explanatory stub instead:
  biblatex compiles but the bibliography stays empty and citations print
  raw keys, with a clear notice.
- **Each release requires a specific tectonic version (pairing).**  The
  formula declares `TECTONIC_VERSION` (0.17) and asserts brew's tectonic
  against it at install time, failing fast with instructions if brew's
  tectonic has moved — a mismatched pair can never be installed silently.
  A weekly GitHub Actions watcher (`.github/workflows/check-tectonic.yml`)
  opens an issue the moment brew's tectonic changes so the matched release
  is cut before users hit a mismatch on `brew upgrade`.
- **python@3.12 → python@3.14** as the zipapp interpreter (current core
  default).

### Added

- **Deterministic source tarball release asset** (`tectdist-0.1.0.tar.gz`,
  `git archive | gzip -n`) alongside the two biber binary assets; the
  formula's sha256 is taken from the Homebrew mirror via `brew fetch`.

- **`makeindex`/`xindy`/`upmendex` proxy to the real system binary.**  When
  a real binary of the same name is installed (TeX Live, MacTeX, MiKTeX,
  homebrew) the farm forwards to it with the same argv, exactly like the
  poppler/qpdf proxies — the farm never shadows a real tool even when it
  comes first on PATH.  When the binary is absent the command stays an
  honest exit-0 note.  (`biber` used to be proxied the same way; since this
  release the Homebrew formula ships the real matched binary itself — see
  "Changed" above — while non-Homebrew installs keep the proxy/stub
  behaviour.)
- **makeindex rerun loop.**  Tectonic itself never runs `makeindex` (it only
  writes `.idx` files), so the engine dispatcher now performs the step: after
  a compile that produced `.idx` files it runs a real `makeindex` binary
  (found on PATH) on each and re-runs Tectonic once, so `\printindex` output
  is actually included in the PDF.  If no `makeindex` is installed the
  compile still succeeds but prints an honest warning and no index is built.
  The loop now also falls back to `upmendex` (a drop-in-compatible
  replacement) before warning.
- **Acceptance battery** (`tests/battery.py`): a parallel, time-bounded,
  stdlib-only suite with two tiers — `[mock]` checks against a recording
  fake engine (exit codes *and* exact engine argv, no TeX needed) and
  `[real]` end-to-end checks (real compiles, real gs/poppler tools).  Each
  case runs in an isolated scratch directory; `--jobs N` and `--mock-only`
  are supported; without `tectonic` the real sections report `SKIPPED`.
  292 checks, all green with the real engine in under ~15 s.
- **Versioning:** a single `VERSION` constant reported by
  `tectdist --version` and `latexmk --version`.
- **Benchmark suite + uv dev environment:** a pytest-benchmark suite
  (`benchmarks/`, results in `BENCHMARKS.md`) run entirely through uv
  (`pyproject.toml`, `uv.lock`, `.python-version`) — dev-only, the runtime
  stays stdlib-only; shim-overhead optimised via lazy imports, lazy proxy
  globs and a deflated zipapp (startup −39%, artifact −57%, stub −46%).
  `tests/check_purity.py` audits the built zipapp for third-party imports.
- **"Using with TeXifier" section in the README**: how to point TeXifier at
  the farm (Preferences → Distribution → Set Custom Distribution, per the
  official TeXifier docs), including the XeTeX-engine caveat.
- **AGPL-3.0 `LICENSE`**, `CONTRIBUTING.md`, this changelog, and a rewritten
  `README.md`.

### Fixed

- Formula: `tectdist` launcher is now symlinked into `bin/`, the `brew test`
  farm-count assertion matches reality (62), and `tests/check_formula.py`
  keeps the formula farm in sync with `flags.py`.
- `latexmk -c/-C` now cleans only the output directory when `-outdir` is set
  (no more deleting `stem.*` files from the working directory).
- `-auxdir` (TeXShop-style) is translated like `-aux-directory`.
- `-jobname` values containing path separators are sanitized to their
  basename — artifacts can no longer be renamed outside the output dir
  (also true for `latexmk` clean modes).
- `-fmt`/`-format` values other than `latex` warn and are dropped instead of
  making Tectonic try to generate a nonexistent format.
- `kpsewhich -var-value` answers only for known TeX variables; arbitrary
  environment variables are refused (exit 1) instead of being echoed.
- `pdfcrop --margins` rejects non-numeric values gracefully (no traceback).
- The dispatcher no longer swallows a following flag as a pending flag's
  value (`-synctex -shell-escape` keeps both behaviors correct).
- `latexmk` resolves extensionless inputs (`latexmk -pdf doc` → `doc.tex`)
  and honors an explicit `-r FILE` even with `-norc`.
- `-interaction batchmode` (space form) silences like the `=` form.
- `tlmgr` action commands (install/update/…) now exit non-zero instead of
  pretending success.
- Empty `TEXINPUTS` components (trailing `:`) map to the current directory.
- `build.py` excludes dotfiles (`.DS_Store`) from the zipapp; stale pre-rename
  artifacts removed from `dist/`.
- `install.py` escapes the repo path in the `export PATH` line it writes;
  `uninstall.py` is byte-preserving (no non-UTF-8 corruption) and atomic.
- **README Limitations corrected.**  The claims that `-draftmode` is
  "warnings only" (it is silently ignored; `-output-format=dvi` warns) and
  that `makeindex`/`dvips` runs are "performed internally by Tectonic" (only
  the bibliography is; there is no DVI pipeline at all, and Tectonic never
  runs makeindex) are gone.  `biber` is documented as proxied to the real
  binary and working through Tectonic's native flow (with the version-
  matching caveat), not unsupported.
- Stub messages for `makeindex`/`xindy`/`upmendex`/`biber` no longer claim
  the step is performed inside the Tectonic compile; when no real binary is
  installed they exit 0 with an honest note naming the real tool (and, for
  `biber`, the empty-bibliography consequence) so pipelines keep running.
- `latexmk` now finds its engines through the *invoked* path (matching the
  old `dirname "$0"` behaviour), with a PATH fallback when the farm is not
  in the same directory — so the built artifact works from any layout.
- The poppler/qpdf proxies no longer recurse into themselves when a tectdist
  farm shadows the real binaries; they also fall back to Homebrew `opt`
  directories.

### Removed

- `tests/battery.sh`, `make-links.sh`, `install.sh` (superseded by the
  Python equivalents above).
- Generated benchmark snapshots (`benchmarks/*.json`, gitignored; they
  contain machine-specific info) and the internal review doc (`REDTEAM.md`,
  purged from git history).

[0.1.0]: https://github.com/tmonk/tectdist/releases/tag/v0.1.0
