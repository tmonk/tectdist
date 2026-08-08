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

* The hot path (every farm-tool invocation) checks only the tectonic half:
  ``tectonic --version`` is fast, and tectonic is the only member of the pair
  that brew can move.  The biber in the keg is OUR build — its version cannot
  drift unless the keg is tampered with.  Results are memoized to a per-user
  cache file keyed by the tectonic binary's mtime, so an upgrade is detected
  on the very next invocation and the check itself is otherwise free.

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
        return os.stat(binary).st_mtime
    except OSError:
        return None


def tectonic_version():
    """Run the resolved tectonic and return (pair, full_version_text, binary).

    ``binary`` is the resolved engine path (TECTONIC env / PATH), so the
    caller can key the cache on it.
    """
    import shutil
    binary = os.environ.get("TECTONIC", "") or shutil.which("tectonic") or ""
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


def biber_version():
    """Run biber --version (only used by `tectdist doctor`)."""
    import shutil
    binary = shutil.which("biber")
    if not binary:
        return "", ""
    try:
        proc = subprocess_run([binary, "--version"], timeout=30)
        text = proc.stdout if proc and proc.stdout else ""
        if proc is not None and proc.returncode == 0:
            return biber_version_of(text), text.strip()
    except Exception:  # pragma: no cover - defensive
        pass
    return "", ""


def subprocess_run(argv, timeout):
    import subprocess
    try:
        return subprocess.run(argv, capture_output=True, text=True,
                              timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None


def check(dist="0.1.0"):
    """Fast runtime pairing check used on every farm-tool invocation.

    Returns ``(ok, message)``.  ``ok`` is True when the declared tectonic pair
    matches the installed one (or the check cannot run at all — mocked
    engines, no tectonic, disabled via env).  ``message`` is the actionable
    failure text when ``ok`` is False, else "".
    """
    from .version import VERSION
    dist = VERSION

    if os.environ.get("TECTDIST_SKIP_PAIRING"):
        return True, ""

    pair, text, binary = tectonic_version()
    if not pair:
        # no tectonic / unparseable (mocked engine): nothing to verify
        return True, ""

    # memoized OK results, keyed by declared pairing + the tectonic binary's
    # mtime (an upgrade replaces the binary and invalidates the cache).
    cache = _cache_path()
    if cache and os.path.isfile(cache):
        try:
            with open(cache) as f:
                data = json.load(f)
            mtime = _tectonic_binary_mtime(binary)
            if (data.get("declared") == [TECTONIC_VERSION, BIBER_VERSION]
                    and data.get("pair") == pair
                    and (mtime is None or data.get("mtime") == mtime)
                    and time.time() - data.get("ts", 0) < _TTL_SECONDS):
                return True, ""
        except (OSError, ValueError):
            pass

    if pair == TECTONIC_VERSION:
        try:
            if cache:
                mtime = _tectonic_binary_mtime(binary)
                with open(cache, "w") as f:
                    json.dump({"declared": [TECTONIC_VERSION, BIBER_VERSION],
                               "pair": pair, "mtime": mtime,
                               "ts": time.time()}, f)
        except OSError:
            pass
        return True, ""
    return False, _message(dist, TECTONIC_VERSION, pair)


def doctor():
    """Full pairing report for `tectdist doctor`; exit code = verdict."""
    from .version import VERSION

    lines = [f"tectdist {VERSION} pairing report", ""]
    lines.append("  declared:   tectonic %s.x + biber %s "
                 "(biblatex %s, .bcf %s)" %
                 (TECTONIC_VERSION, BIBER_VERSION, BIBLATEX_VERSION,
                  BCF_VERSION))

    pair, text, _ = tectonic_version()
    if text:
        lines.append("  installed:  tectonic %s" % text.splitlines()[0])
    else:
        lines.append("  installed:  tectonic NOT FOUND")

    bv, btext = biber_version()
    if btext:
        lines.append("  installed:  biber %s" % btext.splitlines()[0])
    else:
        lines.append("  installed:  biber NOT FOUND")

    lines.append("")
    problems = []
    if pair and pair != TECTONIC_VERSION:
        problems.append("tectonic")
    if bv and bv != BIBER_VERSION:
        problems.append("biber")

    if not problems:
        lines.append("  verdict:    PAIR OK")
        report = "\n".join(lines)
        return report, True
    lines.append("  verdict:    MISMATCH (%s)" % ", ".join(problems))
    report = "\n".join(lines)
    if pair and pair != TECTONIC_VERSION:
        report += "\n\n" + _message(VERSION, TECTONIC_VERSION,
                                    pair or "your tectonic version")
    elif bv and bv != BIBER_VERSION:
        report += ("\n\nbiber %s is not the %s this release declares; the "
                   "keg's bin/biber must not be shadowed by another biber "
                   "earlier on PATH." % (bv, BIBER_VERSION))
    return report, False
