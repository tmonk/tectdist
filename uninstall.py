#!/usr/bin/env python3
"""Remove the tectdist PATH entry installed by install.py.  Clean and
idempotent: scans the usual rc files (or a file given on the command line)
and strips the marker comment plus the export line it introduced.

Run:
    python3 uninstall.py            # removes from ~/.zshrc, ~/.bashrc, ~/.bash_profile
    python3 uninstall.py ~/.bashrc  # or a specific rc file
"""

import os
import sys

MARKER = "# tectdist (Tectonic-backed TeX distribution)"
DEFAULTS = ("~/.zshrc", "~/.bashrc", "~/.bash_profile")


def clean_rc(path):
    """Remove tectdist lines from one rc file; return True if anything was
    removed, False if nothing matched, None if the file does not exist.

    Byte-preserving (no encoding guesses that could corrupt a latin-1 / mixed
    rc file) and atomic (temp file + os.replace, so a crash never truncates
    the user's shell config).  Only lines that reference the install marker or
    the tectdist/texdist PATH entry are touched."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    marker = MARKER.encode("utf-8", "surrogateescape")

    def drop(ln):
        return (b"tectdist/bin" in ln or b"texdist/bin" in ln
                or marker in ln.strip())

    lines = data.split(b"\n")
    if not any(drop(ln) for ln in lines):
        return False
    kept = [ln for ln in lines if not drop(ln)]
    # collapse a run of trailing blank lines down to a single one
    while kept and not kept[-1].strip():
        kept.pop()
    tmp = path + ".tdist-tmp"
    try:
        with open(tmp, "wb") as f:
            f.write(b"\n".join(kept))
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return False
    return True


def main():
    targets = [os.path.expanduser(a) for a in sys.argv[1:]] \
        or [os.path.expanduser(d) for d in DEFAULTS]
    found_any = False
    for path in targets:
        result = clean_rc(path)
        if result is None:
            continue
        if result:
            print(f"uninstall.py: removed tectdist PATH entry from {path}")
            found_any = True
        else:
            print(f"uninstall.py: no tectdist PATH entry found in {path}")
    if not found_any:
        print("uninstall.py: nothing to do — tectdist is not on PATH in the "
              "checked rc files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
