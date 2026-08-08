"""latexmk (tectdist) — a build driver with the classic latexmk interface,
backed by the tectdist engine farm (which is backed by Tectonic).

Supports the flag vocabulary that editors and CI actually use:

  engine:    -pdf (default), -pdfxe/-xelatex, -pdflua/-lualatex, -latex,
             -dvi/-ps (warn, produce PDF), -pdflatex=CMD / -latex=CMD ...
  forwarded: -interaction=..., -synctex=N, -file-line-error, -halt-on-error,
             -shell-escape, -no-shell-escape, -recorder, -8bit, -etex
  paths:     -outdir=, -output-directory=, -auxdir=, -aux-directory=
             (Tectonic uses a single output dir, so aux == out)
  jobname:   -jobname=NAME
  clean:     -c (remove aux files, keep PDF), -C (also remove the PDF)
  misc:      -q, -norc, -r FILE / -rc FILE, -pvc (runs once, warns),
             --version, --help

A .latexmkrc / latexmkrc in the working directory is read for the common
simple assignments: $pdf_mode, $pdflatex, $xelatex, $lualatex, $out_dir,
$jobname, $bibtex_use.

Tectonic already reruns LaTeX internally as needed, so latexmk runs the
engine once per invocation.
"""

import os
import re
import shlex
import shutil
import subprocess
import sys

from .version import VERSION

KNOWN_ENGINES = ("pdflatex", "latex", "xelatex", "lualatex", "platex",
                 "uplatex", "pdftex", "tex", "etex", "luatex", "luahbtex",
                 "pdfetex", "xetex")

CLEAN_EXTS = ("aux log out toc lof lot nav snm bbl blg idx ilg ind fls "
              "fdb_latexmk synctex.gz vrb spl glo gls glsdefs acn acr alg "
              "run.xml bcf xdv").split()

FORWARDED = ("-interaction=*", "-synctex=*", "-file-line-error",
             "-no-file-line-error", "-halt-on-error", "-shell-escape",
             "-no-shell-escape", "-enable-write18", "-disable-write18",
             "-recorder", "-8bit", "-etex", "-pdf-mode=*")

PATH_FLAGS = ("-outdir", "-out-directory", "-output-directory",
              "-auxdir", "-aux-directory")


def usage(prog):
    print(f"""Usage: {prog} [options] file.tex
  -pdf, -pdfxe, -pdflua, -latex, -xelatex, -lualatex : engine selection
  -pdflatex=CMD, -xelatex=CMD, -lualatex=CMD        : custom engine command
  -interaction=MODE, -synctex=N, -file-line-error, -halt-on-error
  -shell-escape, -no-shell-escape, -recorder         : forwarded to engine
  -outdir=DIR, -output-directory=DIR, -auxdir=DIR, -aux-directory=DIR
  -jobname=NAME
  -c (clean aux), -C (clean all incl. PDF), -pvc (run once)
  -q, -norc, -r FILE, --version, --help""")


