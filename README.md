# tectdist

Use LaTeX without installing TeX Live. tectdist runs documents through
[Tectonic](https://tectonic-typesetting.github.io) while providing the familiar
commands expected by editors, build systems and CI: `pdflatex`, `latexmk`,
`biber`, `kpsewhich` and more — compiling documents [34% faster than TeX
Live's own `latexmk`](BENCHMARKS.md#vs-tex-live) in one command, with no
manual reruns.

## Install

On macOS or Linux with [Homebrew](https://brew.sh):

```sh
brew install tmonk/brew/tectdist
```

That's it. Homebrew installs the engine and supporting PDF and bibliography
tools too.

## Use

Compile a document with the simple command:

```sh
tectdist main.tex
```

Existing TeX commands work too, so projects and editor settings usually need
no changes:

```sh
pdflatex -synctex=1 -interaction=nonstopmode main.tex
latexmk -pdf -outdir=build main.tex
```

The first compile downloads the required TeX support files and caches them for
later runs. If something doesn't work — a command isn't found, or another TeX
install is in the way — run `tectdist doctor` for a health check, or
`brew link --overwrite tectdist` to make Homebrew's links win.

## TeXifier

1. Install tectdist with Homebrew.
2. In TeXifier, open **Settings → Distribution → Set Custom Distribution**.
3. Select the `bin` directory inside the path printed by
   `brew --prefix tectdist`.

Typeset as usual. No command-line PATH setup is needed for TeXifier.

## Compatibility

tectdist translates the classic web2c command-line interface — engine flags
like `-synctex`, `-output-directory`, `-jobname` and `-shell-escape`,
`latexmk`'s common workflows, and `kpsewhich` lookups — onto Tectonic, so
existing editor and CI configs keep working unchanged. Run `tectdist tools`
for the full list of compatible command names.

## Limitations

- Every engine command uses Tectonic's XeTeX-based engine. Documents depending
  on pdfTeX- or LuaTeX-specific behavior may render differently.
- Output is PDF only; DVI and PostScript workflows are not implemented.
- Homebrew's bundled biber 2.17 is intentionally matched to the biblatex 3.17
  included by Tectonic 0.17. Do not replace it with an incompatible biber.
- Indexes require a real `makeindex` or `upmendex` on PATH.
- The `latexmk` shim implements the common interface, not every upstream
  `latexmk` feature.

## License

AGPL-3.0-only — see [LICENSE](LICENSE).
