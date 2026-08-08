#!/usr/bin/env python3
# =============================================================================
# tectdist acceptance battery (Python 3, stdlib only)
#
# The suite is split into two tiers so it stays fast AND stays meaningful:
#
#   [mock]  flag-vocabulary / translation / dispatcher checks.  The engine is
#           replaced by a recording stub (via the TECTONIC override), so these
#           checks need no TeX engine and take milliseconds.  They assert the
#           exit code AND the exact argument vector the engine would receive.
#
#   [real]  end-to-end behaviour checks against a real Tectonic engine:
#           compile -> PDF, -jobname / -output-directory / -synctex artifacts,
#           TEXINPUTS search, error exit codes, the latexmk driver, and the
#           Ghostscript / poppler-backed tools.  Every real-engine invocation
#           is time-bounded so the suite can never hang.
#
# All cases run in parallel (thread pool) and each runs in its own isolated
# scratch directory, so no check can pollute another.  If a real engine is not
# installed the [real] sections are reported as SKIPPED (never failed): the
# [mock] tier keeps the suite useful on machines with no TeX at all.
#
# Usage:
#   python3 tests/battery.py              # everything that can run
#   python3 tests/battery.py --mock-only  # skip [real] sections
#   python3 tests/battery.py --jobs 4     # worker count (default: min(8, cpus))
#
# Exit status: 0 iff no check failed (skips are fine).
# =============================================================================

from __future__ import annotations

import argparse
import concurrent.futures
import glob
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field

BIN = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin"))
TINY = (
    "\\documentclass{article}\n"
    "\\begin{document}\n"
    "Hello \\LaTeX{} world.\n"
    "\\end{document}\n"
)
STDIN_DOC = "\\documentclass{article}\\begin{document}hi\\end{document}"
INDEX_DOC = (
    "\\documentclass{article}\n"
    "\\usepackage{makeidx}\n"
    "\\makeindex\n"
    "\\begin{document}\n"
    "Hello\\index{alpha}\\index{beta} world.\n"
    "\\printindex\n"
    "\\end{document}\n"
)
BIBLIO_DOC = (
    "\\documentclass{article}\n"
    "\\usepackage[style=numeric]{biblatex}\n"
    "\\addbibresource{refs.bib}\n"
    "\\begin{document}\n"
    "See \\cite{knuth}.\n"
    "\\printbibliography\n"
    "\\end{document}\n"
)
BIBLIO_BIB = (
    "@book{knuth, author={Knuth, Donald}, title={The TeXbook},\n"
    "       year={1984}, publisher={Addison-Wesley}}\n"
)
EPS = """%!PS-Adobe-3.0 EPSF-3.0
%%BoundingBox: 0 0 100 100
newpath 10 10 moveto 90 90 lineto stroke
showpage
"""
PS = "%!PS\nnewpath 10 10 moveto 90 90 lineto stroke\nshowpage\n"

FAKE_SRC = """#!/usr/bin/env python3
import os, sys
log = os.environ.get("FAKELOG")
if log:
    with open(log, "w") as f:
        f.write(" ".join(sys.argv[1:]) + "\\n")
sys.exit(0)
"""

STYLES = {"mystyle.sty": "\\newcommand{\\mystuff}{styled}\n"}


def unique_pkg(pkg):
    return (
        f"\\newcommand{{\\{pkg}}}{{{pkg} ok}}\n",
        f"\\documentclass{{article}}\\usepackage{{{pkg}}}\\begin{{document}}{pkg} ok\\end{{document}}\n",
    )


FIXTURE_TEX = {
    "tiny.tex": TINY,
    "my doc.tex": TINY,
    "bad.tex": (
        "\\documentclass{article}\n\\begin{document}\n"
        "\\undefinedcommandhere\n\\end{document}\n"
    ),
    "texinputs.tex": (
        "\\documentclass{article}\n\\usepackage{mystyle}\n"
        "\\begin{document}\n\\mystuff\n\\end{document}\n"
    ),
}
for pkg in ("pkgone", "pkgtwo", "pkgthree", "pkgfour", "pkgfive"):
    sty, tex = unique_pkg(pkg)
    STYLES[f"{pkg}.sty"] = sty
    FIXTURE_TEX[f"use{pkg[3:] if False else 'one' if pkg=='pkgone' else 'two' if pkg=='pkgtwo' else 'three' if pkg=='pkgthree' else 'four' if pkg=='pkgfour' else 'five'}.tex"] = tex


# ---------------------------------------------------------------------------
# engine / tool detection (mirrors bin/tectdist's resolution)
# ---------------------------------------------------------------------------
def find_engine():
    cand = os.environ.get("TECTONIC", "")
    if not cand:
        cand = shutil.which("tectonic") or ""
    if not cand and os.path.isfile("/opt/homebrew/bin/tectonic"):
        cand = "/opt/homebrew/bin/tectonic"
    return cand if cand and os.path.isfile(cand) and os.access(cand, os.X_OK) else ""


def have(tool):
    return shutil.which(tool) is not None


# ---------------------------------------------------------------------------
# case model
# ---------------------------------------------------------------------------
@dataclass
class Case:
    name: str
    section: str
    tier: str                      # "mock" | "real"
    cmd: list                      # "$B"/"$D" tokens are resolved at runtime
    want: int | None = 0           # expected exit code
    want_files: list = field(default_factory=list)   # must exist (rel. to cwd)
    no_files: list = field(default_factory=list)     # must NOT exist (rel. to cwd)
    want_args: list = field(default_factory=list)    # engine argv must contain
    want_not_args: list = field(default_factory=list)
    want_last: str | None = None   # final engine argv token
    stdout_exact: str | None = None
    stdout_contains: str | None = None
    stdout_contains2: str | None = None
    stderr_contains: str | None = None
    pdf_contains: str | None = None   # pdftotext must find this in the PDF
    env: dict = field(default_factory=dict)
    stdin: str | None = None
    cwd: str | None = None         # subdir of the case's scratch dir
    rc_file: str | None = None     # content of .latexmkrc in the scratch dir
    setup: dict = field(default_factory=dict)        # filename -> content
    chmod: list = field(default_factory=list)        # setup files to chmod 755
    want_runs: int | None = None   # expected engine-run count (argv.log lines)
    need_pdf: bool = False         # copy the pre-compiled tiny.pdf in
    skip_reason: str = ""
    skip_if_stderr: str | None = None  # on failure, skip if stderr contains this
                                      # (environmental incompatibility, not a bug)

    def skip(self, reason):
        self.skip_reason = reason
        return self


def B(*parts):
    return os.path.join(BIN, *parts)


# --- compact builders --------------------------------------------------------
def engine_case(name, section, tier, flags, prog="pdflatex", input="tiny.tex", **kw):
    cmd = ["$B/" + prog] + list(flags)
    if input is not None:
        cmd.append(input)
    return Case(name=name, section=section, tier=tier, cmd=cmd, **kw)


def mock(name, section, flags, **kw):
    return engine_case(name, section, "mock", flags, **kw)


def real(name, section, flags, **kw):
    return engine_case(name, section, "real", flags, **kw)


# =============================================================================
# build the case list
# =============================================================================
CASES = []
S = {}


def sec(name):
    S.setdefault(name, True)
    return name


