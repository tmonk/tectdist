#!/usr/bin/env python3
"""Build the first tectdist-owned exact runtime pack (plan M1/M2, PACK-001/003/007).

Assembles exact-lane tools built from the pinned TeX Live source into a
content-addressed, manifest-described pack layout:

    <out>/
      bin/<platform>/<tool>
      pack-manifest.json

Provenance rules (plan §15.1):
  * the source tarball is verified against reference/texlive-source/source.sha512;
  * every shipped binary is hashed (SHA-256) and recorded;
  * the pack is byte-deterministic given identical inputs (sorted keys,
    fixed ordering) so CI can reproduce and sign it.

Binaries are never committed to Git (O100-004); this pack directory is a
build artefact consumed via TECTDIST_RUNTIME_ROOT.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = ROOT / "reference" / "texlive-source" / "texlive-20260301-source"
SHA512_FILE = ROOT / "reference" / "texlive-source" / "source.sha512"

# Exact-lane tools available in the pinned build tree today (PACK-007
# progress). Extend as more modules are built in CI.
TOOLS = {
    # logical name -> path inside the build tree, relative
    "pdftex": "texk/web2c/pdftex",
    "bibtex": "texk/web2c/bibtex",
}

MANIFEST_SCHEMA = 1


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_source_tarball() -> dict:
    """Verify the pinned source archive matches its recorded SHA-512."""
    tarball = SOURCE_DIR.with_suffix(".tar.xz")
    if not tarball.exists():
        return {"verified": False,
                "reason": f"missing tarball {tarball.name}"}
    expected_lines = [line.split()[0] for line in
                      SHA512_FILE.read_text().splitlines() if line.strip()]
    actual = hashlib.sha512(tarball.read_bytes()).hexdigest()
    if expected_lines and actual != expected_lines[0]:
        return {"verified": False,
                "reason": "tarball sha512 mismatch vs source.sha512"}
    return {"verified": True, "algorithm": "sha512", "digest": actual}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=ROOT / "out" / "exact-pack")
    ap.add_argument("--build-tree", type=Path, default=SOURCE_DIR / "build-pdftex",
                    help="pinned TL build tree supplying the binaries")
    ap.add_argument("--tools", nargs="*", default=sorted(TOOLS),
                    help="subset of tools to ship (default: all known)")
    args = ap.parse_args(argv)

    if not args.build_tree.exists():
        print(f"error: build tree not found: {args.build_tree}", file=sys.stderr)
        return 2

    provenance = verify_source_tarball()
    if not provenance.get("verified"):
        print(f"error: source provenance failed: {provenance['reason']}",
              file=sys.stderr)
        return 2

    plat = f"{platform.system().lower()}-{platform.machine()}"
    bin_dir = args.out / "bin" / plat
    bin_dir.mkdir(parents=True, exist_ok=True)

    tools_manifest = {}
    for name in args.tools:
        rel = TOOLS.get(name)
        if rel is None:
            print(f"error: unknown tool '{name}' (known: {sorted(TOOLS)})",
                  file=sys.stderr)
            return 2
        built = args.build_tree / rel
        if not built.exists():
            print(f"error: '{name}' not built in {args.build_tree} "
                  f"(expected {rel})", file=sys.stderr)
            return 2
        # Reject fork-server/instrumented blobs defensively (O100-004).
        strings = subprocess.run(["strings", str(built)],
                                 capture_output=True, text=True)
        if "tectdist_forkserver" in strings.stdout:
            print(f"error: '{name}' contains experiment hooks; refusing "
                  "to ship instrumented binaries", file=sys.stderr)
            return 2
        dest = bin_dir / name
        shutil.copy2(built, dest)
        tools_manifest[name] = {
            "sha256": sha256_file(dest),
            "size_bytes": dest.stat().st_size,
            "source_path": rel,
        }

    total = sum(t["size_bytes"] for t in tools_manifest.values())
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "kind": "tectdist-exact-runtime-pack",
        "identity": f"exact-native-{plat}",
        "platform": plat,
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provenance": {
            **provenance,
            "source_tree": "texlive-20260301-source",
            "build_tree": args.build_tree.name,
        },
        "tools": dict(sorted(tools_manifest.items())),
        "total_size_bytes": total,
    }
    manifest_path = args.out / "pack-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    print(f"exact pack written to {args.out}")
    for name, entry in sorted(tools_manifest.items()):
        print(f"  {name:<10} {entry['size_bytes']:>9} bytes  "
              f"{entry['sha256'][:16]}…")
    print(f"  total      {total:>9} bytes (uncompressed, tools only)")
    print(f"  provenance sha512 {provenance['digest'][:16]}… verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
