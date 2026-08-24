#!/usr/bin/env python3
"""Apply the tectdist fork-server hook to a built web2c tree (plan X1).

The prototype inserts a serve() call at the post-format-load convergence
point of the GENERATED texk/web2c/<engine>ini.c. Production form will be a
.ch change file; this script keeps the build-tree variant reproducible.

Idempotent: skips engines already hooked.

Usage:
    python3 scripts/forkserver_apply_patch.py --build <build dir> \
        [--engines pdftex]
"""
import argparse
from pathlib import Path



HOOK = """#ifdef TECTDIST_FORKSERVER
    {
      extern void tectdist_forkserver_serve ( void ) ;
      tectdist_forkserver_serve ( ) ;
    }
#endif /* TECTDIST_FORKSERVER */
"""

def hook_engine(web2c: Path, engine: str) -> str:
    source = web2c / f"{engine}ini.c"
    if not source.is_file():
        return "missing-source"
    text = source.read_text()
    if "TECTDIST_FORKSERVER" in text:
        return "already-hooked"
    lines = text.splitlines(keepends=True)
    seen = 0
    out = []
    inserted = False
    for line in lines:
        out.append(line)
        if line.strip() == "fixdateandtime () ;":
            seen += 1
            # The second (unconditional, non-INITEX) call is the convergence
            # point for preloaded-format runs.
            if seen == 2:
                out.append(HOOK)
                inserted = True
    if not inserted:
        return "anchor-not-found"
    source.write_text("".join(out))
    # Newer than its dependencies so make relinks without regenerating.
    source.touch()
    return "hooked"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", required=True)
    parser.add_argument("--engines", nargs="+", default=["pdftex"])
    ns = parser.parse_args(argv)

    web2c = Path(ns.build) / "texk/web2c"
    statuses = {}
    for engine in ns.engines:
        statuses[engine] = hook_engine(web2c, engine)
        print(f"forkserver: {engine}: {statuses[engine]}")
    if all(status in ("hooked", "already-hooked") for status in statuses.values()):
        return 0
    return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