SEC_MOCK_FLAGS = sec("mock: flag vocabulary (fake engine)")
SEC_VERHELP = sec("mock: version, help, quiet")
SEC_TRANS = sec("mock: flag translation (exact engine args)")
SEC_DISP = sec("mock: dispatcher mechanics")
SEC_FARM = sec("mock: engine farm")
SEC_LMK_MOCK = sec("mock: latexmk interface")
SEC_STUBS = sec("mock: stubs & lookup tools")
SEC_LOOP = sec("mock: makeindex rerun loop")
SEC_REAL = sec("real: engine behaviour (tectonic)")
SEC_LMK_REAL = sec("real: latexmk end-to-end (tectonic)")
SEC_GS = sec("real: gs tools (epstopdf, ps2pdf, pdfcrop)")
SEC_PROXY = sec("real: poppler/qpdf proxies")

ENGINES = ("pdflatex latex xelatex lualatex platex uplatex pdftex tex etex luatex "
           "luahbtex dvilualatex dviluatex xetex pdfetex").split()
STUB_BIB = ("bibtex bibtex8 bibtexu").split()
PROXY_OR_STUB = ("biber makeindex xindy upmendex").split()
STUB_DVI = ("dvips dvipdfm dvipdfmx dvipdf xdvipdfmx dvitype dvicopy dvipos dvidvi").split()
STUB_MNT = ("mktexlsr texhash mktexfmt mktexpk mktextfm fmtutil fmtutil-sys "
            "updmap updmap-sys").split()
STUB_FNT = ("tftopl pltotf vftovp vptovf gftopk gftype afm2tfm otftotfm mf mpost "
            "mft tangle weave context texexec").split()
MEMORY = ("main-memory=1000000 extra-mem-top=1000000 extra-mem-bot=100000 buf-size=100000 "
          "max-print-line=100 error-line=100 half-error-line=100 hash-size=1000 pool-size=100000 "
          "save-size=100000 stack-size=100000 strings=100000 nest-size=100 param-size=1000 "
          "font-max=100 font-mem-size=1000000 max-in-open=50 pkin=100 tfm=100 max-pages=10").split()

# --- A. classic flag vocabulary: every flag accepted (exit 0, fake engine) ---
for f in ("-interaction=nonstopmode", "-interaction=errorstopmode", "-interaction=scrollmode",
          "-interaction=batchmode", "-file-line-error", "-no-file-line-error", "-halt-on-error",
          "-synctex=0", "-synctex=1", "-synctex=2", "-synctex=-1",
          "-jobname=job1", "-output-directory=od1", "-outdir=od3", "-aux-directory=od4",
          "-shell-escape", "-no-shell-escape", "-enable-write18", "-disable-write18",
          "-enable-shell-escape", "-disable-shell-escape", "-shell-restricted",
          "-draftmode", "-draft", "-recorder", "-8bit", "-etex", "-enc",
          "-pdf", "-no-pdf", "-dvi", "-output-format=pdf", "-output-format=dvi",
          "-parse-first-line", "-no-parse-first-line", "-progname=foo", "-cnf-line=foo=bar",
          "-translate-file=foo.tcx", "-src-specials", "-src-specials=everypar",
          "-output-comment=hello", "-ini", "-undump", "-ipc", "-ipc-start",
          "-maketex", "-no-maketex", "-no-mktexpk", "-no-mktexfmt",
          "-pdftex", "-xetex", "-luatex", "-enable-installer", "-disable-installer",
          "-enable-enctex", "-disable-enctex", "-c-style-errors", "-file-line-error-style",
          "-allow-orphan-aux", "-no-allow-orphan-aux", "-tcx=foo.tcx", "-utf8"):
    CASES.append(mock(f"flag {f}", SEC_MOCK_FLAGS, [f]))
for m in MEMORY:
    CASES.append(mock(f"memory {m}", SEC_MOCK_FLAGS, [f"-{m}"]))
CASES.append(mock("interaction separate", SEC_MOCK_FLAGS, ["-interaction", "nonstopmode"]))
CASES.append(mock("synctex separate", SEC_MOCK_FLAGS, ["-synctex", "1"]))
CASES.append(mock("jobname separate", SEC_MOCK_FLAGS, ["-jobname", "job2"]))
CASES.append(mock("output-directory sep", SEC_MOCK_FLAGS, ["-output-directory", "od2"]))
CASES.append(mock("output-format sep", SEC_MOCK_FLAGS, ["-output-format", "pdf"]))

# --- B. version / help / quiet ----------------------------------------------
for v in ("-version", "-v", "-V", "--version"):
    CASES.append(mock(f"version {v}", SEC_VERHELP, [v]))
for h in ("-help", "-h", "--help"):
    CASES.append(mock(f"help {h}", SEC_VERHELP, [h]))
CASES.append(Case(name="tectdist --help", section=SEC_VERHELP, tier="mock",
                  cmd=["$B/tectdist", "--help"]))
CASES.append(Case(name="tectdist -V", section=SEC_VERHELP, tier="mock",
                  cmd=["$B/tectdist", "-V"]))
for q in ("-q", "-quiet", "-silent"):
    CASES.append(mock(f"quiet {q}", SEC_VERHELP, [q]))

CASES.append(mock("version arg -> --version", SEC_VERHELP, ["-version"],
                  want_args=["--version"]))
CASES.append(mock("help arg -> --help", SEC_VERHELP, ["--help"], want_args=["--help"]))
for q in ("-q", "-quiet", "-silent"):
    CASES.append(mock(f"quiet {q} -> chatter", SEC_VERHELP, [q],
                      want_args=["--chatter minimal"]))
CASES.append(mock("batchmode -> chatter", SEC_VERHELP, ["-interaction=batchmode"],
                  want_args=["--chatter minimal"]))

# --- B2. runtime pairing check + doctor (declared 0.17 + biber 2.17) --------
# The battery's default fake engine prints nothing for --version, which the
# pairing check treats as unparseable and skips, so the mock tier above is
# unaffected.  These cases install tiny engine stubs that DO answer --version
# and assert the fail-fast / doctor behaviour, plus the release gate that
# keeps Formula/tectdist.rb and src/tectdist/pairing.py in lockstep.
SEC_PAIR = sec("mock: pairing check & doctor")

FAKE17 = "#!/bin/sh\nif [ \"$1\" = --version ]; then echo \"Tectonic 0.17.9 (stub)\"; exit 0; fi\nexit 0\n"
FAKE18 = "#!/bin/sh\nif [ \"$1\" = --version ]; then echo \"Tectonic 0.18.0 (stub)\"; exit 0; fi\nexit 0\n"

CASES.append(Case(name="pairing ok (tectonic 0.17.9)", section=SEC_PAIR, tier="mock",
                  cmd=["$B/pdflatex", "tiny.tex"],
                  setup={"fake17.sh": FAKE17}, chmod=["fake17.sh"],
                  env={"TECTONIC": "$D/fake17.sh", "TECTDIST_SKIP_PAIRING": ""},
                  want=0, want_args=["tiny.tex"]))
CASES.append(Case(name="pairing fail-fast (tectonic 0.18.0)", section=SEC_PAIR, tier="mock",
                  cmd=["$B/pdflatex", "tiny.tex"],
                  setup={"fake18.sh": FAKE18}, chmod=["fake18.sh"],
                  env={"TECTONIC": "$D/fake18.sh", "TECTDIST_SKIP_PAIRING": ""},
                  want=1, stderr_contains="requires tectonic 0.17.x"))
