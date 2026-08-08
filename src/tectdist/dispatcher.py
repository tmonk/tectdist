"""The tectdist dispatcher.

Every binary name in bin/ is a symlink to this launcher (or the built
artifact).  A naive tool (editor, latexmk, CI script) can treat the farm
exactly like a stock TeX Live installation: the classic web2c flag
vocabulary is accepted, translated to Tectonic where possible and dropped
where it has no equivalent, while Tectonic-native options pass through
untouched.

  Translated:      -synctex=N, -output-directory/-outdir/-aux-directory,
                   -auxdir, -jobname, -shell-escape/-enable-write18,
                   -include-directory/-I (MiKTeX), -fmt/-format,
                   -q/-quiet/-silent, -interaction=batchmode, TEXINPUTS,
                   BIBINPUTS, BSTINPUTS, INDEXSTYLE
  Ignored:         -interaction, -file-line-error, -halt-on-error,
                   -recorder, -8bit, -etex, -draftmode, -dvi/-no-pdf,
                   -pdf, -cnf-line, -progname, -parse-first-line,
                   -translate-file, -src-specials, -ipc, memory knobs,
                   installer/engine-selector switches, ...
  Pass-through:    everything else, i.e. every real Tectonic option
                   (-C, -b, -f, -r, -k, -p, --chatter, --color,
                   --outfmt, --makefile-rules, -Z..., ...)

Standard behaviour details:
  * output goes to the current directory unless -output-directory is given
    (exactly like a stock pdflatex);
  * -jobname renames the produced .pdf and .synctex.gz artifacts;
  * an input given without a .tex extension is resolved like web2c does;
  * exit status is 0 on success, non-zero on failure.
"""

import os
import sys

from .flags import (ENGINES, IGNORED_FLAGS, MEMORY_KNOBS, PROXIES,
                    ENGINE_PATH_VARS, TECTONIC_FALLBACK,
                    STUB_BIB, PROXY_OR_STUB, STUB_DVI, STUB_MNT_SILENT,
                    STUB_MNT_VERBOSE, STUB_FNT, STUB_MF, STUB_CONTEXT)
from .version import VERSION

# Imported lazily on first use: subprocess/shutil/tools/latexmk are only
# needed on specific dispatch paths, and their imports cost real startup
# time on every other invocation (see benchmarks/).

GS_TOOL_NAMES = {"epstopdf": "do_epstopdf",
                 "eps2eps": "do_eps2eps",
                 "ps2pdf": "do_ps2pdf",
                 "pdfcrop": "do_pdfcrop"}

HELP_TEXT = """tectdist: tectonic-backed TeX distribution.
Available binaries (symlinked to tectdist):
  engines: pdflatex latex xelatex lualatex platex uplatex pdftex tex etex
           luatex luahbtex dvilualatex dviluatex xetex pdfetex
  helpers: bibtex biber bibtex8 bibtexu makeindex xindy upmendex
           dvips dvipdfm dvipdfmx dvipdf xdvipdfmx dvitype dvicopy
           dvipos dvidvi mktexlsr texhash mktexfmt mktexpk mktextfm
           fmtutil fmtutil-sys updmap updmap-sys texconfig tlmgr texdoc
           tftopl pltotf vftovp vptovf gftopk gftype afm2tfm otftotfm
           kpsewhich
  real:    epstopdf eps2eps ps2pdf pdfcrop (via Ghostscript)
           pdftotext pdfinfo pdfimages pdftoppm pdftocairo pdfunite
           pdfseparate pdftops qpdf (proxied to system binaries)
  driver:  latexmk
Classic web2c flags are accepted; see the header of this script."""


def resolve_engine():
    """TECTONIC env -> PATH lookup -> single hard fallback (as before)."""
    import shutil
    cand = os.environ.get("TECTONIC", "")
    if not cand:
        cand = shutil.which("tectonic") or ""
    if not cand:
        cand = TECTONIC_FALLBACK
    return cand