def read_rc(path, state):
    """Parse a (subset of a) latexmk rc file into the driver state."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.split("#", 1)[0].strip()
                m = re.match(r"^\$(\w+)\s*=\s*(.*)$", line)
                if not m:
                    continue
                key = m.group(1)
                v = m.group(2).split(";", 1)[0].strip()
                if v.startswith('"'):
                    v = v[1:]
                if v.endswith('"'):
                    v = v[:-1]
                v = v.replace("%O", "").replace("%S", "").replace("%D", "")
                if key == "pdf_mode":
                    if v not in ("", "0"):
                        state["engine"] = "pdflatex"
                elif key in ("pdflatex", "xelatex", "lualatex"):
                    if "lualatex" in v:
                        state["engine"] = "lualatex"
                    elif "xelatex" in v:
                        state["engine"] = "xelatex"
                    elif "pdflatex" in v:
                        state["engine"] = "pdflatex"
                    elif v:
                        state["engine"] = v
                elif key == "out_dir":
                    if v:
                        state["outdir"] = v
                elif key == "jobname":
                    if v:
                        state["jobname"] = v
    except OSError:
        pass


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    prog = os.path.basename(argv[0])
    # the directory of the *invoked* path (not the resolved symlink target),
    # so a latexmk symlink next to the farm finds its engines there — this
    # mirrors the original bash `dirname "$0"` behaviour
    here = os.path.dirname(os.path.abspath(argv[0]))
    args = argv[1:]

    state = {"engine": "pdflatex", "forward": [], "outdir": "", "jobname": "",
             "mode": "run", "quiet": 0, "norc": 0, "rcfile": "", "input": "",
             "run_once": 0, "rcfile_read": 0}

    # --- rc file(s): read defaults first so CLI args override them ---------
    if state["norc"] == 0:
        if os.path.isfile(".latexmkrc"):
            read_rc(".latexmkrc", state)
        elif os.path.isfile("latexmkrc"):
            read_rc("latexmkrc", state)

    # --- argument parsing --------------------------------------------------
    pending = None
    for a in args:
        if pending is not None:
            if pending == "rcfile":
                state["rcfile"] = a
                # an explicit -r FILE is honored even with -norc (real latexmk
                # behaviour); -norc only skips the default .latexmkrc scan
                if os.path.isfile(a):
                    read_rc(a, state)
                    state["rcfile_read"] = 1
            elif pending == "outdir":
                state["outdir"] = a
            elif pending == "jobname":
                state["jobname"] = a
            elif pending == "synctex":
                if a != "0":
                    state["forward"].append("-synctex=1")
            elif pending == "interaction":
                if a == "batchmode":
                    state["forward"].append("-interaction=batchmode")
            pending = None
            continue
        if a in ("-h", "-help", "--help"):
            usage(prog)
            return 0
        if a in ("-v", "-version", "--version"):
            print(f"latexmk (tectdist) {VERSION} — Tectonic-backed build driver")
            return 0
        if a in ("-pdf", "-latex"):
            state["engine"] = "pdflatex"
        elif a in ("-pdfxe", "-xelatex"):
            state["engine"] = "xelatex"
        elif a in ("-pdflua", "-lualatex"):
            state["engine"] = "lualatex"
        elif a in ("-dvi", "-ps"):
            print(f"latexmk: {prog}: {a}: DVI/PS output unsupported; "
                  "producing PDF.", file=sys.stderr)
            state["engine"] = "pdflatex"
        elif a.startswith("-pdflatex=") or a.startswith("-latex="):
            state["engine"] = a.split("=", 1)[1]
        elif a.startswith("-xelatex="):
            state["engine"] = a.split("=", 1)[1]
        elif a.startswith("-lualatex="):
            state["engine"] = a.split("=", 1)[1]
        elif any(a == f or a.startswith(f[:-1] + "=")
                 for f in ("-interaction=", "-synctex=", "-pdf-mode=")) \
                or a in ("-file-line-error", "-no-file-line-error",
                         "-halt-on-error", "-shell-escape", "-no-shell-escape",
                         "-enable-write18", "-disable-write18", "-recorder",
                         "-8bit", "-etex"):
            state["forward"].append(a)
        elif a == "-interaction":
            pending = "interaction"
        elif a == "-synctex":
            pending = "synctex"
        elif any(a.startswith(f + "=") for f in PATH_FLAGS):
            state["outdir"] = a.split("=", 1)[1]
        elif a in PATH_FLAGS:
            pending = "outdir"
        elif a.startswith("-jobname="):
            state["jobname"] = a.split("=", 1)[1]
        elif a == "-jobname":
            pending = "jobname"
        elif a == "-c":
            state["mode"] = "clean"
        elif a == "-C":
            state["mode"] = "cleanall"
        elif a in ("-pvc", "-p", "-pv"):
            state["run_once"] = 1
        elif a in ("-q", "-quiet"):
            state["quiet"] = 1
        elif a == "-norc":
            state["norc"] = 1
        elif a in ("-r", "-rc"):
            pending = "rcfile"
        elif a.startswith("-r=") or a.startswith("-rc="):
            state["rcfile"] = a.split("=", 1)[1]
            if os.path.isfile(state["rcfile"]):
                read_rc(state["rcfile"], state)
                state["rcfile_read"] = 1
        elif a in ("-f", "-g", "-b", "-bibtex", "-bibtex-", "-x", "-n") \
                or a.startswith("-bibtex-use=") or a.startswith("-bibtexuse="):
            pass
        elif a.startswith("-e"):
            print(f"latexmk: ignoring perl-eval option {a}", file=sys.stderr)
        elif a.startswith("-"):
            print(f"latexmk: ignoring unknown option {a}", file=sys.stderr)
        elif not state["input"]:
            state["input"] = a
        else:
            print(f"latexmk: ignoring extra input {a}", file=sys.stderr)
    # a trailing pending flag with no value is simply dropped
    pending = None

    # -norc was given: discard whatever the default rc file set, unless an
    # explicit -r FILE supplied its own values (which -norc must not clobber)
    if state["norc"] == 1 and not state["rcfile_read"]:
        state["outdir"] = ""
        state["jobname"] = ""
        state["engine"] = "pdflatex"

    # --- clean modes -------------------------------------------------------
    if state["mode"] != "run":
        stem = state["jobname"] or (
            os.path.splitext(os.path.basename(state["input"]))[0]
            if state["input"] else "")
        # a path-y jobname must not delete files outside the output dir
        base = os.path.basename(stem)
        if base != stem:
            print(f"latexmk: jobname '{stem}' contains a path; cleaning '{base}'",
                  file=sys.stderr)
            stem = base
        # stock latexmk cleans only the output directory when one is set
        dirs = [state["outdir"]] if state["outdir"] else ["."]
        if not stem:
            print("latexmk: no input file; nothing to clean", file=sys.stderr)
            return 1
        for d in dirs:
            for ext in CLEAN_EXTS:
                try:
                    os.remove(os.path.join(d, f"{stem}.{ext}"))
                except OSError:
                    pass
            if state["mode"] == "cleanall":
                try:
                    os.remove(os.path.join(d, f"{stem}.pdf"))
                except OSError:
                    pass
        print("latexmk: cleaning done" + (" (quiet)" if state["quiet"] else ""))
        return 0

    # --- assemble the engine invocation ------------------------------------
    input_f = state["input"]
    if not input_f:
        print("latexmk: no input file specified", file=sys.stderr)
        usage(prog)
        return 1
    # resolve an extensionless input the way stock latexmk does
    if input_f != "-" and not os.path.isfile(input_f):
        if "." not in os.path.basename(input_f) \
                and os.path.isfile(input_f + ".tex"):
            input_f += ".tex"
            state["input"] = input_f
    if input_f != "-" and not os.path.isfile(input_f):
        print(f"latexmk: Did not find file '{input_f}'.", file=sys.stderr)
        return 1

    engine = state["engine"]
    if "/" in engine:
        engine_cmd = engine                      # custom command path
    elif engine in KNOWN_ENGINES:
        engine_cmd = os.path.join(here, engine)  # symlink into the same bin/
        if not (os.path.isfile(engine_cmd) and os.access(engine_cmd, os.X_OK)):
            engine_cmd = shutil.which(engine) or engine_cmd
    else:
        candidate = os.path.join(here, engine)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            engine_cmd = candidate
        else:
            engine_cmd = shutil.which(engine) or engine

    cmd = []
    if state["outdir"]:
        cmd.append(f"-output-directory={state['outdir']}")
    if state["jobname"]:
        cmd.append(f"-jobname={state['jobname']}")
    cmd += state["forward"]
    if state["quiet"]:
        cmd.append("-interaction=batchmode")

    if state["run_once"]:
        print("latexmk: -pvc: continuous preview not supported; running once.",
              file=sys.stderr)
    print(f"latexmk: Running '{engine}' on '{input_f}'")

    full = (shlex.split(engine_cmd) if " " in engine_cmd else [engine_cmd]) \
        + cmd + [input_f]
    try:
        return subprocess.run(full).returncode
    except FileNotFoundError:
        print(f"latexmk: {engine_cmd}: command not found", file=sys.stderr)
        return 127
