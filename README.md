# tectdist

A drop-in TeX distribution backed by [Tectonic](https://tectonic-typesetting.github.io) —
one executable plus the classic TeX tool names (`pdflatex`, `latexmk`, `bibtex`,
`kpsewhich`, `biber`, …), so editors, build systems and CI scripts work
unchanged. No TeX Live install required.

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

Requires `python3` ≥ 3.9; compiling requires `tectonic` on PATH.

## Quick start

```sh
pdflatex -synctex=1 -interaction=nonstopmode main.tex   # like TeX Live
latexmk -pdf -outdir=build main.tex                     # build driver
kpsewhich -var-value TEXINPUTS                          # file lookup
```

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
   `latexmk`, `kpsewhich`, `epstopdf`, `pdfcrop`.
4. Typeset as usual.

Notes:

- The engine is Tectonic (XeTeX-based): the web2c interface is translated,
  but the typesetting engine is Tectonic's, not pdfTeX's.
- The first compile downloads Tectonic's support files on demand (cached in
  `~/.cache/Tectonic`).

## What you get

| Group | Names | Behaviour |
|---|---|---|
| Engines | `pdflatex`, `latex`, `xelatex`, `lualatex`, `platex`, `uplatex`, `pdftex`, `tex`, `etex`, `luatex`, … | compile via Tectonic |
| Build driver | `latexmk` | classic interface (`-pdf`, `-outdir`, `-c/-C`, `.latexmkrc`) |
| Bibliography | `biber` | biblatex works out of the box |
| Stubs | `bibtex`, `makeindex`, `dvips`, `tlmgr`, `mf`, `context`, … | no-op with a note when the real binary is absent |
| Real tools | `epstopdf`, `ps2pdf`, `eps2eps`, `pdfcrop` | Ghostscript-backed |
| Proxies | `pdfinfo`, `pdftotext`, `pdftoppm`, `pdfunite`, `qpdf`, … | pass through to poppler/qpdf |
| Lookup | `kpsewhich` | file lookup with TEXINPUTS search |

## Limitations

- One engine — Tectonic's XeTeX-based LaTeX; documents relying on pdfTeX- or
  LuaTeX-specific behaviour may typeset differently.
- biblatex works out of the box (bundled biber 2.17 matched to biblatex
  3.17); Homebrew's core biber (2.21) is not compatible with that biblatex.
- Classic `\bibliography` is processed inside the Tectonic compile; standalone
  `bibtex` is a no-op stub.
- PDF output only: no DVI/PostScript; `dvips` & friends are stubs.
- `tlmgr install …` exits non-zero; `mf`, `mpost` and `context` are stubs.
- The `latexmk` shim reads a subset of `.latexmkrc` (`$pdf_mode`, `$out_dir`,
  `$jobname`, …).

## License

AGPL-3.0-only — see [LICENSE](LICENSE). Contributions welcome:
[CONTRIBUTING.md](CONTRIBUTING.md).
