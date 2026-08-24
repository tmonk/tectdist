"""Declared version pairing for this tectdist release.

Each tectdist release REQUIRES a specific tectonic version: tectonic x.y
bundles a specific biblatex version, which speaks a specific ``.bcf`` format,
which only a specific biber version understands.  Brew can move the tectonic
formula underneath an installed tectdist (``brew upgrade``), which silently
breaks biblatex for biblatex documents.  The installed software therefore
compares the ACTUAL pair at runtime and fails fast with instructions when it
no longer matches the declaration.

This module is the single source of truth for the declaration.  The Homebrew
formula mirrors ``TECTONIC_VERSION``; the release gate (tests/battery.py and
RELEASING.md, "Bumping the pairing") checks they stay equal, and the weekly
GitHub Actions watcher (.github/workflows/check-tectonic.yml) files an issue
when brew's tectonic leaves the declared pair before a matched release ships.

Design notes:

* The engine-compile path checks only the tectonic half: tectonic is the only
  member of the pair that brew can move.  The biber in the keg is OUR build —
  its version cannot drift unless the keg is tampered with.  Results are
  memoized to a per-user cache file keyed by the resolved tectonic binary and
  its mtime, so an upgrade is detected on the very next compile and the check
  itself is otherwise free.  Independent utilities remain usable while an
  engine pairing is being diagnosed.

* ``tectdist doctor`` performs the full check (tectonic + biber) and prints a
  human-readable report.

* Unparseable version output (e.g. a mocked engine under tests) disables the
  check silently; the environment variable ``TECTDIST_SKIP_PAIRING=1``
  disables it explicitly.
"""

import json
import os
import re
import time

TECTONIC_VERSION = "0.17"   # tectonic minor pair this release requires
BIBER_VERSION = "2.17"      # biber version this release builds/bundles
BIBLATEX_VERSION = "3.17"   # biblatex bundled by tectonic TECTONIC_VERSION
BCF_VERSION = "3.8"         # .bcf format the pairing speaks

_TTL_SECONDS = 24 * 3600    # cache validity; invalidated early by mtime change


def _message(dist, need, actual):
    return (
        f"tectdist {dist} requires tectonic {need}.x: tectonic {need} bundles "
        f"biblatex {BIBLATEX_VERSION}, which is only understood by the bundled "
        f"biber {BIBER_VERSION}.  The installed tectonic is {actual} — a "
        f"mismatched pair would silently break biblatex, so tectdist refuses "
        f"to run.\n\n"
        f"Fix: keep brew's tectonic at {need}.x, or wait for the next tectdist "
        f"release that pairs with {actual} and then run:\n"
        f"  brew upgrade tmonk/brew/tectdist   # or: brew upgrade tectdist\n"
        f"While tectonic is at {need}.x you can also pin it so it cannot move "
        f"underneath the pairing:\n"
        f"  brew pin tectonic\n"
        f"Run `tectdist doctor` for details."
    )


def tectonic_pair_of(version_text):
    """'Tectonic 0.17.0 ...' -> '0.17' ('' when unparseable)."""
    m = re.search(r"(\d+)\.(\d+)", version_text or "")
    return f"{m.group(1)}.{m.group(2)}" if m else ""


def biber_version_of(version_text):
    """'biber version: 2.17 ...' -> '2.17' ('' when unparseable)."""
    m = re.search(r"biber version:\s*([0-9.]+)", version_text or "")
    return m.group(1) if m else ""


def _cache_dir():
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(
        os.path.expanduser("~"), ".cache")
    d = os.path.join(base, "tectdist")
    try:
        os.makedirs(d, exist_ok=True)
        return d
    except OSError:
        return None


def _cache_path():
    d = _cache_dir()
    return os.path.join(d, "pairing.json") if d else None


def _tectonic_binary_mtime(binary):
    try:
        return os.stat(binary).st_mtime_ns
    except OSError:
        return None


def _resolved_tectonic():
    """Return the configured/path-resolved tectonic executable, if any."""
    import shutil
    configured = os.environ.get("TECTONIC", "")
    if configured:
        # Resolve a bare override such as TECTONIC=tectonic when possible,
        # but preserve an invalid explicit path so the caller can report the
        # engine error rather than silently selecting another binary.
        return shutil.which(configured) or configured
    found = shutil.which("tectonic")
    if found:
        return found
    from .flags import TECTONIC_FALLBACK
    return (TECTONIC_FALLBACK
            if os.path.isfile(TECTONIC_FALLBACK)
            and os.access(TECTONIC_FALLBACK, os.X_OK) else "")