CASES.append(Case(name="pairing bypass env var", section=SEC_PAIR, tier="mock",
                  cmd=["$B/pdflatex", "tiny.tex"],
                  setup={"fake18.sh": FAKE18}, chmod=["fake18.sh"],
                  env={"TECTONIC": "$D/fake18.sh", "TECTDIST_SKIP_PAIRING": "1"},
                  want=0, want_args=["tiny.tex"]))
CASES.append(Case(name="doctor ok", section=SEC_PAIR, tier="mock",
                  cmd=["$B/tectdist", "doctor"],
                  setup={"fake17.sh": FAKE17}, chmod=["fake17.sh"],
                  env={"TECTONIC": "$D/fake17.sh"},
                  want=0, stdout_contains="PAIR OK",
                  stdout_contains2="declared:"))
CASES.append(Case(name="doctor mismatch", section=SEC_PAIR, tier="mock",
                  cmd=["$B/tectdist", "doctor"],
                  setup={"fake18.sh": FAKE18}, chmod=["fake18.sh"],
                  env={"TECTONIC": "$D/fake18.sh"},
                  want=1, stdout_contains="MISMATCH"))

# --- C. translation: exact engine argv --------------------------------------
CASES.append(mock("synctex=1 -> --synctex", SEC_TRANS, ["-synctex=1"],
                  want_args=["--synctex", "-o .", "tiny.tex"]))
CASES.append(mock("synctex sep -> --synctex", SEC_TRANS, ["-synctex", "1"],
                  want_args=["--synctex"]))
CASES.append(mock("synctex=0 -> no --synctex", SEC_TRANS, ["-synctex=0"],
                  want_not_args=["--synctex"]))
CASES.append(mock("shell-escape -> -Z shell-escape", SEC_TRANS, ["-shell-escape"],
                  want_args=["-Z shell-escape"]))
CASES.append(mock("enable-write18 -> -Z shell-escape", SEC_TRANS, ["-enable-write18"],
                  want_args=["-Z shell-escape"]))
CASES.append(mock("no-shell-escape -> nothing", SEC_TRANS, ["-no-shell-escape"],
                  want_not_args=["shell-escape"]))
CASES.append(mock("output-directory= -> -o DIR", SEC_TRANS, ["-output-directory=od1"],
                  want_args=["-o od1"]))
CASES.append(mock("outdir= -> -o DIR", SEC_TRANS, ["-outdir=od3"], want_args=["-o od3"]))
CASES.append(mock("aux-directory= -> -o DIR", SEC_TRANS, ["-aux-directory=od4"],
                  want_args=["-o od4"]))
CASES.append(mock("no outdir -> -o .", SEC_TRANS, [], want_args=["-o ."]))
CASES.append(mock("jobname never reaches engine", SEC_TRANS, ["-jobname=job1"],
                  want_not_args=["job1"]))
CASES.append(mock("include-directory= -> search-path", SEC_TRANS,
                  ["-include-directory=$D/styles", "useone.tex"],
                  want_args=["-Z", "search-path=$D/styles"], input=None))
CASES.append(mock("-I sep -> search-path", SEC_TRANS, ["-I", "$D/styles", "usetwo.tex"],
                  want_args=["-Z", "search-path=$D/styles"], input=None))
CASES.append(mock("-I attached -> search-path", SEC_TRANS, ["-I$D/styles", "usethree.tex"],
                  want_args=["search-path=$D/styles"], input=None))
CASES.append(mock("-I= -> search-path", SEC_TRANS, ["-I=$D/styles", "usefour.tex"],
                  want_args=["search-path=$D/styles"], input=None))
CASES.append(mock("-fmt -> -f", SEC_TRANS, ["-fmt", "latex"], want_args=["-f", "latex"]))
CASES.append(mock("-format= -> -f", SEC_TRANS, ["-format=latex"], want_args=["-f", "latex"]))
CASES.append(mock("-fmt=xelatex dropped", SEC_TRANS, ["-fmt=xelatex"],
                  want_not_args=["xelatex"]))
CASES.append(mock("auxdir= -> -o DIR", SEC_TRANS, ["-auxdir=od5"], want_args=["-o od5"]))
CASES.append(mock("auxdir sep -> -o DIR", SEC_TRANS, ["-auxdir", "od6"],
                  want_args=["-o od6"]))
CASES.append(mock("interaction space batchmode", SEC_TRANS,
                  ["-interaction", "batchmode"], want_args=["--chatter minimal"]))
CASES.append(mock("synctex does not swallow next flag", SEC_TRANS,
                  ["-synctex", "-shell-escape"],
                  want_args=["-Z shell-escape"], want_not_args=["--synctex"]))
CASES.append(mock("TEXINPUTS trailing colon -> cwd", SEC_TRANS, [],
                  env={"TEXINPUTS": "$D/styles:"}, want_args=["search-path=."]))
CASES.append(mock("TEXINPUTS -> search-path", SEC_TRANS, ["usefive.tex"],
                  env={"TEXINPUTS": "$D/styles"}, want_args=["search-path=$D/styles"],
                  input=None))
CASES.append(mock("BIBINPUTS -> search-path", SEC_TRANS, [],
                  env={"BIBINPUTS": "$D/styles"}, want_args=["search-path=$D/styles"]))
CASES.append(mock("native -o forwarded", SEC_TRANS, ["-o", "nat"],
                  want_args=["-o nat", "tiny.tex"]))
CASES.append(mock("native --outdir= -> -o", SEC_TRANS, ["--outdir=nat2"],
                  want_args=["-o nat2"]))
CASES.append(mock("native --chatter= forwarded", SEC_TRANS, ["--chatter=minimal"],
                  want_args=["--chatter=minimal"]))
CASES.append(mock("native -r 1 forwarded", SEC_TRANS, ["-r", "1"],
                  want_args=["-r", "1"]))
CASES.append(mock("native --reruns= forwarded", SEC_TRANS, ["--reruns=2"],
                  want_args=["--reruns=2"]))
CASES.append(mock("native --makefile-rules forwarded", SEC_TRANS,
                  ["--makefile-rules=rules.mk"], want_args=["--makefile-rules=rules.mk"]))
CASES.append(mock("native -Zpaper-size forwarded", SEC_TRANS, ["-Zpaper-size=a4"],
                  want_args=["-Zpaper-size=a4"]))
CASES.append(mock("native -C forwarded", SEC_TRANS, ["-C"], want_args=["-C"]))
CASES.append(mock("native --untrusted forwarded", SEC_TRANS, ["--untrusted"],
                  want_args=["--untrusted"]))
CASES.append(mock("TECTONIC override forwards args", SEC_TRANS,
                  ["-interaction=nonstopmode", "-synctex=1", "-jobname=zz"],
                  want_args=["--synctex", "-o .", "tiny.tex"], want_not_args=["zz"]))

# --- D. dispatcher mechanics ------------------------------------------------
CASES.append(mock("end-of-options --", SEC_DISP, ["--"], want_args=["--", "tiny.tex"]))
CASES.append(mock("flags after input", SEC_DISP, ["tiny.tex", "-synctex=1", "-jobname=late"],
                  want_args=["--synctex"], want_not_args=["late"], input=None))
CASES.append(mock("combined everything", SEC_DISP,
                  ["-interaction=nonstopmode", "-file-line-error", "-synctex=1",
                   "-halt-on-error", "-shell-escape", "-recorder", "-jobname=deck",
                   "-output-directory=build"],
                  want_args=["--synctex", "-Z shell-escape", "-o build", "tiny.tex"],
                  want_not_args=["deck"]))
