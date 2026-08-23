# Compatibility and limitations

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
