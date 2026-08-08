"""Non-engine tools in the farm: real-binary proxies (poppler/qpdf), the
Ghostscript-based helpers (epstopdf/eps2eps/ps2pdf/pdfcrop), the informational
stubs, and the kpsewhich file-lookup.

All of these mirror the behaviour of the original bash dispatcher exactly:
same messages, same exit codes, same argument handling.
"""

import glob
import os
import shutil
import subprocess
import sys

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def err(msg):
    print(msg, file=sys.stderr)


def stub_message(prog, lines):
    """Print a two-line "nothing to do" notice for an unsupported tool."""
    for ln in lines:
        err(f"tectdist: {prog}: {ln}")
    return 0


def run_cmd(argv):
    """Run a child and return its exit status (stdout/stderr inherit)."""
    try:
        return subprocess.run(argv).returncode
    except FileNotFoundError:
        err(f"tectdist: {argv[0]}: command not found")
        return 127


# ---------------------------------------------------------------------------
# proxy: run the real system binary of the same name (poppler, qpdf, ...)
# ---------------------------------------------------------------------------

def resolve_real(prog, prefer_path=False):
    """Find the real system binary for ``prog``, never the tectdist launcher.

    The farm may shadow a real tool of the same name (e.g. a Homebrew install
    of tectdist in the prefix bin), so any candidate that resolves to the
    tectdist executable (the launcher or the zipapp artifact) is skipped;
    Homebrew opt dirs are the fallback where the real keg binaries live.

    ``prefer_path=True`` searches PATH first (used by the makeindex rerun
    loop, where a user's own makeindex on PATH must win); the default keeps
    the fixed locations first, exactly as the proxies always behaved.

    Every PATH entry is scanned in order: ``shutil.which`` only returns the
    first hit, which is often the farm symlink itself and must be skipped.
    """
    self_real = os.path.realpath(sys.argv[0])

    def good(path):
        if not path:
            return False
        rp = os.path.realpath(path)
        if rp == self_real or os.path.basename(rp) == "tectdist":
            return False
        return os.path.isfile(path) and os.access(path, os.X_OK)

    def path_candidates():
        for d in os.environ.get("PATH", "").split(os.pathsep):
            if d:
                cand = os.path.join(d, prog)
                if os.path.isfile(cand) and os.access(cand, os.X_OK):
                    yield cand

    def candidates():
        # fixed locations first; the /opt/*/bin globs are only evaluated on
        # a miss (they are the expensive part of the lookup)
        yield f"/opt/homebrew/bin/{prog}"
        yield f"/usr/local/bin/{prog}"
        yield f"/usr/bin/{prog}"
        yield from path_candidates()
        for base in ("/opt/homebrew/opt", "/usr/local/opt"):
            for hit in sorted(glob.glob(f"{base}/*/bin/{prog}")):
                yield hit

    if prefer_path:
        for c in path_candidates():
            if good(c):
                return c
    for c in candidates():
        if good(c):
            return c
    return ""


def run_proxy(prog, args):
    found = resolve_real(prog)
    if not found:
        err(f"tectdist: {prog}: real binary not found on this system.")
        return 127
    try:
        os.execvpe(found, [found] + args, os.environ)
    except OSError as exc:
        err(f"tectdist: {prog}: cannot execute {found}: {exc}")
        return 127
    return 127  # unreachable


def run_proxy_or_stub(prog, args):
    """Proxy to the real system binary of the same name when installed;
    otherwise fall back to an honest exit-0 stub notice.

    Used for makeindex/xindy/upmendex/biber: these are real tools a user may
    well have installed (TeX Live, MacTeX, MiKTeX, homebrew), and the farm
    must not shadow them.  When the tool is absent the command stays a
    no-op that exits 0 so unconditional pipeline calls keep running.
    """
    found = resolve_real(prog)
    if found:
        try:
            os.execvpe(found, [found] + args, os.environ)
        except OSError as exc:
            err(f"tectdist: {prog}: cannot execute {found}: {exc}")
            return 127
    return do_stub(prog, args)


# ---------------------------------------------------------------------------
# gs-based helpers (epstopdf / eps2eps / ps2pdf / pdfcrop)
# ---------------------------------------------------------------------------

def require_gs(prog):
    if shutil.which("gs"):
        return True
    err(f"tectdist: {prog}: ghostscript (gs) is required but not installed.")
    return False


def gs(argv):
    """Run ghostscript and return its exit status."""
    return run_cmd([shutil.which("gs")] + argv)


def fmt_num(v):
    """Format a float the way awk does: integral values without a decimal."""
    return str(int(v)) if float(v).is_integer() else str(v)