def warn(prog, msg):
    print(f"tectdist: {prog}: {msg}", file=sys.stderr)


def translate(args, prog):
    """Turn web2c-style args into a Tectonic command line.

    Returns ``(cmd, rename, help_wanted)`` where ``rename`` is
    ``(jobname, stem, outdir)`` or ``None``.
    """
    extra = []
    inputs = []
    jobname = ""
    outdir = ""
    synctex = 0
    shell_escape = 0
    quiet = 0
    native_o = 0
    endopts = 0
    help_wanted = 0
    pending = None

    def consume(value):
        nonlocal jobname, outdir, synctex, quiet, extra, pending
        if pending == "jobname":
            jobname = value
        elif pending == "outdir":
            outdir = value
        elif pending == "includedir":
            extra += ["-Z", f"search-path={value}"]
        elif pending == "fmt":
            # Tectonic only ships the latex format; anything else would make it
            # try to *generate* a format file and fail the whole run.
            if value == "latex":
                extra += ["-f", value]
            else:
                warn(prog, f"format '{value}' unsupported by Tectonic; using latex.")
        elif pending == "outputformat":
            if value != "pdf":
                warn(prog, f"output-format '{value}' unsupported; producing PDF.")
        elif pending == "interaction":
            if value == "batchmode":
                quiet = 1
        elif pending == "synctex":
            if value not in ("0", ""):
                synctex = 1
        pending = None

    for a in args:
        if pending is not None:
            if a.startswith("-") and a != "-":
                # no value follows (e.g. `-synctex -shell-escape`): drop the
                # pending flag instead of swallowing the next flag as its value
                consume("")
            else:
                consume(a)
                continue
        if endopts:
            inputs.append(a)
            continue
        if a == "--":
            endopts = 1
            extra.append("--")
            continue
        if a == "-":
            inputs.append(a)
            continue
        if not a.startswith("-"):
            inputs.append(a)
            continue

        # normalize: strip up to two leading dashes, split name=value
        name = a[1:]
        if name.startswith("-"):
            name = name[1:]
        if "=" in name:
            val = name.split("=", 1)[1]
            name = name.split("=", 1)[0]
            hasval = True
        else:
            val = ""
            hasval = False

        if name in ("interaction",):
            if hasval:
                if val == "batchmode":
                    quiet = 1
            else:
                pending = "interaction"
        elif name in ("synctex",):
            if hasval:
                if val != "0":
                    synctex = 1
            else:
                pending = "synctex"  # bare flag with no value -> synctex stays 0
        elif name in ("jobname",):
            if hasval:
                jobname = val
            else:
                pending = "jobname"
        elif name in ("output-directory", "outdir", "aux-directory", "auxdir"):
            if hasval:
                outdir = val
            else:
                pending = "outdir"
        elif name in ("include-directory",):
            if hasval:
                extra += ["-Z", f"search-path={val}"]
            else:
                pending = "includedir"
        elif name == "I":
            if hasval:
                extra += ["-Z", f"search-path={val}"]
            else:
                pending = "includedir"
        elif name.startswith("I") and len(name) > 1:
            extra += ["-Z", f"search-path={name[1:]}"]
        elif name in ("fmt", "format"):
            if hasval:
                if val == "latex":
                    extra += ["-f", val]
                else:
                    warn(prog, f"format '{val}' unsupported by Tectonic; using latex.")
            else:
                pending = "fmt"
        elif name in ("output-format",):
            if hasval:
                if val != "pdf":
                    warn(prog, f"output-format '{val}' unsupported; producing PDF.")
            else:
                pending = "outputformat"
        elif name in ("shell-escape", "enable-write18", "enable-shell-escape"):
            shell_escape = 1
        elif name in ("q", "quiet", "silent"):
            quiet = 1
        elif name in IGNORED_FLAGS:
            pass
        elif name in MEMORY_KNOBS:
            pass
        elif name in ("v", "version", "V"):
            extra.append("--version")
        elif name in ("h", "help"):
            help_wanted = 1
        elif name in ("o", "outdir"):
            native_o = 1
            if hasval:
                extra.append(a.split("=", 1)[0] + "=" + val)
            else:
                extra.append(f"-{name}")
        else:
            if hasval:
                extra.append(a.split("=", 1)[0] + "=" + val)
            else:
                extra.append(a)

    if pending is not None:
        consume("")

    if help_wanted:
        return None, extra, help_wanted  # handled by the caller

    # --- TEXINPUTS & friends -> search paths --------------------------------
    for pathvar in ENGINE_PATH_VARS:
        value = os.environ.get(pathvar, "")
        if value:
            for d in value.split(":"):
                if not d:
                    d = "."      # TeX semantics: an empty component is cwd
                d = d.rstrip("/").rstrip("/")
                extra += ["-Z", f"search-path={d}"]

    # --- web2c-style extensionless input resolution -------------------------
    if inputs and inputs[0] != "-":
        f = inputs[0]
        if (not os.path.isfile(f)
                and "." not in os.path.basename(f)
                and os.path.isfile(f + ".tex")):
            inputs[0] = f + ".tex"

    # --- assemble the command ------------------------------------------------
    cmd = []
    if synctex:
        cmd.append("--synctex")
    if shell_escape:
        cmd += ["-Z", "shell-escape"]
    if quiet:
        cmd += ["--chatter", "minimal"]

    # Standard TeX writes output into the current directory unless told
    # otherwise; Tectonic defaults to the input's directory, so pin the cwd
    # when no explicit -output-directory and no Tectonic-native -o/--outdir
    # was given.
    if outdir:
        try:
            os.makedirs(outdir, exist_ok=True)
        except OSError:
            pass
        cmd += ["-o", outdir]
    elif not native_o and inputs:
        cmd += ["-o", "."]

    cmd += extra + inputs

    # --- -jobname: Tectonic names artifacts after the input file; rename ----
    rename = None
    if jobname and inputs:
        if inputs[0] == "-":
            stem = "texput"                     # Tectonic's name for stdin
        else:
            stem = os.path.splitext(os.path.basename(inputs[0]))[0]
        if jobname != stem:
            rename = (jobname, stem, outdir or ".")
    return cmd, rename, 0