CASES.append(mock("multiple jobname last wins", SEC_DISP,
                  ["-jobname=first", "-jobname=second"]))
CASES.append(mock("extensionless resolves to .tex", SEC_DISP, ["tiny"],
                  want_args=["tiny.tex"], input=None))
CASES.append(mock("file with spaces", SEC_DISP, ["my doc.tex"],
                  want_args=["my doc.tex"], input=None))
CASES.append(mock("foreign input pins cwd", SEC_DISP,
                  ["-interaction=nonstopmode", "../tiny.tex"], cwd="other",
                  want_args=["-o .", "../tiny.tex"], input=None))
CASES.append(mock("stdin passed as final arg", SEC_DISP,
                  ["-interaction=nonstopmode", "-"], stdin=STDIN_DOC,
                  want_last="-", input=None))
CASES.append(mock("stdin+jobname", SEC_DISP, ["-interaction=nonstopmode", "-jobname=stdin", "-"],
                  stdin=STDIN_DOC, want_last="-", want_not_args=["stdin"],
                  input=None))

# --- E. engine farm: every name dispatches ----------------------------------
for e in ENGINES:
    CASES.append(mock(f"engine {e}", SEC_FARM, ["-interaction=nonstopmode"], prog=e))

# --- F. latexmk interface ---------------------------------------------------
CASES.append(Case(name="latexmk --version", section=SEC_LMK_MOCK, tier="mock",
                  cmd=["$B/latexmk", "--version"]))
CASES.append(mock("latexmk -pdf reaches engine", SEC_LMK_MOCK,
                  ["-pdf", "tiny.tex"], prog="latexmk", want_args=["tiny.tex"]))
CASES.append(mock("latexmk forwards synctex+outdir", SEC_LMK_MOCK,
                  ["-pdf", "-synctex=1", "-file-line-error", "-shell-escape",
                   "-outdir=lm", "tiny.tex"],
                  prog="latexmk", want_args=["--synctex", "-o lm"]))
CASES.append(mock("latexmk jobname dropped", SEC_LMK_MOCK,
                  ["-pdf", "-jobname=lmjob", "tiny.tex"], prog="latexmk",
                  want_not_args=["lmjob"]))
for eng in ("-xelatex", "-pdflua"):
    CASES.append(mock(f"latexmk {eng} dispatches", SEC_LMK_MOCK,
                      [eng, "tiny.tex"], prog="latexmk", want_args=["tiny.tex"]))
CASES.append(Case(name="latexmk missing input", section=SEC_LMK_MOCK, tier="mock",
                  cmd=["$B/latexmk", "-pdf", "nope.tex"], want=1))
# clean modes need no engine
CASES.append(Case(name="latexmk -c keeps pdf, drops aux", section=SEC_LMK_MOCK, tier="mock",
                  cmd=["$B/latexmk", "-c", "tiny.tex"],
                  setup={"tiny.aux": "aux", "tiny.log": "log", "tiny.pdf": "pdf"},
                  want_files=["tiny.pdf"], no_files=["tiny.aux", "tiny.log"]))
CASES.append(Case(name="latexmk -c outdir cleans only outdir", section=SEC_LMK_MOCK,
                  tier="mock",
                  cmd=["$B/latexmk", "-c", "-outdir=build", "tiny.tex"],
                  setup={"tiny.aux": "aux", "tiny.log": "log",
                         "build/tiny.aux": "aux", "build/tiny.log": "log",
                         "build/.keep": ""},
                  want_files=["tiny.aux", "tiny.log", "build/.keep"],
                  no_files=["build/tiny.aux", "build/tiny.log"]))
CASES.append(Case(name="latexmk -C removes all", section=SEC_LMK_MOCK, tier="mock",
                  cmd=["$B/latexmk", "-C", "tiny.tex"],
                  setup={"tiny.aux": "aux", "tiny.pdf": "pdf"},
                  no_files=["tiny.aux", "tiny.pdf"]))
# .latexmkrc handling
CASES.append(mock("latexmk reads .latexmkrc out_dir", SEC_LMK_MOCK, ["-pdf", "tiny.tex"],
                  prog="latexmk", rc_file='$out_dir = "rcout";\n',
                  want_args=["-o rcout"]))
CASES.append(mock("latexmk extensionless input", SEC_LMK_MOCK,
                  ["-pdf", "tiny"], prog="latexmk", want_args=["tiny.tex"],
                  input=None))
CASES.append(mock("latexmk -norc honors explicit -r", SEC_LMK_MOCK,
                  ["-pdf", "-norc", "-r", "$D/my.rc", "tiny.tex"], prog="latexmk",
                  setup={"my.rc": '$out_dir = "fromrc";\n'},
                  want_args=["-o fromrc"], input=None))
CASES.append(mock("latexmk CLI overrides rc", SEC_LMK_MOCK,
                  ["-pdf", "-outdir=cliout", "tiny.tex"], prog="latexmk",
                  rc_file='$out_dir = "rcout";\n', want_args=["-o cliout"]))
CASES.append(mock("latexmk -norc ignores rc", SEC_LMK_MOCK, ["-pdf", "-norc", "tiny.tex"],
                  prog="latexmk", rc_file='$out_dir = "rcout";\n',
                  want_not_args=["rcout"]))

# --- G. stubs, kpsewhich, maintenance ---------------------------------------
for x in STUB_BIB + STUB_DVI + STUB_FNT:
    CASES.append(Case(name=f"{x} noop", section=SEC_STUBS, tier="mock",
                      cmd=["$B/" + x, "whatever"]))
for x in STUB_MNT:
    CASES.append(Case(name=f"{x} noop", section=SEC_STUBS, tier="mock",
                      cmd=["$B/" + x]))
# honest stub wording: nothing claims Tectonic "performs" the index step;
# with no real binary installed the proxy-or-stub names fall back to an
# exit-0 note (PATH is pinned so a machine with TeX tools doesn't proxy)
def _has_real(prog):
    # like tools.resolve_real: a PATH hit that is the tectdist farm launcher
    # itself (e.g. /opt/homebrew/bin/makeindex -> the keg's farm symlink) is
    # not a real binary and must not gate indexer cases
    self_real = os.path.realpath(os.path.join(BIN, "tectdist"))

    def good(p):
        if not p or not os.path.isfile(p) or not os.access(p, os.X_OK):
            return False
        rp = os.path.realpath(p)
        return rp != self_real and os.path.basename(rp) != "tectdist"

    for d in os.environ.get("PATH", "").split(os.pathsep):
        if d and good(os.path.join(d, prog)):
            return True
    return any(good(p) for p in (f"/opt/homebrew/bin/{prog}",
                                 f"/usr/local/bin/{prog}",
                                 f"/usr/bin/{prog}"))

def _absent_stub(prog, args, frag):
    c = Case(name=f"{prog} stub when absent", section=SEC_STUBS, tier="mock",
             cmd=["$B/" + prog] + args,
             env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
             stderr_contains=frag)
    return c if not _has_real(prog) else c.skip(f"real {prog} present")

