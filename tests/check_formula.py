#!/usr/bin/env python3
"""Keep the Homebrew formula's symlink farm in sync with the dispatcher.

The single source of truth for the farm is src/tectdist/flags.py; the formula
hand-copies it because brew formulae are Ruby.  This check parses the farm
list out of Formula/tectdist.rb and fails if it drifts, if the `tectdist`
launcher link is missing (the formula's brew test calls #{bin}/tectdist), or
if the test-block count assertion no longer matches the farm size.

Usage:
    python3 tests/check_formula.py        # exit 0 = in sync
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))

from tectdist.flags import FORMULA_FARM_NAMES  # noqa: E402

FORMULA = os.path.join(ROOT, "Formula", "tectdist.rb")
LAUNCHER = "tectdist"
# Real binaries the formula installs into bin/ next to the farm symlinks
# (not part of the farm list, but they occupy bin/ slots — biber is bundled
# as a resource so the farm never symlinks it).
BUNDLED_BINARIES = ("biber",)
MIN_BIN_ENTRIES = 62   # 60 farm names + the tectdist launcher link + the
                       # bundled biber binary


def main():
    with open(FORMULA, encoding="utf-8") as f:
        src = f.read()
    m = re.search(r"farm = %w\[(.*?)\]", src, re.S)
    if not m:
        print("check_formula.py: FAIL — could not find the farm list in "
              "Formula/tectdist.rb")
        return 1
    farm = m.group(1).split()
    expected = list(FORMULA_FARM_NAMES) + [LAUNCHER]

    problems = []
    if LAUNCHER not in farm:
        problems.append(f"farm is missing the '{LAUNCHER}' launcher link "
                        "(brew test calls #{bin}/tectdist)")
    missing = sorted(set(expected) - set(farm))
    extra = sorted(set(farm) - set(expected))
    if missing:
        problems.append(f"farm missing names: {', '.join(missing)}")
    if extra:
        problems.append(f"farm has unexpected names: {', '.join(extra)}")
    if len(farm) + len(BUNDLED_BINARIES) < MIN_BIN_ENTRIES:
        problems.append(f"farm + bundled binaries has "
                        f"{len(farm) + len(BUNDLED_BINARIES)} entries; the "
                        f"test block asserts at least {MIN_BIN_ENTRIES} "
                        f"bin entries")
    if f":>=, {MIN_BIN_ENTRIES}" not in src:
        problems.append(f"test-block count assertion drifted from "
                        f"{MIN_BIN_ENTRIES}")

    if problems:
        for p in problems:
            print(f"check_formula.py: FAIL — {p}")
        return 1
    print(f"check_formula.py: OK — formula farm ({len(farm)} names incl. "
          f"'{LAUNCHER}') matches flags.py; test threshold "
          f"{MIN_BIN_ENTRIES} (incl. {len(BUNDLED_BINARIES)} bundled "
          f"binary)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
