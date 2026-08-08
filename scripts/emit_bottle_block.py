#!/usr/bin/env python3
"""Print the `bottle do` block for the formula from `brew bottle --json`
output files in the current directory (as produced by the bottles CI
workflow).  Each bottle JSON maps a formula name to {formula, bottle}, and
each bottle has root_url/rebuild/cellar and per-platform tags with sha256s.

Output replicates brew's own DSL formatting (see Homebrew::DevCmd::Bottle:
generate_sha256_line): one `sha256` line per tag with aligned columns and a
per-tag `cellar:` argument.

Usage: scripts/emit_bottle_block.py [path/to/*.bottle.json ...]
If no files are given, all *.bottle.json files in the current directory are
used.  Output is formatted for pasting into Formula/tectdist.rb.
"""

import json
import sys
from pathlib import Path


def cellar_fragment(cellar: str) -> str:
    """Render a cellar value the way brew's DSL does."""
    if cellar.startswith("/"):
        return f'cellar: "{cellar}",'
    return f"cellar: :{cellar},"


def main(argv: list[str]) -> int:
    files = argv[1:] or [str(p) for p in Path(".").glob("*.bottle.json")]
    if not files:
        print("no *.bottle.json files found", file=sys.stderr)
        return 1

    root_urls: set[str] = set()
    rebuilds: set[int] = set()
    shas: dict[str, str] = {}    # tag -> sha256
    cellars: dict[str, str] = {} # tag -> cellar value ("any", path, ...)
    for f in files:
        data = json.loads(Path(f).read_text())
        for info in data.values():
            b = info["bottle"]
            root_urls.add(b["root_url"])
            rebuilds.add(b["rebuild"])
            for tag, t in b["tags"].items():
                shas[tag] = t["sha256"]
                cellars[tag] = b.get("cellar", "any")

    if len(root_urls) != 1:
        print(f"inconsistent root_url across bottles: {root_urls}", file=sys.stderr)
        return 1
    if len(rebuilds) != 1:
        print(f"inconsistent rebuild across bottles: {rebuilds}", file=sys.stderr)
        return 1

    tags = sorted(shas)
    max_tag_len = max(len(t) for t in tags)
    # brew: tag_column = "cellar: <widest cellar>, ".length (after the "sha256 " prefix)
    widest_cellar = max(len(cellar_fragment(c)) for c in cellars.values()) + 1
    tag_column = len("sha256 ") + widest_cellar
    digest_column = tag_column + max_tag_len + 2  # `: ` after the tag

    lines = ["  bottle do", f'    root_url "{root_urls.pop()}"']
    if rebuilds.pop():
        lines.append("    rebuild 1")
    for tag in tags:
        head = cellar_fragment(cellars[tag])
        line = "sha256 " + head.ljust(widest_cellar)
        line += f"{tag}:"
        line += " " * (digest_column - tag_column - len(tag) - 1)
        lines.append(f"    {line}\"{shas[tag]}\"")
    lines.append("  end")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