CASES.append(_absent_stub("makeindex", ["x.idx"], "no real makeindex binary"))
CASES.append(_absent_stub("xindy", ["x.idx"], "no real xindy binary"))
CASES.append(_absent_stub("upmendex", ["x.idx"], "no real upmendex binary"))
CASES.append(_absent_stub("biber", ["x.bcf"], "no real biber binary"))
CASES.append(Case(name="bibtex stub internal", section=SEC_STUBS, tier="mock",
                  cmd=["$B/bibtex", "x.aux"],
                  stderr_contains="built-in BiBTeX"))

# proxy-or-stub forward path: with the farm first on PATH (the normal install
# layout) and a real binary later on PATH, the command must proxy to it
PROXY_TOOL = """#!/bin/bash
echo "$@" > proxied.log
echo "ran with: $*"
exit 0
"""

def _proxy_case(prog, args):
    c = Case(name=f"{prog} proxies to real binary", section=SEC_STUBS, tier="mock",
             cmd=["$B/" + prog] + args,
             setup={"fakebin/" + prog: PROXY_TOOL},
             chmod=["fakebin/" + prog],
             env={"PATH": BIN + os.pathsep + "$D/fakebin" + os.pathsep
                  + os.environ.get("PATH", "")},
             want_files=["proxied.log"],
             stdout_contains="ran with: " + " ".join(args))
    return c if not _has_real(prog) else c.skip(f"real {prog} present")

CASES.append(_proxy_case("makeindex", ["foo.idx", "foo"]))
CASES.append(_proxy_case("xindy", ["-M", "xstyle", "x.idx"]))
CASES.append(_proxy_case("upmendex", ["x.idx"]))
CASES.append(_proxy_case("biber", ["probe.bcf"]))

# --- G2. makeindex rerun loop (mock) ---------------------------------------
# a custom fake engine that appends argv per run, writes tiny.idx on the first
# run and tiny.pdf on any later run; a fake makeindex that writes tiny.ind
LOOP_ENGINE = """#!/bin/bash
echo "$@" >> argv.log
if [ -f tiny.idx ]; then
  echo "%pdf" > tiny.pdf
else
  touch tiny.idx
fi
exit 0
"""
FAKE_MK = """#!/bin/bash
echo "ran" > makeindex-ran.log
echo "%ind" > tiny.ind
exit 0
"""
CASES.append(Case(name="index loop runs makeindex and reruns", section=SEC_LOOP,
                  tier="mock",
                  cmd=["$B/pdflatex", "-interaction=nonstopmode", "tiny.tex"],
                  setup={"engine.sh": LOOP_ENGINE, "fakebin/makeindex": FAKE_MK},
                  chmod=["engine.sh", "fakebin/makeindex"],
                  env={"TECTONIC": "$D/engine.sh",
                       "PATH": "$D/fakebin:" + os.environ.get("PATH", "")},
                  want_files=["tiny.idx", "tiny.ind", "tiny.pdf",
                              "makeindex-ran.log"],
                  want_runs=2, want_args=["search-path=."]))
CASES.append(mock("plain compile single run (no idx)", SEC_LOOP,
                  ["-interaction=nonstopmode"], want_runs=1))
