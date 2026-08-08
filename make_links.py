#!/usr/bin/env python3
"""Rebuild the symlink farm in bin/: every tool name is a symlink to the
`tectdist` launcher (or the built artifact).  Idempotent.

The name list is the single source of truth in src/tectdist/flags.py, so the
farm can never drift from what the dispatcher understands.

Usage:
    python3 make_links.py
"""

import os
import sys

_here = os.path.dirname(os.path.realpath(__file__))
_src = os.path.join(_here, "src")
if os.path.isdir(_src) and _src not in sys.path:
    sys.path.insert(0, _src)

from tectdist.flags import FARM_NAMES  # noqa: E402

BIN = os.path.join(_here, "bin")


def main():
    os.makedirs(BIN, exist_ok=True)
    replaced = 0
    for name in FARM_NAMES:
        path = os.path.join(BIN, name)
        if os.path.islink(path):
            os.unlink(path)
        elif os.path.exists(path):
            print(f"tectdist: {name}: replacing a real file with a symlink")
            os.remove(path)
            replaced += 1
        os.symlink("tectdist", path)
    count = sum(1 for n in os.listdir(BIN)
                if os.path.islink(os.path.join(BIN, n)))
    extra = sorted(n for n in os.listdir(BIN)
                   if os.path.islink(os.path.join(BIN, n))
                   and n not in FARM_NAMES and n != "tectdist")
    if extra:
        print(f"tectdist: note: unexpected symlinks not in the farm: "
              f"{', '.join(extra)}")
    if replaced:
        print(f"tectdist: replaced {replaced} real file(s) with symlinks")
    print(f"tectdist: {count} symlinks + 1 launcher (bin/tectdist) in {BIN}")


if __name__ == "__main__":
    sys.exit(main())
