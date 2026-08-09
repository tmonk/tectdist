# tectdist

A drop-in TeX distribution backed by [Tectonic](https://tectonic-typesetting.github.io) —
one executable plus the classic TeX tool names (`pdflatex`, `latexmk`, `bibtex`,
`kpsewhich`, `biber`, …), so editors, build systems and CI scripts work
unchanged. No TeX Live install required.

Everything is a single-file Python 3 zipapp plus a symlink farm: every tool
name points at the same executable, which dispatches on the invoked name and
speaks the classic web2c flag vocabulary.

## Install

### Homebrew (recommended)

```sh
brew tap tmonk/brew
brew install tmonk/brew/tectdist
```

If another TeX installation already provides some farm names:

```sh
brew link --overwrite tectdist
```

### From the repository

```sh
python3 make_links.py     # build the bin/ symlink farm (idempotent)
python3 install.py        # add bin/ to PATH in ~/.zshrc (or pass an rc file)
python3 uninstall.py      # remove the PATH entry
```

`python3 build.py` builds the single-file release artifact (`dist/tectdist`).

## Quick start

```sh
pdflatex -synctex=1 -interaction=nonstopmode main.tex   # like TeX Live
latexmk -pdf -outdir=build main.tex                     # build driver
kpsewhich -var-value TEXINPUTS                          # file lookup
latexmk --dry-run -pdf main.tex                         # inspect the engine call
tectdist doctor --json                                  # machine-readable health check
```

Set `TECTONIC` to use a specific engine binary (default: `tectonic` on PATH,
else `/opt/homebrew/bin/tectonic`).

## TeXifier

tectdist exists so [TeXifier](https://www.texifier.com) users can typeset
without a multi-gigabyte TeX Live install: the Distribution pane just needs a
directory containing the classic binaries, and the farm provides them.

1. Install tectdist — Homebrew (farm in `/opt/homebrew/bin` or
   `/usr/local/bin`) or a source checkout (`python3 make_links.py`).
2. Open TeXifier Preferences (`Cmd-,`) → **Distribution** → **Set Custom
   Distribution**, and select the farm directory (or pick it from *Installed
   LaTeX distributions* when Homebrew installed it in the standard location).
3. The health check passes: the farm provides the engine names plus
   `latexmk`, `kpsewhich`, `epstopdf`, `pdfcrop` and the maintenance stubs.
4. Typeset as usual.

Notes:

- The engine is Tectonic (XeTeX-based): the web2c interface is translated,
  but the typesetting engine is Tectonic's, not pdfTeX's.
- The first compile downloads Tectonic's support files on demand (cached in
  `~/.cache/Tectonic`).
- No PATH setup is needed for TeXifier; `python3 install.py` is only for
  command-line use.

## Requirements

| Tool | Needed for |
|---|---|
| `tectonic` 0.17.x | every compile (required) |
| `ghostscript` | `epstopdf`, `ps2pdf`, `pdfcrop` |
| `poppler` | `pdfinfo`, `pdftotext`, `pdfunite`, … |
| `qpdf` | `qpdf` |
| `python@3.14` | the zipapp interpreter (the repo tools run on stock `python3` ≥ 3.9) |
| `perl` | building and running the bundled biber |
| `libxml2`, `libxslt` | biber's XML modules |
| `openssl@3` | biber's HTTPS support |

biber 2.17 is built from source by the formula (the plk/biber v2.17 source
plus 119 sha256-pinned CPAN module resources, mirroring homebrew-core's own
biber formula) — no prebuilt binaries anywhere.

## What you get

| Group | Names | Behaviour |
|---|---|---|
| Engines | `pdflatex`, `latex`, `xelatex`, `lualatex`, `platex`, `uplatex`, `pdftex`, `tex`, `etex`, `luatex`, … | compile via Tectonic; full web2c flag vocabulary |
| Build driver | `latexmk` | classic interface (`-pdf`, `-outdir`, `-c/-C`, `.latexmkrc`) |
| Bibliography | `biber` | real biber 2.17 (Homebrew); proxies to a PATH biber otherwise |
| Stubs | `bibtex`, `makeindex`, `xindy`, `dvips`, `tlmgr`, `mktexlsr`, `mf`, `context`, … | exit 0 with a note when the real binary isn't installed |
| Real tools | `epstopdf`, `ps2pdf`, `eps2eps`, `pdfcrop` | implemented on Ghostscript |
| Proxies | `pdfinfo`, `pdftotext`, `pdftoppm`, `pdftocairo`, `pdfunite`, `pdftops`, `qpdf`, … | forwarded to the real system binary |
| Lookup | `kpsewhich` | `-var-value`, `-format=`, TEXINPUTS/BIBINPUTS/BSTINPUTS search |

Common flags (`-synctex`, `-output-directory`, `-jobname`, `-shell-escape`,
`-fmt`, `TEXINPUTS`, …) are translated to Tectonic; flags with no Tectonic
equivalent (`-halt-on-error`, `-recorder`, memory knobs, …) are ignored;
everything else passes through untouched. Output goes to the current
directory unless `-output-directory` is given.

## Platform support

| Platform | Bottle | Notes |
|---|---|---|
| macOS arm64 | `arm64_sequoia` | verified end-to-end (biblatex → PDF) |
| macOS Intel | `sequoia` | CI-built and published |
| Linux x86_64 | `x86_64_linux` | CI-built and published |
| Linux arm64 | `arm64_linux` | CI-built and published |

biber 2.17 is built from source on every platform; bottles pour in seconds,
source builds are the fallback.

## Development

```sh
python3 tests/battery.py             # acceptance suite (stdlib only)
python3 tests/battery.py --mock-only # mock tier only, no engine needed
```

The battery is the equivalence oracle: flag vocabulary, translation and
dispatcher mechanics against a recording fake engine, plus end-to-end
compiles with a real Tectonic. Benchmarks live in
[BENCHMARKS.md](BENCHMARKS.md); extending the tool farm is covered in
[CONTRIBUTING.md](CONTRIBUTING.md).

## Limitations

- One engine — Tectonic's XeTeX-based LaTeX. Every engine name compiles with
  it; documents relying on pdfTeX- or LuaTeX-specific behaviour may typeset
  differently.
- biblatex works out of the box (formula-built biber 2.17 matched to biblatex
  3.17); Homebrew's core biber (2.21) is not compatible with that biblatex.
- Classic `\bibliography` is processed inside the Tectonic compile; standalone
  `bibtex` is a no-op stub.
- Indexes: the dispatcher runs a real `makeindex`/`upmendex` and re-runs
  Tectonic when `.idx` files appear (with a warning if neither is installed).
- PDF output only: no DVI/PostScript; `dvips` & friends are stubs.
- `tlmgr install …` exits non-zero; `mf`, `mpost` and `context` are stubs.
- The `latexmk` shim reads a subset of `.latexmkrc` (`$pdf_mode`, `$out_dir`,
  `$jobname`, …) and supports `-n`/`--dry-run` for editor and CI inspection.
- `tectdist doctor --json` emits the pairing report as structured JSON for
  integrations; the default `tectdist doctor` form remains human-readable.

## License

AGPL-3.0-only — see [LICENSE](LICENSE). Contributions welcome:
[CONTRIBUTING.md](CONTRIBUTING.md).