def tectonic_version(binary=None):
    """Run the resolved tectonic and return (pair, full_version_text, binary).

    ``binary`` is the resolved engine path (TECTONIC env / PATH), so the
    caller can key the cache on it.
    """
    binary = binary or _resolved_tectonic()
    if not binary:
        return "", "", ""
    try:
        proc = subprocess_run([binary, "--version"], timeout=10)
        text = proc.stdout if proc and proc.stdout else ""
        if proc is not None and proc.returncode == 0:
            return tectonic_pair_of(text), text.strip(), binary
    except Exception:  # pragma: no cover - defensive
        pass
    return "", "", binary


def biber_status():
    """Run ``biber --version`` and return its usable health information.

    A path lookup alone is not a health check: a brewed biber may be present
    but fail before it can print its version, for example when a bottle's
    XS modules were built for a different Perl ABI.  Keep the distinction so
    ``tectdist doctor`` can tell a missing program from a broken one.

    Returns ``(version, version_text, binary, error)``.  ``error`` is empty
    only when biber ran successfully; it is deliberately concise because it
    is displayed in both human and JSON doctor reports.
    """
    import shutil
    binary = shutil.which("biber")
    if not binary:
        return "", "", "", ""
    try:
        proc = subprocess_run([binary, "--version"], timeout=30)
        if proc is None:
            return "", "", binary, "could not execute or timed out"
        text = (proc.stdout or "").strip()
        if proc.returncode != 0:
            detail = (proc.stderr or "").strip() or text
            error = f"exited with status {proc.returncode}"
            if detail:
                error += f": {detail.splitlines()[0]}"
            return "", text, binary, error
        version = biber_version_of(text)
        if not version:
            return "", text, binary, "did not report a parseable version"
        return version, text, binary, ""
    except Exception:  # pragma: no cover - defensive
        return "", "", binary, "could not execute"


def subprocess_run(argv, timeout):
    import subprocess
    try:
        return subprocess.run(argv, capture_output=True, text=True,
                              timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None


def _read_cached(cache, binary, mtime):
    """Return a recent cached pair for this exact executable, or ``None``."""
    if not cache or mtime is None:
        return None
    try:
        with open(cache) as f:
            data = json.load(f)
        if (data.get("declared") == [TECTONIC_VERSION, BIBER_VERSION]
                and data.get("binary") == os.path.realpath(binary)
                and data.get("mtime") == mtime
                and time.time() - data.get("ts", 0) < _TTL_SECONDS):
            pair = data.get("pair")
            return pair if isinstance(pair, str) else ""
    except (OSError, ValueError, TypeError):
        pass
    return None


def _write_cache(cache, binary, mtime, pair):
    """Best-effort atomic cache update; a cache must never break a compile."""
    if not cache or mtime is None:
        return
    tmp = f"{cache}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w") as f:
            json.dump({"declared": [TECTONIC_VERSION, BIBER_VERSION],
                       "binary": os.path.realpath(binary),
                       "pair": pair, "mtime": mtime, "ts": time.time()}, f)
        os.replace(tmp, cache)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def check(dist="0.1.0"):
    """Fast runtime pairing check used on every engine compile.

    Returns ``(ok, message)``.  ``ok`` is True when the declared tectonic pair
    matches the installed one (or the check cannot run at all — mocked
    engines, no tectonic, disabled via env).  ``message`` is the actionable
    failure text when ``ok`` is False, else "".
    """
    from .version import VERSION
    dist = VERSION

    if os.environ.get("TECTDIST_SKIP_PAIRING"):
        return True, ""

    binary = _resolved_tectonic()
    if not binary:
        # no tectonic: nothing to verify
        return True, ""

    cache = _cache_path()
    mtime = _tectonic_binary_mtime(binary)
    cached_pair = _read_cached(cache, binary, mtime)
    if cached_pair is not None:
        if cached_pair == TECTONIC_VERSION:
            return True, ""
        return False, _message(dist, TECTONIC_VERSION, cached_pair)

    pair, text, binary = tectonic_version(binary)
    if not pair:
        # no tectonic / unparseable (mocked engine): nothing to verify
        return True, ""

    if pair == TECTONIC_VERSION:
        _write_cache(cache, binary, _tectonic_binary_mtime(binary), pair)
        return True, ""
    _write_cache(cache, binary, _tectonic_binary_mtime(binary), pair)
    return False, _message(dist, TECTONIC_VERSION, pair)