# no indexer anywhere (makeindex or upmendex): compile must succeed, warn,
# and not rerun
_real_mk = _has_real("makeindex")
_real_up = _has_real("upmendex")
_no_idx = Case(name="index loop no indexer warns", section=SEC_LOOP, tier="mock",
               cmd=["$B/pdflatex", "-interaction=nonstopmode", "tiny.tex"],
               setup={"engine.sh": LOOP_ENGINE},
               chmod=["engine.sh"],
               env={"TECTONIC": "$D/engine.sh",
                    "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
               want_files=["tiny.idx"], want_runs=1,
               want_not_args=["search-path"],
               stderr_contains="index will not be built")
CASES.append(_no_idx if not (_real_mk or _real_up)
             else _no_idx.skip("real makeindex/upmendex present"))
# upmendex fallback: no makeindex anywhere, fake upmendex first on PATH -> the
# loop must run it and rerun the engine so the .ind gets \@input
FAKE_UP = """#!/bin/bash
echo "ran" > upmendex-ran.log
echo "%ind" > tiny.ind
exit 0
"""
_up_fb = Case(name="index loop falls back to upmendex", section=SEC_LOOP,
              tier="mock",
              cmd=["$B/pdflatex", "-interaction=nonstopmode", "tiny.tex"],
              setup={"engine.sh": LOOP_ENGINE, "fakebin/upmendex": FAKE_UP},
              chmod=["engine.sh", "fakebin/upmendex"],
              env={"TECTONIC": "$D/engine.sh",
                   "PATH": "$D/fakebin:/usr/bin:/bin:/usr/sbin:/sbin"},
              want_files=["tiny.idx", "tiny.ind", "tiny.pdf",
                          "upmendex-ran.log"],
              want_runs=2, want_args=["search-path=."])
CASES.append(_up_fb if not (_real_mk or _real_up)
             else _up_fb.skip("real makeindex/upmendex present"))
CASES.append(Case(name="tlmgr --version", section=SEC_STUBS, tier="mock",
                  cmd=["$B/tlmgr", "--version"]))
CASES.append(Case(name="tlmgr install refused", section=SEC_STUBS, tier="mock",
                  cmd=["$B/tlmgr", "install", "somemacro"], want=1))
CASES.append(Case(name="tlmgr no args", section=SEC_STUBS, tier="mock",
                  cmd=["$B/tlmgr"], want=1))
CASES.append(Case(name="texdoc", section=SEC_STUBS, tier="mock",
                  cmd=["$B/texdoc", "article"]))
CASES.append(Case(name="kpsewhich found", section=SEC_STUBS, tier="mock",
                  cmd=["$B/kpsewhich", "tiny.tex"], stdout_exact="tiny.tex"))
CASES.append(Case(name="kpsewhich abs", section=SEC_STUBS, tier="mock",
                  cmd=["$B/kpsewhich", "$D/tiny.tex"], stdout_exact="$D/tiny.tex"))
CASES.append(Case(name="kpsewhich missing", section=SEC_STUBS, tier="mock",
                  cmd=["$B/kpsewhich", "nope.tex"], want=1))
CASES.append(Case(name="kpsewhich -var-value", section=SEC_STUBS, tier="mock",
                  cmd=["$B/kpsewhich", "-var-value", "TEXINPUTS"],
                  env={"TEXINPUTS": "$D/styles"}, stdout_exact="$D/styles"))
CASES.append(Case(name="kpsewhich unknown var", section=SEC_STUBS, tier="mock",
                  cmd=["$B/kpsewhich", "-var-value", "NOSUCHVAR_XYZ"],
                  want=1, stdout_exact=""))
CASES.append(Case(name="kpsewhich -format=", section=SEC_STUBS, tier="mock",
                  cmd=["$B/kpsewhich", "-format=tex", "tiny.tex"],
                  stdout_exact="tiny.tex"))
CASES.append(Case(name="kpsewhich --version", section=SEC_STUBS, tier="mock",
                  cmd=["$B/kpsewhich", "--version"]))
CASES.append(Case(name="kpsewhich --help", section=SEC_STUBS, tier="mock",
                  cmd=["$B/kpsewhich", "--help"]))
CASES.append(Case(name="kpsewhich TEXINPUTS", section=SEC_STUBS, tier="mock",
                  cmd=["$B/kpsewhich", "mystyle.sty"], env={"TEXINPUTS": "$D/styles"},
                  stdout_contains="mystyle"))

# --- H. real engine behaviour -----------------------------------------------
if not (HAVE_ENGINE := find_engine()):
    ENGINE_NOTE = "tectonic engine not available (set TECTONIC or install tectonic)"
else:
    ENGINE_NOTE = ""

real_section = SEC_REAL


def real_flags(*flags):
    return list(flags)


CASES.append(real("basic compile", SEC_REAL, ["-interaction=nonstopmode"],
                  want_files=["tiny.pdf"]))
CASES.append(real("synctex=1", SEC_REAL, ["-interaction=nonstopmode", "-synctex=1"],
                  want_files=["tiny.synctex.gz"]))
CASES.append(real("jobname=", SEC_REAL, ["-interaction=nonstopmode", "-jobname=job1"],
                  want_files=["job1.pdf"]))
CASES.append(real("multiple jobname last wins", SEC_REAL,
                  ["-interaction=nonstopmode", "-jobname=first", "-jobname=second"],
                  want_files=["second.pdf"]))
CASES.append(real("output-directory=", SEC_REAL,
                  ["-interaction=nonstopmode", "-output-directory=od1"],
                  want_files=["od1/tiny.pdf"]))
CASES.append(real("outdir=", SEC_REAL, ["-interaction=nonstopmode", "-outdir=od3"],
                  want_files=["od3/tiny.pdf"]))
CASES.append(real("aux-directory=", SEC_REAL,
                  ["-interaction=nonstopmode", "-aux-directory=od4"],
                  want_files=["od4/tiny.pdf"]))
CASES.append(real("combined everything", SEC_REAL,
                  ["-interaction=nonstopmode", "-file-line-error", "-synctex=1",
                   "-halt-on-error", "-shell-escape", "-recorder", "-jobname=deck",
                   "-output-directory=build"],
                  want_files=["build/deck.pdf", "build/deck.synctex.gz"]))
CASES.append(real("extensionless input", SEC_REAL, ["-interaction=nonstopmode", "tiny"],
                  want_files=["tiny.pdf"], input=None))
CASES.append(real("file with spaces", SEC_REAL,
                  ["-interaction=nonstopmode", "my doc.tex"], want_files=["my doc.pdf"],
                  input=None))
CASES.append(real("foreign input -> cwd output", SEC_REAL,
                  ["-interaction=nonstopmode", "../tiny.tex"], cwd="other",
                  want_files=["tiny.pdf"], input=None))
CASES.append(real("stdin compile", SEC_REAL, ["-interaction=nonstopmode", "-"],
                  stdin=STDIN_DOC, want_files=["texput.pdf"], input=None))
CASES.append(real("stdin with jobname", SEC_REAL,
                  ["-interaction=nonstopmode", "-jobname=stdin", "-"],
                  stdin=STDIN_DOC, want_files=["stdin.pdf"], input=None))
CASES.append(real("auxdir real", SEC_REAL, ["-interaction=nonstopmode", "-auxdir=od5"],
                  want_files=["od5/tiny.pdf"]))
CASES.append(real("fmt unsupported value still compiles", SEC_REAL,
                  ["-fmt=xelatex", "-interaction=nonstopmode"], want_files=["tiny.pdf"]))
CASES.append(real("jobname path sanitized", SEC_REAL,
                  ["-interaction=nonstopmode", "-jobname=sub/x"],
                  want_files=["x.pdf"]))
CASES.append(real("include-directory real", SEC_REAL,
                  ["-interaction=nonstopmode", "-include-directory=$D/styles", "useone.tex"],
                  input=None))
CASES.append(Case(name="pdfcrop bad margins graceful", section=SEC_GS, tier="real",
                  cmd=["$B/pdfcrop", "--margins", "notanumber", "tiny.pdf", "o.pdf"],
                  want=1, need_pdf=True))
CASES.append(real("TEXINPUTS real", SEC_REAL, ["-interaction=nonstopmode", "usefive.tex"],
                  env={"TEXINPUTS": "$D/styles"}, input=None))
CASES.append(real("TECTONIC override real", SEC_REAL, ["-interaction=nonstopmode"],
                  env={"TECTONIC": "$ENGINE"}, want_files=["tiny.pdf"]))
CASES.append(real("error doc -> non-zero", SEC_REAL,
                  ["-interaction=nonstopmode", "-halt-on-error", "bad.tex"], want=1,
                  input=None))
CASES.append(real("missing file -> non-zero", SEC_REAL,
                  ["-interaction=nonstopmode", "missing.tex"], want=1, input=None))
CASES.append(real("no args -> non-zero", SEC_REAL, [], want=2, input=None))
CASES.append(real("index end-to-end (makeindex)", SEC_REAL,
                  ["-interaction=nonstopmode"],
                  setup={"tiny.tex": INDEX_DOC},
                  want_files=["tiny.idx", "tiny.ind", "tiny.pdf"],
                  skip_reason="" if _has_real("makeindex") else "makeindex not found"))
CASES.append(real("index end-to-end (upmendex)", SEC_REAL,
                  ["-interaction=nonstopmode"],
                  setup={"tiny.tex": INDEX_DOC},
                  want_files=["tiny.idx", "tiny.ind", "tiny.pdf"],
                  pdf_contains="alpha",
                  skip_reason="" if _has_real("upmendex") else "upmendex not found"))
CASES.append(real("biblatex end-to-end (biber)", SEC_REAL,
                  ["-interaction=nonstopmode"],
                  setup={"tiny.tex": BIBLIO_DOC, "refs.bib": BIBLIO_BIB},
                  want_files=["tiny.pdf"],
                  pdf_contains="TeXbook",
                  skip_reason="" if have("biber") else "biber not found",
                  skip_if_stderr="versions are incompatible"))
CASES.append(real("-C only-cached", SEC_REAL, ["-C", "-interaction=nonstopmode"]))
CASES.append(real("--chatter=minimal", SEC_REAL, ["--chatter=minimal", "-interaction=nonstopmode"]))
CASES.append(real("-r 1 reruns", SEC_REAL, ["-r", "1", "-interaction=nonstopmode"]))
CASES.append(real("--reruns=2", SEC_REAL, ["--reruns=2", "-interaction=nonstopmode"]))
CASES.append(real("-k keep-intermediates", SEC_REAL, ["-k", "-interaction=nonstopmode"],
                  want_files=["tiny.aux"]))
CASES.append(real("native -o outdir", SEC_REAL, ["-o", "nat", "-interaction=nonstopmode"],
                  want_files=["nat/tiny.pdf"], setup={"nat/.keep": ""}))
CASES.append(real("native --outdir=", SEC_REAL, ["--outdir=nat2", "-interaction=nonstopmode"],
                  want_files=["nat2/tiny.pdf"]))
CASES.append(real("-Z shell-escape native", SEC_REAL,
                  ["-Z", "shell-escape", "-interaction=nonstopmode"]))
CASES.append(real("--makefile-rules", SEC_REAL,
                  ["--makefile-rules=rules.mk", "-interaction=nonstopmode"],
                  want_files=["rules.mk"]))
for e in ("xelatex", "lualatex"):
    CASES.append(real(f"engine {e} real", SEC_REAL, ["-interaction=nonstopmode"],
                      prog=e, want_files=["tiny.pdf"]))

# --- I. latexmk end-to-end --------------------------------------------------
CASES.append(real("latexmk -pdf basic", SEC_LMK_REAL, ["-pdf", "-interaction=nonstopmode"],
                  prog="latexmk", want_files=["tiny.pdf"]))
CASES.append(real("latexmk outdir+synctex", SEC_LMK_REAL,
                  ["-pdf", "-synctex=1", "-file-line-error", "-shell-escape",
                   "-outdir=lm", "tiny.tex"], prog="latexmk",
                  want_files=["lm/tiny.pdf", "lm/tiny.synctex.gz"]))
CASES.append(real("latexmk jobname", SEC_LMK_REAL, ["-pdf", "-jobname=lmjob", "tiny.tex"],
                  prog="latexmk", want_files=["lmjob.pdf"]))
CASES.append(real("latexmk -pvc runs once", SEC_LMK_REAL, ["-pdf", "-pvc", "tiny.tex"],
                  prog="latexmk", want_files=["tiny.pdf"]))
CASES.append(real("latexmk reads .latexmkrc", SEC_LMK_REAL,
                  ["-pdf", "-interaction=nonstopmode", "tiny.tex"], prog="latexmk",
                  rc_file='$out_dir = "rcout";\n', want_files=["rcout/tiny.pdf"]))
CASES.append(real("latexmk CLI overrides rc", SEC_LMK_REAL,
                  ["-pdf", "-interaction=nonstopmode", "-outdir=cliout", "tiny.tex"],
                  prog="latexmk", rc_file='$out_dir = "rcout";\n',
                  want_files=["cliout/tiny.pdf"]))
CASES.append(real("latexmk -norc ignores rc", SEC_LMK_REAL,
                  ["-pdf", "-norc", "-interaction=nonstopmode", "tiny.tex"],
                  prog="latexmk", want_files=["tiny.pdf"]))
CASES.append(real("latexmk -xelatex", SEC_LMK_REAL,
                  ["-xelatex", "-interaction=nonstopmode", "tiny.tex"],
                  prog="latexmk", want_files=["tiny.pdf"]))

# --- J. gs tools ------------------------------------------------------------
if have("gs"):
    GS_NOTE = ""
else:
    GS_NOTE = "ghostscript (gs) not found"

gs_flags = [("-epstopdf", ["test.eps"], ["test.pdf"]),
            ("-epstopdf -o", ["-o", "eps2.pdf", "test.eps"], ["eps2.pdf"]),
            ("-eps2eps", ["test.eps", "test2.eps"], ["test2.eps"]),
            ("-ps2pdf", ["test.ps"], ["test.pdf"]),
            ("-ps2pdf named", ["test.ps", "named.pdf"], ["named.pdf"]),
            ("-pdfcrop", ["tiny.pdf"], ["tiny-crop.pdf"]),
            ("-pdfcrop margins", ["--margins", "5 5 5 5", "tiny.pdf", "crop5.pdf"],
             ["crop5.pdf"])]
for name, flags, wantf in gs_flags:
    setup = {"test.eps": EPS, "test.ps": PS}
    CASES.append(Case(name=f"gs {name}", section=SEC_GS, tier="real",
                      cmd=["$B/epstopdf" if "epstopdf" in name or "eps2eps" in name else
                           "$B/ps2pdf" if "ps2pdf" in name else "$B/pdfcrop"] + flags,
                      want_files=wantf, setup=setup, need_pdf=("pdfcrop" in name)))

# --- K. poppler/qpdf proxies -------------------------------------------------
CASES.append(Case(name="pdfinfo proxy", section=SEC_PROXY, tier="real",
                  cmd=["$B/pdfinfo", "tiny.pdf"], stdout_contains="Pages", need_pdf=True))
CASES.append(Case(name="pdftotext proxy", section=SEC_PROXY, tier="real",
                  cmd=["$B/pdftotext", "tiny.pdf", "-"], stdout_contains="Hello",
                  need_pdf=True))
CASES.append(Case(name="pdfunite proxy", section=SEC_PROXY, tier="real",
                  cmd=["$B/pdfunite", "tiny.pdf", "tiny.pdf", "united.pdf"],
                  want_files=["united.pdf"], need_pdf=True))
CASES.append(Case(name="qpdf proxy", section=SEC_PROXY, tier="real",
                  cmd=["$B/qpdf", "--check", "tiny.pdf"], need_pdf=True))

# gate real sections on engine availability
if not HAVE_ENGINE:
    for c in CASES:
        if c.tier == "real" and not c.skip_reason:
            c.skip(ENGINE_NOTE)
for c in CASES:
    if c.section == SEC_GS and not c.skip_reason and GS_NOTE:
        c.skip(GS_NOTE)
    if c.section == SEC_PROXY and not c.skip_reason:
        tool = os.path.basename(c.cmd[0].replace("$B/", ""))
        if not have(tool):
            c.skip(f"{tool} not found")
        elif not HAVE_ENGINE:
            c.skip(ENGINE_NOTE)
    if c.tier == "real" and c.pdf_contains and not c.skip_reason \
            and not have("pdftotext"):
        c.skip("pdftotext not found")


# =============================================================================
# execution
# =============================================================================
def resolve(cmd, case_dir, engine):
    out = []
    for a in cmd:
        a = a.replace("$B", BIN).replace("$D", case_dir).replace("$ENGINE", engine)
        out.append(a)
    return out


def run_case(case, work_root, fake, engine, tiny_pdf):
    if case.skip_reason:
        return case, "skip", case.skip_reason
    d = os.path.join(work_root, case.section.split(":")[0].strip(),
                     f"{abs(hash(case.name)) % 10**9}-{case.name.replace(' ', '_')[:60]}")
    os.makedirs(d, exist_ok=True)
    for fname, content in FIXTURE_TEX.items():
        with open(os.path.join(d, fname), "w") as f:
            f.write(content)
    os.makedirs(os.path.join(d, "styles"), exist_ok=True)
    for fname, content in STYLES.items():
        with open(os.path.join(d, "styles", fname), "w") as f:
            f.write(content)
    if case.rc_file:
        with open(os.path.join(d, ".latexmkrc"), "w") as f:
            f.write(case.rc_file)
    for fname, content in case.setup.items():
        full = os.path.join(d, fname)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(content)
    for p in case.chmod:
        os.chmod(os.path.join(d, p), 0o755)
    if case.need_pdf and tiny_pdf:
        shutil.copy(tiny_pdf, os.path.join(d, "tiny.pdf"))

    env = os.environ.copy()
    if case.tier == "mock":
        env["TECTONIC"] = fake
        env["FAKELOG"] = os.path.join(d, "argv.log")
        # the pairing check probes `tectonic --version`, which would pollute
        # the recording fake engines; it is exercised only by its own
        # section (SEC_PAIR) and against the real engine in [real] cases
        if case.section != SEC_PAIR:
            env["TECTDIST_SKIP_PAIRING"] = "1"
    env.update({k: v.replace("$D", d).replace("$ENGINE", engine) for k, v in case.env.items()})
    cwd = os.path.join(d, case.cwd) if case.cwd else d
    os.makedirs(cwd, exist_ok=True)
    cmd = resolve(case.cmd, d, engine)

    try:
        if case.stdin is not None:
            p = subprocess.run(cmd, cwd=cwd, env=env, input=case.stdin,
                               capture_output=True, text=True, timeout=30)
        else:
            p = subprocess.run(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                               capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        return case, "fail", "TIMEOUT after 30s"

    problems = []
    if case.want is not None and p.returncode != case.want:
        problems.append(f"exit {p.returncode}/{case.want}")
    for wf in case.want_files:
        if not os.path.exists(os.path.join(cwd, wf)):
            problems.append(f"missing {wf}")
    for nf in case.no_files:
        if os.path.exists(os.path.join(cwd, nf)):
            problems.append(f"unexpected {nf}")
    if case.stdout_exact is not None and p.stdout.strip() != case.stdout_exact.replace("$D", d):
        problems.append(f"stdout {p.stdout.strip()!r} != {case.stdout_exact!r}")
    if case.stdout_contains and case.stdout_contains not in p.stdout:
        problems.append(f"stdout missing {case.stdout_contains!r}")
    if case.stdout_contains2 and case.stdout_contains2 not in p.stdout:
        problems.append(f"stdout missing {case.stdout_contains2!r}")
    if case.stderr_contains and case.stderr_contains not in p.stderr:
        problems.append(f"stderr missing {case.stderr_contains!r}")
    if case.pdf_contains:
        pdfs = sorted(glob.glob(os.path.join(cwd, "*.pdf")))
        if not pdfs:
            problems.append(f"pdf_contains={case.pdf_contains!r} but no PDF produced")
        elif have("pdftotext"):
            txt = subprocess.run([shutil.which("pdftotext"), pdfs[0], "-"],
                                 capture_output=True, text=True).stdout
            if case.pdf_contains not in txt:
                problems.append(f"PDF text missing {case.pdf_contains!r}")
    if problems and case.skip_if_stderr and case.skip_if_stderr in p.stderr:
        return case, "skip", f"environment: {case.skip_if_stderr!r} in stderr ({'; '.join(problems)})"
    log = ""
    if case.tier == "mock" and os.path.exists(os.path.join(d, "argv.log")):
        with open(os.path.join(d, "argv.log")) as f:
            log = f.read().strip()
        for pat in case.want_args:
            if pat.replace("$D", d) not in log:
                problems.append(f"args missing {pat!r} (got: {log or '(empty)'})")
        for pat in case.want_not_args:
            if pat in log:
                problems.append(f"args unexpected {pat!r} (got: {log})")
        if case.want_last is not None:
            last = log.split()[-1] if log.split() else ""
            if last != case.want_last:
                problems.append(f"last arg {last!r} != {case.want_last!r} (got: {log})")
        if case.want_runs is not None:
            runs = len([ln for ln in log.splitlines() if ln.strip()])
            if runs != case.want_runs:
                problems.append(f"engine runs {runs} != {case.want_runs} (got: {log})")
    return case, ("fail" if problems else "pass"), "; ".join(problems)


def main():
    # --- release gate: Formula/tectdist.rb mirrors src/tectdist/pairing.py ---
    # (the formula must declare the same pairing this software checks; see
    # RELEASING.md "Bumping the pairing")
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "src"))
    from tectdist import pairing as pairing_mod
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    formula = os.path.join(repo, "Formula", "tectdist.rb")
    gate_problems = []
    if os.path.isfile(formula):
        text = open(formula).read()
        m = __import__("re").search(r'TECTONIC_VERSION = "([0-9.]+)"', text)
        if not m or m.group(1) != pairing_mod.TECTONIC_VERSION:
            gate_problems.append(
                f"Formula TECTONIC_VERSION {m.group(1) if m else '(missing)'} "
                f"!= pairing.py {pairing_mod.TECTONIC_VERSION}")
        m2 = __import__("re").search(r'plk/biber/archive/refs/tags/v([0-9.]+)\.tar\.gz', text)
        if not m2 or m2.group(1) != pairing_mod.BIBER_VERSION:
            gate_problems.append(
                f"Formula biber resource v{m2.group(1) if m2 else '(missing)'} "
                f"!= pairing.py {pairing_mod.BIBER_VERSION}")
        if not __import__("re").search(r'reject \{ \|n\| n == "biber" \}', text):
            gate_problems.append("Formula install must exclude the biber resource "
                                 "from the module loop (reject biber)")
    else:
        gate_problems.append(f"Formula not found at {formula}")
    if gate_problems:
        print("RELEASE GATE FAILED:")
        for p in gate_problems:
            print("  - " + p)
        return 2

    ap = argparse.ArgumentParser(description="tectdist acceptance battery (stdlib Python 3)")
    ap = argparse.ArgumentParser(description="tectdist acceptance battery (stdlib Python 3)")
    ap.add_argument("--mock-only", action="store_true",
                    help="skip the [real] engine sections")
    ap.add_argument("--jobs", type=int, default=min(8, os.cpu_count() or 4),
                    help="parallel worker count (default: min(8, cpu count))")
    args = ap.parse_args()

    have_engine = bool(HAVE_ENGINE) and not args.mock_only
    engine = HAVE_ENGINE if have_engine else ""

    work_root = tempfile.mkdtemp(prefix="tdist-battery-")
    fake = os.path.join(work_root, "fake-engine.py")
    with open(fake, "w") as f:
        f.write(FAKE_SRC)
    os.chmod(fake, 0o755)

    # pre-compile tiny.pdf once for the gs/proxy sections
    tiny_pdf = ""
    if have_engine:
        d = os.path.join(work_root, "precompile")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "tiny.tex"), "w") as f:
            f.write(TINY)
        try:
            subprocess.run([os.path.join(BIN, "pdflatex"), "-interaction=nonstopmode",
                            "tiny.tex"], cwd=d, capture_output=True, timeout=60)
        except subprocess.TimeoutExpired:
            pass
        pdf = os.path.join(d, "tiny.pdf")
        if os.path.exists(pdf):
            tiny_pdf = pdf

    if not have_engine:
        note = ENGINE_NOTE or "tectonic engine not available"
        for c in CASES:
            if c.tier == "real" and not c.skip_reason:
                c.skip(note)

    start = time.monotonic()
    results = []
    if len(CASES) == 1:
        results = [run_case(CASES[0], work_root, fake, engine, tiny_pdf)]
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as ex:
            results = list(ex.map(lambda c: run_case(c, work_root, fake, engine, tiny_pdf),
                                  CASES))
    elapsed = time.monotonic() - start

    # group by section, preserving first-seen order
    order = []
    by_sec = {}
    for c in CASES:
        if c.section not in by_sec:
            by_sec[c.section] = []
            order.append(c.section)
    counts = {s: {"pass": 0, "fail": 0, "skip": 0} for s in order}
    for case, status, detail in results:
        counts[case.section][status] += 1
        if status == "fail":
            print(f"FAIL [{case.section}] {case.name}: {detail}")

    total = {"pass": 0, "fail": 0, "skip": 0}
    print()
    print("=" * 64)
    print(f" tectdist battery results  ({elapsed:.1f}s, jobs={args.jobs})")
    print("-" * 64)
    for s in order:
        c = counts[s]
        total["pass"] += c["pass"]
        total["fail"] += c["fail"]
        total["skip"] += c["skip"]
        print(f"  {s:<44} pass={c['pass']:<4} fail={c['fail']:<4} skip={c['skip']}")
    print("-" * 64)
    print(f"  TOTAL{'':<40} pass={total['pass']:<4} fail={total['fail']:<4} skip={total['skip']}")
    if total["fail"] == 0:
        print("  ALL GREEN")
        if total["skip"]:
            print(f"  (note: {total['skip']} checks skipped — run with tectonic/gs/"
                  "poppler installed to cover them)")
    else:
        print("  FAILURES PRESENT")
    print("=" * 64)
    shutil.rmtree(work_root, ignore_errors=True)
    return 0 if total["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