def do_epstopdf(args):
    if not require_gs("epstopdf"):
        return 1
    in_f = out = ""
    quiet = 0
    pending_o = False
    for a in args:
        if pending_o:
            out = a
            pending_o = False
            continue
        if a == "-o":
            pending_o = True
        elif a.startswith("-o=") or a.startswith("--outfile="):
            out = a.split("=", 1)[1]
        elif a in ("-q", "--quiet"):
            quiet = 1
        elif a in ("--debug", "--pdf", "--nocompress", "--hires"):
            pass
        elif a.startswith("--gs=") or a.startswith("--gscmd="):
            pass
        elif a.startswith("-"):
            err(f"tectdist: epstopdf: ignoring option {a}")
        else:
            if not in_f:
                in_f = a
            else:
                out = a
    if not in_f:
        err("tectdist: epstopdf: no input file")
        return 1
    if not os.path.isfile(in_f):
        err(f"tectdist: epstopdf: {in_f}: No such file")
        return 1
    if not out:
        out = os.path.splitext(in_f)[0] + ".pdf"
    argv = ["-q", "-dNOPAUSE", "-dBATCH", "-dSAFER",
            "-sDEVICE=pdfwrite", "-dEPSCrop"]
    if quiet:
        argv.append("-dQUIET")
    argv += [f"-sOutputFile={out}", in_f]
    return gs(argv)


def do_eps2eps(args):
    if not require_gs("eps2eps"):
        return 1
    if len(args) < 2:
        err("tectdist: eps2eps: usage: eps2eps input.eps output.eps")
        return 1
    return gs(["-q", "-dNOPAUSE", "-dBATCH", "-dSAFER",
               "-sDEVICE=eps2write", f"-sOutputFile={args[1]}", args[0]])


def do_ps2pdf(args):
    if not require_gs("ps2pdf"):
        return 1
    in_f = out = ""
    gsopts = []
    last = args[-1] if args else ""
    for a in args:
        if a.endswith(".ps") or a.endswith(".eps"):
            if not in_f:
                in_f = a
            else:
                gsopts.append(a)
        else:
            if in_f and a == last and not out:
                out = a
            else:
                gsopts.append(a)
    if not in_f:
        err("tectdist: ps2pdf: no input file")
        return 1
    if not out:
        out = os.path.splitext(in_f)[0] + ".pdf"
    return gs(["-q", "-dNOPAUSE", "-dBATCH", "-dSAFER",
               "-sDEVICE=pdfwrite", f"-sOutputFile={out}"] + gsopts + [in_f])


def do_pdfcrop(args):
    if not require_gs("pdfcrop"):
        return 1
    in_f = out = ""
    margins = "0 0 0 0"
    i = 0
    n = len(args)
    while i < n:
        a = args[i]
        if a in ("--margins", "--margin"):
            if i + 1 < n:
                margins = args[i + 1]
            i += 2
            continue
        if a.startswith("--margins=") or a.startswith("--margin="):
            margins = a.split("=", 1)[1]
            i += 1
            continue
        if a in ("--hires", "--nopdfinfo"):
            i += 1
            continue
        if a.startswith("-"):
            err(f"tectdist: pdfcrop: ignoring option {a}")
            i += 1
            continue
        if not in_f:
            in_f = a
        else:
            out = a
        i += 1
    if not in_f:
        err("tectdist: pdfcrop: no input file")
        return 1
    if not os.path.isfile(in_f):
        err(f"tectdist: pdfcrop: {in_f}: No such file")
        return 1
    if not out:
        base, ext = os.path.splitext(in_f)
        out = base + "-crop" + ext

    # measure the bounding box
    try:
        proc = subprocess.run([shutil.which("gs"), "-q", "-dSAFER", "-dNOPAUSE",
                               "-dBATCH", "-sDEVICE=bbox", in_f],
                              capture_output=True, text=True, timeout=60)
    except (subprocess.TimeoutExpired, OSError):
        err(f"tectdist: pdfcrop: could not determine bounding box")
        return 1
    bbox = ""
    for line in proc.stderr.splitlines():
        if "BoundingBox" in line:
            bbox = line
    parts = bbox.split(":", 1)[-1].split() if bbox else []
    if len(parts) < 4:
        err("tectdist: pdfcrop: could not determine bounding box")
        return 1
    x0, y0, x1, y1 = (float(p) for p in parts[-4:])
    ml = mr = mt = mb = 0.0
    mp = margins.split()
    try:
        if len(mp) >= 1:
            ml = float(mp[0])
        if len(mp) >= 2:
            mr = float(mp[1])
        if len(mp) >= 3:
            mt = float(mp[2])
        if len(mp) >= 4:
            mb = float(mp[3])
    except ValueError:
        err(f"tectdist: pdfcrop: invalid --margins value '{margins}'")
        return 1
    x0, y0, x1, y1 = x0 - ml, y0 - mb, x1 + mr, y1 + mt
    box = " ".join(fmt_num(v) for v in (x0, y0, x1, y1))
    return gs(["-q", "-dNOPAUSE", "-dBATCH", "-dSAFER",
               "-sDEVICE=pdfwrite", "-o", out,
               "-c", f"[/CropBox [{box}] /PAGES pdfmark", "-f", in_f])


# ---------------------------------------------------------------------------
# stubs
# ---------------------------------------------------------------------------