def doctor(as_json=False):
    """Full pairing report for `tectdist doctor`; exit code = verdict.

    ``as_json`` is intended for editor integrations and CI health checks.  It
    returns the same verdict as the human report, with paths and parsed
    versions included so callers do not need to scrape prose.
    """
    from .version import VERSION

    pair, text, binary = tectonic_version()
    bv, btext, biber_binary, biber_error = biber_status()
    problems = []
    # ``doctor`` is a health check, rather than the permissive compile-path
    # probe (which deliberately lets the normal engine-not-found error speak
    # for itself).  A missing dependency must therefore be unhealthy instead
    # of accidentally producing a reassuring "PAIR OK" result.
    if not pair:
        problems.append("tectonic-missing")
    elif pair != TECTONIC_VERSION:
        problems.append("tectonic")
    if not biber_binary:
        problems.append("biber-missing")
    elif biber_error:
        problems.append("biber-failed")
    elif bv != BIBER_VERSION:
        problems.append("biber")

    if as_json:
        import shutil
        payload = {
            "tectdist": VERSION,
            "declared": {
                "tectonic": TECTONIC_VERSION,
                "biblatex": BIBLATEX_VERSION,
                "biber": BIBER_VERSION,
                "bcf": BCF_VERSION,
            },
            "installed": {
                "tectonic": {
                    "path": binary or None,
                    "pair": pair or None,
                    "version": text.splitlines()[0] if text else None,
                },
                "biber": {
                    "path": biber_binary or None,
                    "version": btext.splitlines()[0] if btext else None,
                    "error": biber_error or None,
                },
            },
            "ok": not problems,
            "problems": problems,
        }
        return json.dumps(payload, indent=2, sort_keys=True), not problems

    lines = [f"tectdist {VERSION} pairing report", ""]
    lines.append("  declared:   tectonic %s.x + biber %s "
                 "(biblatex %s, .bcf %s)" %
                 (TECTONIC_VERSION, BIBER_VERSION, BIBLATEX_VERSION,
                  BCF_VERSION))

    if text:
        lines.append("  installed:  tectonic %s" % text.splitlines()[0])
    else:
        lines.append("  installed:  tectonic NOT FOUND")

    if biber_error:
        lines.append("  installed:  biber FAILED (%s)" % biber_error)
    elif btext:
        lines.append("  installed:  biber %s" % btext.splitlines()[0])
    else:
        lines.append("  installed:  biber NOT FOUND")

    lines.append("")
    if not problems:
        lines.append("  verdict:    PAIR OK")
        report = "\n".join(lines)
        return report, True
    lines.append("  verdict:    MISMATCH (%s)" % ", ".join(problems))
    report = "\n".join(lines)
    if not pair:
        report += ("\n\ntectonic is required but was not found or did not "
                   "report a parseable version. Install the matching "
                   f"tectonic {TECTONIC_VERSION}.x release and run "
                   "`tectdist doctor` again.")
    elif pair != TECTONIC_VERSION:
        report += "\n\n" + _message(VERSION, TECTONIC_VERSION,
                                    pair or "your tectonic version")
    elif not biber_binary:
        report += ("\n\nbiber is required for the supported biblatex "
                   "workflow but was not found or did not report a "
                   "parseable version. Install the formula-provided biber "
                   f"{BIBER_VERSION} and run `tectdist doctor` again.")
    elif biber_error:
        report += ("\n\nbiber was found but could not run. This commonly "
                   "means its Perl modules were built for a different Perl "
                   "version. Reinstall a tectdist bottle built for the "
                   "formula's bundled Perl, then run `tectdist doctor` "
                   "again.")
    elif bv != BIBER_VERSION:
        report += ("\n\nbiber %s is not the %s this release declares; the "
                   "keg's bin/biber must not be shadowed by another biber "
                   "earlier on PATH." % (bv, BIBER_VERSION))
    return report, False
