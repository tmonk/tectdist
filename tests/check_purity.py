#!/usr/bin/env python3
"""Stdlib-only purity audit for the built dist/tectdist zipapp.

Verifies the artifact contains no third-party imports: every top-level
module imported by any module inside the archive must be the Python standard
library (or the tectdist package itself).  This keeps the "stdlib-only"
promise honest end to end — the zipapp must run on a stock python3 with no
site-packages at all.

Usage:
    python3 tests/check_purity.py                     # build fresh + audit
    python3 tests/check_purity.py dist/tectdist       # audit an existing one
    python3 tests/check_purity.py --no-build          # fail if absent

Exit status: 0 = pure, 1 = third-party import found, 2 = build failure.
"""

import argparse
import ast
import pathlib
import subprocess
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent

# sys.stdlib_module_names exists on Python 3.10+; frozen fallback for 3.9.
if hasattr(sys, "stdlib_module_names"):
    STDLIB = frozenset(sys.stdlib_module_names)
else:  # pragma: no cover - Python 3.9
    STDLIB = frozenset("""abc argparse ast asyncio base64 bisect builtins cmath cmd
    code codecs collections colorsys compileall concurrent configparser contextlib
    copy csv ctypes dataclasses datetime decimal difflib dis email encodings enum
    errno faulthandler filecmp fileinput fnmatch fractions functools gc getopt glob
    graphlib gzip hashlib heapq hmac html http importlib inspect io ipaddress itertools
    json keyword linecache locale logging lzma math mimetypes mmap modulefinder
    multiprocessing netrc numbers operator os pathlib pickle pickletools pkgutil
    platform plistlib pprint profile pstats pty pwd py_compile pyclbr pydoc queue
    quopri random re readline reprlib resource rlcompleter runpy sched secrets select
    selectors shelve shlex shutil signal site smtplib socket sqlite3 ssl stat
    statistics string stringprep struct subprocess sys sysconfig syslog tarfile
    tempfile textwrap threading time timeit tkinter token tokenize trace traceback
    tracemalloc tty types typing unicodedata unittest urllib uu uuid venv warnings
    wave weakref webbrowser winreg wsgiref xml xmlrpc zipapp zipfile zlib""".split())


def audit_zipapp(zip_path):
    """Return (violations, module_count); pure iff violations is empty."""
    violations = []
    module_count = 0
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            if not name.endswith(".py"):
                continue
            module_count += 1
            src = zf.read(name).decode("utf-8", errors="replace")
            tree = ast.parse(src, filename=name)
            # package parts of this module, e.g. "tectdist/dispatcher.py" ->
            # ["tectdist", "dispatcher"]; relative imports resolve against them
            mod_parts = name[:-3].split("/")
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    if node.level:      # relative: from . import x / from ..pkg import y
                        base = mod_parts[:max(0, len(mod_parts) - node.level)]
                        mods = [".".join(base + ([node.module] if node.module else []))]
                    elif node.module:
                        mods = [node.module]
                    else:
                        continue
                else:
                    continue
                for m in mods:
                    top = m.split(".")[0]
                    if top not in STDLIB and top != "tectdist":
                        violations.append(f"{name}: imports {m!r} "
                                          f"(top-level {top!r})")
    return violations, module_count


def build_artifact(dest):
    r = subprocess.run([sys.executable, str(ROOT / "build.py"), "-o", str(dest)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
        sys.exit(2)


def main():
    ap = argparse.ArgumentParser(
        description="audit the tectdist zipapp for third-party imports")
    ap.add_argument("dist", nargs="?", default=None,
                    help="artifact path (default: build fresh to dist/tectdist)")
    ap.add_argument("--no-build", action="store_true",
                    help="fail instead of building when the artifact is absent")
    args = ap.parse_args()

    if args.dist:
        path = pathlib.Path(args.dist)
        if not path.exists() and not args.no_build:
            build_artifact(path)
    else:
        path = ROOT / "dist" / "tectdist"
        if not args.no_build:
            build_artifact(path)
    if not path.exists():
        print(f"check_purity.py: {path}: not found", file=sys.stderr)
        return 1

    violations, count = audit_zipapp(path)
    print(f"check_purity.py: {path}: {count} modules audited")
    if violations:
        for v in sorted(set(violations)):
            print(f"  VIOLATION: {v}")
        print(f"check_purity.py: FAIL — {len(set(violations))} "
              "third-party import(s) in the artifact")
        return 1
    print("check_purity.py: OK — stdlib-only (no third-party imports)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
