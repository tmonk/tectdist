#!/usr/bin/env python3
"""Print the `bottle do` block for the formula from `brew bottle --json`
output files in the current directory (as produced by the bottles CI
workflow).  Each bottle JSON maps a formula name to {formula, bottle}, and
each bottle has root_url/rebuild and per-platform tags with sha256s.

Usage: scripts/emit_bottle_block.py [path/to/*.bottle.json ...]
If no files are given, all *.bottle.json files in the current directory are
used.  Output is formatted for pasting into Formula/tectdist.rb.
"""

import json
import sys
from pathlib import Path

def main(argv: list[str]) -> int:
    files = argv[1:] or [str(p) for p in Path(".").glob("*.bottle.json")]
    if not files:
        print("no *.bottle.json files found", file=sys.stderr)
        return 1

    block_lines: list[str] = []
    rebuilds: set[int] = set()
    root_urls: set[str] = set()
    shas: dict[str, str] = {}
    for f in files:
        data = json.loads(Path(f).read_text())
        for info in data.values():
            b = info["bottle"]
            root_urls.add(b["root_url"])
            rebuilds.add(b["rebuild"])
            for tag, t in b["tags"].items():
                shas[tag] = t["sha256"]

    if len(root_urls) != 1:
        print(f"inconsistent root_url across bottles: {root_urls}", file=sys.stderr)
        return 1
    if len(rebuilds) != 1:
        print(f"inconsistent rebuild across bottles: {rebuilds}", file=sys.stderr)
        return 1

    block_lines.append('  bottle do')
    block_lines.append(f'    root_url "{root_urls.pop()}"')
    if rebuilds.pop():
        block_lines.append("    rebuild 1")
    block_lines.append("    sha256 cellar: :any")
    for tag in sorted(shas):
        block_lines.append(f'      {tag}: "{shas[tag]}"')
    block_lines.append("  end")
    print("\n".join(block_lines))
    return 0

if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