def do_stub(prog, args):
    if prog in ("bibtex", "bibtex8", "bibtexu"):
        return stub_message(prog, [
            "bibliography processing is performed by Tectonic's",
            "         built-in BiBTeX during the compile; nothing to do here."])
    if prog == "biber":
        return stub_message(prog, [
            "no real biber binary on PATH.  Tectonic runs biber natively",
            "         for biblatex documents; without it the bibliography is",
            "         empty and citations print their raw keys.  Install biber",
            "         (TeX Live/MacTeX) to get real biblatex+biber support."])
    if prog == "makeindex":
        return stub_message(prog, [
            "no real makeindex binary on PATH.  The engine's rerun loop",
            "         runs makeindex (or upmendex) automatically after a",
            "         compile; without it the index will not be built."])
    if prog == "xindy":
        return stub_message(prog, [
            "no real xindy binary on PATH; nothing to do here.  xindy is",
            "         proxied when installed but is never used by the engine",
            "         loop (it is not a makeindex drop-in)."])
    if prog == "upmendex":
        return stub_message(prog, [
            "no real upmendex binary on PATH; nothing to do here.  The",
            "         engine's rerun loop tries upmendex after makeindex."])
    if prog in ("dvips", "dvipdfm", "dvipdfmx", "dvipdf", "xdvipdfmx",
                "dvitype", "dvicopy", "dvipos", "dvidvi"):
        return stub_message(prog, [
            "DVI/PS handling is already performed by Tectonic;",
            "         nothing to do here."])
    if prog in ("mktexlsr", "texhash"):
        return 0
    if prog in ("mktexfmt", "mktexpk", "mktextfm", "fmtutil", "fmtutil-sys",
                "updmap", "updmap-sys", "texconfig"):
        return stub_message(prog, [
            "font/format management is handled by Tectonic's",
            "         bundle; nothing to do here."])
    if prog in ("tftopl", "pltotf", "vftovp", "vptovf", "gftopk", "gftype",
                "afm2tfm", "otftotfm"):
        return stub_message(prog, [
            "font conversion is not needed with Tectonic;",
            "         nothing to do here."])
    if prog in ("mf", "mpost", "mft", "tangle", "weave"):
        return stub_message(prog, [
            "not supported by Tectonic; no output produced."])
    if prog in ("context", "texexec"):
        return stub_message(prog, [
            "ConTeXt is not supported by Tectonic (LaTeX is).",
            "         no output produced."])
    if prog == "tlmgr":
        first = args[0] if args else ""
        if first in ("--version", "-v", "version"):
            print("tlmgr (tectdist): Tectonic 0.16.9 bundle manager")
            return 0
        if first in ("--help", "-h", "help", "--list"):
            return 0
        # action commands (install/update/remove/...) are refused: exit non-zero
        # so scripts that check tlmgr's status don't mistake a no-op for success
        err("tectdist: tlmgr: package management is delegated to Tectonic's")
        err("         bundle; nothing to do here.")
        return 1
    if prog == "texdoc":
        err("tectdist: texdoc: offline documentation is not bundled; see")
        err("         https://tectonic-typesetting.github.io for docs.")
        return 0
    return 0


# ---------------------------------------------------------------------------
# kpsewhich
# ---------------------------------------------------------------------------

def kpsewhich_main(args):
    # -var-value only answers for variables this distribution actually knows;
    # echoing arbitrary environment variables (real kpsewhich does not) would
    # leak secrets to scripts running kpsewhich on untrusted input.
    known_vars = ("TEXINPUTS", "BIBINPUTS", "BSTINPUTS", "INDEXSTYLE")
    var = ""
    name = ""
    var_next = False
    skip_next = False
    for a in args:
        if a.startswith("-var-value="):
            var = a[len("-var-value="):]
        elif a == "-var-value":
            var_next = True
        elif (a.startswith("-format=") or a.startswith("-progname=")
              or a.startswith("-interaction=") or a.startswith("-debug=")):
            pass
        elif a in ("-format", "-progname"):
            skip_next = True
        elif a in ("-version", "--version", "-v"):
            print("kpsewhich (tectdist, Tectonic 0.16.9)")
            return 0
        elif a in ("-help", "--help", "-h"):
            print("usage: kpsewhich [options] filename...")
            return 0
        elif a.startswith("-"):
            if var_next:
                var = a[1:]
                var_next = False
            if skip_next:
                skip_next = False
        else:
            if var_next:
                var = a
                var_next = False
                continue
            if skip_next:
                skip_next = False
                continue
            if not name:
                name = a
    if var:
        if var not in known_vars:
            err(f"kpsewhich: unknown variable '{var}'")
            return 1
        print(os.environ.get(var, ""))
        return 0
    if not name:
        return 1
    if os.path.isfile(name):
        print(name)
        return 0
    # search TEXINPUTS / BIBINPUTS / BSTINPUTS directories
    for pathvar in ("TEXINPUTS", "BIBINPUTS", "BSTINPUTS"):
        value = os.environ.get(pathvar, "")
        if not value:
            continue
        for d in value.split(":"):
            if not d:
                continue
            d = d.rstrip("/")
            if os.path.isfile(os.path.join(d, name)):
                print(os.path.join(d, name))
                return 0
    return 1
