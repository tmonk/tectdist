#!/usr/bin/env bash
# Full black-box acceptance test for the documented Homebrew installation.
#
# This deliberately removes an existing tectdist installation, installs the
# requested formula, then uses a new HOME and an empty Tectonic cache. It
# validates the actual installed commands, including the Biber/biblatex path
# that simple document smoke tests do not reach.
#
# Usage:
#   tests/homebrew_e2e.sh
#   TECTDIST_FORMULA=./Formula/tectdist.rb tests/homebrew_e2e.sh
#   TECTDIST_REQUIRE_BOTTLE=1 tests/homebrew_e2e.sh

set -euo pipefail

formula="${TECTDIST_FORMULA:-tmonk/brew/tectdist}"
require_bottle="${TECTDIST_REQUIRE_BOTTLE:-0}"
tmpdir="$(mktemp -d "${TMPDIR:-/tmp}/tectdist-homebrew-e2e.XXXXXX")"
trap 'rm -rf "$tmpdir"' EXIT

if [[ "${TECTDIST_SKIP_INSTALL:-0}" != 1 ]]; then
  if brew list --versions tectdist >/dev/null 2>&1; then
    brew uninstall tectdist
  fi

  brew install "$formula" 2>&1 | tee "$tmpdir/install.log"
  if [[ "$require_bottle" == 1 ]]; then
    grep -q "Pouring tectdist" "$tmpdir/install.log"
  fi
fi

prefix="$(brew --prefix tectdist)"
test -x "$prefix/bin/tectdist"
test -x "$prefix/bin/biber"

work="$tmpdir/work"
mkdir -p "$work/home" "$work/cache" "$work/build"
cat >"$work/main.tex" <<'EOF'
\documentclass{article}
\begin{document}
Fresh Homebrew install.
\end{document}
EOF
cat >"$work/citations.tex" <<'EOF'
\documentclass{article}
\usepackage[backend=biber,style=authoryear]{biblatex}
\addbibresource{references.bib}
\begin{document}
An end-to-end bibliography citation: \autocite{knuth1984}.
\printbibliography
\end{document}
EOF
cat >"$work/references.bib" <<'EOF'
@book{knuth1984,
  author = {Donald E. Knuth},
  title = {The TeXbook},
  year = {1984},
  publisher = {Addison-Wesley}
}
EOF

# Retain Homebrew's PATH but no user configuration or prior Tectonic cache.
run=(env -i "PATH=$PATH" "HOME=$work/home" "XDG_CACHE_HOME=$work/cache")
cd "$work"
"${run[@]}" tectdist doctor | grep -q "PAIR OK"
"${run[@]}" biber --version | grep -q "biber version: 2.17"
"${run[@]}" tectdist main.tex
test -s main.pdf
"${run[@]}" pdflatex -synctex=1 -interaction=nonstopmode main.tex
test -s main.synctex.gz
"${run[@]}" latexmk -pdf -outdir=build citations.tex
test -s build/citations.pdf

echo "homebrew_e2e: OK ($formula)"
