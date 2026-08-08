# tectdist — a standard-TeX-compatible distribution backed by Tectonic

`tectdist` is a drop-in replacement for a stock TeX Live installation, backed by
[Tectonic](https://tectonic-typesetting.github.io). Editors, `latexmk`-driven
build systems, and CI scripts that call `pdflatex`, `latexmk`, `bibtex`,
`kpsewhich`, … with the classic web2c flag vocabulary work against it
unchanged — no TeX Live needed.

Everything is a single-file Python 3 executable (a zipapp built from the
`src/tectdist` package) plus a symlink farm: every TeX tool name points at it,
and the dispatcher switches on the invoked name.

## Requirements

**Runtime** (the engine and the real-tool backends):

| Tool | Needed for | Notes |
|---|---|---|
| `tectonic` | every compile | required; found via `TECTONIC`, `PATH`, else `/opt/homebrew/bin/tectonic` |
| `ghostscript` (`gs`) | `epstopdf`, `eps2eps`, `ps2pdf`, `pdfcrop` | |
| `poppler` tools | `pdfinfo`, `pdftotext`, `pdfunite`, `pdfimages`, `pdfseparate`, `pdftocairo`, `pdftoppm`, `pdftops` | passed through to the real binaries |
| `qpdf` | `qpdf` | passed through |

**Testing** additionally needs a Python 3 interpreter (≥ 3.9, stdlib only) —
macOS's stock `/usr/bin/python3` works.

## Install

### Homebrew (recommended)

Tap the repository and install:

```sh
brew tap tmonk/tectdist
brew install tmonk/tectdist/tectdist
```

The formula installs the built zipapp plus the full tool farm, declares
`tectonic`, `ghostscript`, `poppler` and `qpdf` as dependencies, and needs no
`--overwrite` against those formulae.  If another TeX installation already
provides some farm names, run `brew link --overwrite tectdist`.

### From the repository

```sh
python3 build.py            # optional: build dist/tectdist, the release artifact
python3 make_links.py       # (re)build the bin/ symlink farm, idempotent
python3 install.py          # add bin/ to PATH in ~/.zshrc (idempotent)
python3 install.py ~/.bashrc  # or any rc file
```

`uninstall.py` removes the PATH entry (from `~/.zshrc`, `~/.bashrc` and
`~/.bash_profile`, or a file given as an argument):

```sh
python3 uninstall.py
```

## Usage

```sh
pdflatex -interaction=nonstopmode -synctex=1 main.tex     # like TeX Live
latexmk -pdf -synctex=1 -outdir=build main.tex            # build driver
kpsewhich -var-value TEXINPUTS                            # file lookup
```

If `TECTONIC` is set, its value is used as the engine binary (default:
`tectonic` found on PATH, else `/opt/homebrew/bin/tectonic`).

## Using with TeXifier

[TeXifier](https://www.texifier.com) (macOS LaTeX editor) is the reason
tectdist exists: it wants a TeX distribution — a directory containing the
classic binaries — and tectdist provides exactly that, without a
multi-gigabyte TeX Live install.

1. **Install tectdist** (either way works):
   - *Source checkout:* `python3 make_links.py` (and optionally
     `python3 install.py` to add `bin/` to PATH — not required for
     TeXifier).
   - *Homebrew:* `brew tap tmonk/tectdist && brew install tmonk/tectdist/tectdist` —
     the farm lands in `/opt/homebrew/bin` (Apple Silicon) or
     `/usr/local/bin`.
2. **Point TeXifier at the farm.**  Open Preferences (`Cmd-,`) → the
   **Distribution** pane.  If the farm directory is not already listed
   under *Installed LaTeX distributions*, click **Set Custom Distribution**
   and select the tectdist `bin/` directory — in TeXifier's words, "the
   directory where LaTeX binaries may be found".
3. **Check the health check.**  TeXifier verifies that the binaries it
   needs for typesetting are present in the selected distribution.  The
   farm provides the engine names (`pdflatex`, `latex`, `xelatex`,
   `lualatex`, …) plus `latexmk`, `kpsewhich`, `epstopdf`, `pdfcrop` and
   the maintenance stubs, so the health check passes.
4. **Typeset as usual.**  TeXifier invokes `pdflatex` (or whichever engine
   you select) from the farm; it compiles with Tectonic and produces a PDF
   in the document directory.

Notes and caveats:

- **The engine is Tectonic (XeTeX-based).**  tectdist translates the web2c
  command-line interface, but the underlying engine is Tectonic's — not
  pdfTeX's.  Documents that depend on pdfTeX-specific engine behaviour may
  typeset differently; see [Limitations](#limitations).
- **First compile needs the network**: Tectonic downloads its support-file
  bundle on first use and caches it (`~/.cache/Tectonic`).
- **No PATH needed for TeXifier**: the Distribution pane uses the selected
  directory's binaries by path; `python3 install.py` is only for
  command-line use in a terminal.
- Homebrew installs live in a standard location, so a newer TeXifier may
  list the farm under *Installed LaTeX distributions* directly — then you
  can just select it instead of using *Set Custom Distribution*.

## Layout

```
tectdist/
├── bin/
│   ├── tectdist          # thin launcher: python3 + the package from ../src
│   └── <73 symlinks>    # pdflatex, latexmk, bibtex, kpsewhich, tlmgr, ...
├── src/tectdist/         # the package (single source of truth)
│   ├── dispatcher.py    # argv[0] dispatch + web2c→Tectonic translation
│   ├── flags.py         # the tool farm + flag vocabulary tables
│   ├── latexmk.py       # latexmk-compatible build driver
│   ├── tools.py         # proxies, Ghostscript tools, stubs, kpsewhich
│   └── version.py       # VERSION
├── Formula/tectdist.rb   # tap-ready Homebrew formula
├── build.py             # dist/tectdist: one self-contained executable
├── make_links.py        # regenerate the symlink farm (idempotent)
├── install.py           # add bin/ to PATH (idempotent, any rc file)
├── uninstall.py         # remove the PATH entry
└── tests/battery.py     # the acceptance battery (Python 3, stdlib only)
```

## What each name does

| Group | Names | Behaviour |
|---|---|---|
| Engines | `pdflatex latex xelatex lualatex platex uplatex pdftex tex etex luatex luahbtex dvilualatex dviluatex xetex pdfetex` | compile via Tectonic; accept the full web2c flag vocabulary |
| Build driver | `latexmk` | classic interface (`-pdf`, `-outdir`, `-c/-C`, `.latexmkrc`, …) over the engine farm |
| Stubs | `bibtex`, `biber makeindex xindy upmendex`, `dvips dvipdfm dvipdfmx xdvipdfmx dvitype dvicopy …`, `mktexlsr texhash mktexfmt fmtutil updmap tlmgr texconfig texdoc`, `tftopl pltotf vftovp gftopk …`, `mf mpost context …` | exit 0 with a note when the real binary isn't installed — `biber`/`makeindex`/`xindy`/`upmendex` proxy to the real system binary when present; `bibtex` runs inside the Tectonic compile (built-in BiBTeX) |
| Real tools | `epstopdf ps2pdf eps2eps pdfcrop` | implemented on Ghostscript (`gs`) |
| Proxies | `pdfinfo pdftotext pdftoppm pdftocairo pdfunite pdfseparate pdftops pdfimages qpdf` | forwarded to the real system binary (poppler/qpdf) |
| Lookup | `kpsewhich` | file lookup, `-var-value`, `-format=`, TEXINPUTS/BIBINPUTS/BSTINPUTS search |

## Flag handling (engines)

- **Translated:** `-synctex=N`, `-output-directory` / `-outdir` / `-aux-directory` /
  `-auxdir` (auto-created), `-jobname` (renames `.pdf` / `.synctex.gz`, incl.
  stdin's `texput`; a path-like jobname is sanitized to its basename so
  artifacts can't escape the output dir), `-shell-escape` / `-enable-write18`
  (→ `-Z shell-escape`), `-include-directory` / `-I` (MiKTeX), `-fmt` /
  `-format` (only `latex` is supported; other values warn and are dropped),
  `-q` / `-quiet` / `-silent`, `-interaction=batchmode` (silence),
  `TEXINPUTS`, `BIBINPUTS`, `BSTINPUTS`, `INDEXSTYLE` (→ search paths; an
  empty `:` component means the current directory).
- **Ignored (no Tectonic equivalent):** `-interaction`, `-file-line-error`,
  `-halt-on-error`, `-recorder`, `-draftmode`, `-8bit`, `-etex`, `-dvi`,
  memory knobs, `-cnf-line`, `-progname`, `-parse-first-line`,
  `-translate-file`, `-src-specials`, `-ipc`, installer/engine-selector
  switches, … (`-output-format=dvi` warns and still produces PDF;
  `-draftmode` is silently ignored).
- **Pass-through:** everything else reaches Tectonic untouched (`-C`, `-b`,
  `-f`, `-r`, `-k`, `-p`, `--chatter`, `--color`, `-Z...`, `--untrusted`,
  `--makefile-rules`, `--`, …).

Standard semantics are preserved: output goes to the **current directory**
unless `-output-directory` is given (not the input's directory), extensionless
input `main` resolves to `main.tex`, exit status is 0/non-zero as expected,
`--version`/`--help` work on every name.

## Testing

The acceptance battery is a single, parallel, time-bounded Python 3 script
(stdlib only).  It is the equivalence oracle for the whole distribution:

```sh
python3 tests/battery.py              # everything that can run
python3 tests/battery.py --mock-only  # skip the [real] engine sections
python3 tests/battery.py --jobs 4     # worker count (default: min(8, cpus))
```

Two tiers:

- **`[mock]`** — flag vocabulary, translation and dispatcher mechanics,
  checked against a *recording fake engine* (via the `TECTONIC` override).
  These assert both the exit code **and the exact engine argv**, take
  milliseconds, and need no TeX engine at all.
- **`[real]`** — end-to-end behaviour with a real Tectonic engine and real
  `gs`/poppler tools: compile→PDF, `-jobname`/`-output-directory`/`-synctex`
  artifacts, TEXINPUTS search, error exit codes, the latexmk driver, and the
  document tools.

Every case runs in its own isolated scratch directory; every subprocess is
time-bounded, so the suite can never hang.  Without `tectonic` installed the
mock tier still runs and the real sections report `SKIPPED` (never failed).
Exit status is 0 iff no check failed.

### Benchmarking (dev-only, uv)

Performance is tracked by a pytest-benchmark suite under the uv-managed dev
environment.  This toolchain is **dev-only**: the battery, the installers and
the built artifact run on a stock `python3` with no uv and no site-packages.

```sh
uv sync                                       # one-time: .venv + dev deps
uv run pytest benchmarks/                     # full suite incl. purity audit
uv run pytest benchmarks/ --benchmark-only    # benchmarks only (faster)
uv run pytest benchmarks/ --benchmark-json=benchmarks/latest.json  # save results
TECTDIST_BENCH_SAMPLES=3 uv run pytest benchmarks/ --benchmark-only  # quick run
```

Cases cover shim startup (warm/cold/artifact/stub), flag translation,
proxy resolution, kpsewhich lookup, and end-to-end (real compile, latexmk,
full battery).  Results are reported as median/p50/p95 over repeated samples;
the before/after table lives in [BENCHMARKS.md](BENCHMARKS.md) with
`benchmarks/baseline.json` (pre-optimisation) and `benchmarks/after.json`
as the paired record.  The suite also re-checks that the built zipapp stays
stdlib-only (`tests/check_purity.py`).

## Versioning

`VERSION` lives in `src/tectdist/version.py` — the single source of truth.
It is reported by:

```sh
tectdist --version       # tectdist 0.1.0 (Tectonic-backed TeX distribution)
latexmk --version       # latexmk (tectdist) 0.1.0 — Tectonic-backed build driver
```

`pdflatex --version` deliberately reports the *engine* version (Tectonic), like
a stock `pdflatex` reports the underlying TeX system.  The version also
appears in `build.py`'s output, the Homebrew formula, and the CHANGELOG.

## Limitations

- One engine exists (Tectonic's XeTeX-based LaTeX engine): `xelatex`/
  `lualatex`/`platex`/`pdftex`/… accept the classic flag vocabulary, but every
  name compiles with the same Tectonic engine.  Documents that rely on
  engine-specific behaviour (LuaTeX `\directlua`/`luacode`, pdfTeX
  primitives, pTeX macro conventions) may fail or typeset differently.
- The bibliography for classic `\bibliography` documents is processed inside
  the Tectonic compile (Tectonic's built-in BiBTeX); a standalone `bibtex`
  call is a no-op stub that writes no `.bbl`.
- `biber` is **proxied to the real system binary when one is installed**:
  Tectonic 0.17 runs `biber` natively for biblatex documents (it looks it up
  on PATH, runs it in a scratch dir and re-runs TeX), so the farm must not
  shadow it.  Without a real `biber` on PATH the compile still succeeds but
  the bibliography is empty, citations print their raw keys, and an honest
  warning is shown.  Note that `biber` must match Tectonic's bundled
  biblatex: Tectonic 0.17 ships biblatex 3.17 (bcf 3.8), which pairs with
  `biber` 2.17 — a newer `biber` (e.g. Homebrew's current 2.21, which needs
  biblatex 3.21) aborts the compile with a “versions are incompatible”
  error.
- Tectonic itself never runs `makeindex`; it only writes `.idx` files.  The
  engine dispatcher implements the rerun loop instead: after a compile that
  produced `.idx` files it runs a real `makeindex` binary (found on PATH,
  falling back to `upmendex`, a drop-in-compatible replacement) on each and
  re-runs Tectonic once, so `\printindex` output is included in the PDF.  If
  neither `makeindex` nor `upmendex` is installed the compile still succeeds
  but prints a warning, and the index is not built.  Standalone
  `makeindex`/`xindy`/`upmendex` calls proxy to the real binary when
  installed and are exit-0 notes otherwise (the loop never uses `xindy` —
  it is not a makeindex drop-in).
- No DVI/PostScript output at all: Tectonic compiles directly to PDF, so
  `-output-format=dvi` warns (and still produces PDF), `-draftmode` is
  silently ignored, and `dvips` & friends are stubs.
- `-jobname` is implemented by renaming the produced artifacts (`.pdf` and
  `.synctex.gz`) after the run.
- `tlmgr install …` exits non-zero (fonts/macros come from Tectonic's bundle);
  `mf`/`mpost`/`context` are stubs that report they can't run.
- The `latexmk` shim reads a simple subset of `.latexmkrc` (`$pdf_mode`,
  `$pdflatex`, `$xelatex`, `$lualatex`, `$out_dir`, `$jobname`); an explicit
  `-r FILE` is honored even with `-norc`, and `-c`/`-C` clean only the output
  directory when `-outdir` is set (like stock latexmk).

## Extending

1. Add a name to the right group in `src/tectdist/flags.py` and run
   `python3 make_links.py`.
2. Implement its behaviour: a new dispatch arm in `src/tectdist/dispatcher.py`
   for engines/stubs/tools, a new function in `src/tectdist/tools.py` for
   gs-based/proxied tools, or extend `src/tectdist/latexmk.py` for the driver.
3. Add checks to `tests/battery.py` and run it:
   `python3 tests/battery.py`.

## License

AGPL-3.0-only — see [LICENSE](LICENSE).  Contributions are welcome; see
[CONTRIBUTING.md](CONTRIBUTING.md).