def run_engine(prog, args):
    """Engine path: translate and run Tectonic with the translated argv.

    Index support: Tectonic itself never runs makeindex (it only writes
    ``.idx`` files).  After a successful compile that produced new ``.idx``
    files, a real indexer (makeindex from PATH, falling back to upmendex —
    a drop-in-compatible replacement; never the farm stub itself) is run on
    each stem and Tectonic is re-run once so that ``\\printindex`` picks up
    the generated ``.ind`` files.  When no indexer is installed the compile
    still succeeds, but an honest warning is printed and the index is not
    built.  (biber needs no loop here: Tectonic 0.17 runs a real biber from
    PATH itself for biblatex documents.)
    """
    engine = resolve_engine()
    result = translate(args, prog)
    if result[2]:
        # help requested for a non-tectdist name: forward to the engine
        cmd, _, _ = result
        cmd = [engine, "--help"]
        return run(cmd)
    cmd, rename, _ = result
    full = [engine] + cmd

    # the output directory as Tectonic sees it (translated or native -o)
    dest = "."
    try:
        dest = cmd[cmd.index("-o") + 1]
    except (ValueError, IndexError):
        pass

    def idx_files():
        try:
            return set(os.listdir(dest))
        except OSError:
            return set()

    before = idx_files()
    rc = run(full)
    if rc == 0:
        new_idx = sorted(n for n in (idx_files() - before) if n.endswith(".idx"))
        if new_idx:
            from . import tools
            indexer = (tools.resolve_real("makeindex", prefer_path=True)
                       or tools.resolve_real("upmendex", prefer_path=True))
            if not indexer:
                warn(prog, "the document produced an index (.idx) but neither "
                            "makeindex nor upmendex is available; the index "
                            "will not be built.")
            else:
                import subprocess
                indexed = 0
                for name in new_idx:
                    stem = os.path.splitext(name)[0]
                    proc = None
                    try:
                        proc = subprocess.run([indexer, stem], cwd=dest,
                                              capture_output=True, text=True,
                                              timeout=120)
                    except (OSError, subprocess.TimeoutExpired):
                        pass
                    if proc is not None and proc.returncode == 0:
                        indexed += 1
                    else:
                        detail = ""
                        if proc is not None and proc.stderr and proc.stderr.strip():
                            detail = "; " + proc.stderr.strip()
                        warn(prog, f"{os.path.basename(indexer)} failed on "
                                    f"'{name}'{detail}")
                if indexed:
                    # re-run so \printindex can \@input the new .ind files;
                    # add the output dir to the search paths so a non-cwd
                    # -output-directory works on the second pass too
                    rc = run(full + ["-Z", f"search-path={dest}"])
    if rc == 0 and rename:
        jobname, stem, dest = rename
        # -jobname names the artifacts; it must not relocate them outside the
        # output dir (os.path.join(dest, "/abs" or "../..") would escape it)
        base = os.path.basename(jobname)
        if base != jobname:
            warn(prog, f"-jobname '{jobname}' contains a path; renaming to '{base}'")
            jobname = base
        for ext in ("pdf", "synctex.gz"):
            src = os.path.join(dest, f"{stem}.{ext}")
            if os.path.isfile(src):
                try:
                    os.replace(src, os.path.join(dest, f"{jobname}.{ext}"))
                except OSError:
                    pass
    return rc


