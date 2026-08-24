#!/usr/bin/env python3
"""Create the BasicTeX-only real-world qualification corpus (plan §8.5).

Every document uses only packages present in the frozen BasicTeX manifest.
Each directory contains the sources plus a meta.json declaring the exact
reference resolution sequence and expected page count floor.

Usage:
    python3 scripts/basictex_corpus.py [--output benchmarks/basictex-corpus]
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DOCUMENTS = {
    "plain-tex": {
        "main": "main.tex",
        "sequence": ["tex {job}.tex"],
        "expect_pages_floor": 1,
        "content": r"""Hello from plain TeX.
Width of box: \ifdim 5pt>3pt true\fi.

\bye
""",
    },
    "article-basic": {
        "main": "main.tex",
        "sequence": ["pdflatex {job}.tex"],
        "expect_pages_floor": 1,
        "content": r"""\documentclass{article}
\usepackage{makeidx}
\makeindex
\begin{document}
\title{BasicTeX Article}\author{BT100}\maketitle
\section{Introduction}
This article exercises the standard LaTeX article class with an index.
Text about indexing appears here\index{indexing}.
\printindex
\end{document}
""",
    },
    "report-book-refs": {
        "main": "main.tex",
        "sequence": ["pdflatex {job}.tex", "pdflatex {job}.tex"],
        "expect_pages_floor": 3,
        "content": r"""\documentclass[12pt]{report}
\begin{document}
\tableofcontents
\chapter{First}
\label{ch:first}
See chapter~\ref{ch:second}.
\section{Detail}
Some content with an equation $e^{i\pi}+1=0$.
\chapter{Second}
\label{ch:second}
More content so the report spans several pages.
\newpage
Additional page of content for length.
\end{document}
""",
    },
    "ams-math": {
        "main": "main.tex",
        "sequence": ["pdflatex {job}.tex"],
        "expect_pages_floor": 1,
        "content": r"""\documentclass{article}
\usepackage{amsmath}
\usepackage{amsthm}
\newtheorem{theorem}{Theorem}
\begin{document}
\begin{theorem}\label{thm:x}
For all $n$, $\sum_{k=1}^n k = n(n+1)/2$.
\end{theorem}
\begin{align}
a &= b + c \\
  &= d
\end{align}
Reference: theorem~\eqref{thm:x}.
\end{document}
""",
    },
    "bibtex-doc": {
        "main": "main.tex",
        "bib": "refs.bib",
        "sequence": ["pdflatex {job}.tex", "bibtex {job}",
                     "pdflatex {job}.tex", "pdflatex {job}.tex"],
        "expect_pages_floor": 1,
        "content": r"""\documentclass{article}
\begin{document}
Citing Knuth~\cite{knuth84} and Lamport~\cite{lamport86}.
\bibliographystyle{plain}
\bibliography{refs}
\end{document}
""",
        "extra_files": {
            "refs.bib": """@book{knuth84,
  author = {Donald E. Knuth},
  title = {The TeXbook},
  publisher = {Addison-Wesley},
  year = {1984}
}
@book{lamport86,
  author = {Leslie Lamport},
  title = {LaTeX: A Document Preparation System},
  publisher = {Addison-Wesley},
  year = {1986}
}
""",
        },
    },
    "xelatex-fonts": {
        "main": "main.tex",
        "sequence": ["xelatex {job}.tex"],
        "expect_pages_floor": 1,
        "content": r"""\documentclass{article}
\usepackage{fontspec}
\setmainfont{lmroman10-regular.otf}
\begin{document}
Unicode text with accented characters: café, naïve, Zürich.
Mathematics stays with legacy fonts where available.
\end{document}
""",
    },
    "lualatex-doc": {
        "main": "main.tex",
        "sequence": ["lualatex {job}.tex"],
        "expect_pages_floor": 1,
        "content": r"""\documentclass{article}
\begin{document}
\directlua{tex.print("Lua says: " .. tostring(2 + 2))}
LuaLaTeX pipeline document.
\end{document}
""",
    },
    "dvi-dvips": {
        "main": "main.tex",
        "sequence": ["latex {job}.tex", "dvips {job}.dvi"],
        "expect_artifacts": ["main.dvi", "main.ps"],
        "expect_pages_floor": 1,
        "content": r"""\documentclass{article}
\begin{document}
DVI pipeline document routed through dvips.
\end{document}
""",
    },
    "metapost-figure": {
        "main": "fig.mp",
        "is_metapost": True,
        "sequence": ["mpost fig.mp"],
        "expect_artifacts": ["fig.1"],
        "expect_pages_floor": None,
        "content": """beginfig(1)
draw (0,0)--(30mm,0)--(30mm,10mm)--cycle;
label(btex MP etex, origin);
endfig;
end.
""",
    },
    "stress-book-50p": {
        "main": "main.tex",
        "sequence": ["pdflatex {job}.tex", "pdflatex {job}.tex"],
        "expect_pages_floor": 50,
        "generated": "stress_book",
    },
}


def stress_book_content():
    chapters = []
    for chapter in range(1, 9):
        body = []
        for section in range(1, 6):
            body.append(
                "\\section{Chapter %d Section %d}\n" % (chapter, section)
                + ("Paragraph with mathematics $\\int_0^1 x^2\\,dx = \\frac13$ "
                   "and a cross-reference label.\n\\label{sec:%d:%d}\n"
                   % (chapter, section))
                + "Repeated filler sentence for page volume. " * 12)
        chapters.append("\\chapter{Chapter %d}\n%s" % (chapter, "\n".join(body)))
    preamble = r"""\documentclass[11pt]{report}
\usepackage{amsmath}
\begin{document}
\tableofcontents
"""
    epilogue = "\n".join(chapters) + "\n\\end{document}\n"
    return preamble + epilogue


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(ROOT / "benchmarks/basictex-corpus"))
    ns = parser.parse_args(argv)
    out = Path(ns.output)
    created = []
    for name, spec in DOCUMENTS.items():
        directory = out / name
        directory.mkdir(parents=True, exist_ok=True)
        content = spec.get("content") or (
            stress_book_content() if spec.get("generated") == "stress_book" else "")
        (directory / spec["main"]).write_text(content)
        for extra_name, extra_content in spec.get("extra_files", {}).items():
            (directory / extra_name).write_text(extra_content)
        meta = {"sequence": spec["sequence"],
                "expect_pages_floor": spec["expect_pages_floor"]}
        if spec.get("expect_artifacts"):
            meta["expect_artifacts"] = spec["expect_artifacts"]
        if spec.get("is_metapost"):
            meta["is_metapost"] = True
        (directory / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
        created.append(name)
    print(f"corpus: created {len(created)} BasicTeX documents -> {out}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
