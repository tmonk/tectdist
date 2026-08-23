# tectdist

Use LaTeX without installing TeX Live. tectdist compiles your documents
through [Tectonic](https://tectonic-typesetting.github.io), a modern,
self-contained LaTeX engine, but answers to the same commands
(`pdflatex`, `latexmk`, `biber`, `kpsewhich`) as a normal TeX Live
install, so your editor and existing documents just work, unchanged. It's
also [34% faster than TeX Live's own `latexmk`](BENCHMARKS.md#vs-tex-live)
at producing a finished PDF, with no manual reruns needed.

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
later runs. If something doesn't work (a command isn't found, or another TeX
install is in the way), run `tectdist doctor` for a health check, or
`brew link --overwrite tectdist` to make Homebrew's links win.

## TeXifier

1. Install tectdist with Homebrew.
2. In TeXifier, open **Settings → Distribution → Set Custom Distribution**.
3. Select the `bin` directory inside the path printed by
   `brew --prefix tectdist`.

Typeset as usual. No command-line PATH setup is needed for TeXifier.

## License

AGPL-3.0-only, see [LICENSE](LICENSE). Full compatibility details and
known limitations are in [COMPATIBILITY.md](COMPATIBILITY.md).