def run(argv):
    import subprocess
    try:
        return subprocess.run(argv).returncode
    except FileNotFoundError:
        warn(os.path.basename(argv[0]), f"{argv[0]}: command not found")
        return 127


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    invoked = prog = os.path.basename(argv[0])
    if prog == "tectdist":
        prog = "pdflatex"
    args = argv[1:]

    # --- the tectdist meta-command -------------------------------------------
    if invoked == "tectdist":
        if any(a in ("-v", "-version", "-V", "--version") for a in args):
            print(f"tectdist {VERSION} (Tectonic-backed TeX distribution)")
            return 0
        if any(a in ("-h", "-help", "--help") for a in args):
            print(HELP_TEXT)
            return 0
        if args and args[0] == "doctor":
            from . import pairing
            report, ok = pairing.doctor()
            print(report)
            return 0 if ok else 1

    # --- runtime pairing check (fails fast when brew's tectonic moved) ------
    from . import pairing
    ok, message = pairing.check()
    if not ok:
        warn(prog, message)
        return 1

    # --- tool groups ---------------------------------------------------------
    if prog == "latexmk":
        from .latexmk import main as latexmk_main
        return latexmk_main(argv)
    if prog in (STUB_BIB + STUB_DVI + STUB_MNT_SILENT + STUB_MNT_VERBOSE
                + STUB_FNT + STUB_MF + STUB_CONTEXT + ("tlmgr", "texdoc")):
        from . import tools
        return tools.do_stub(prog, args)
    if prog in PROXY_OR_STUB:
        from . import tools
        return tools.run_proxy_or_stub(prog, args)
    if prog == "kpsewhich":
        from . import tools
        return tools.kpsewhich_main(args)
    if prog in GS_TOOL_NAMES:
        from . import tools
        return getattr(tools, GS_TOOL_NAMES[prog])(args)
    if prog in PROXIES:
        from . import tools
        return tools.run_proxy(prog, args)

    # --- engines -------------------------------------------------------------
    return run_engine(prog, args)

