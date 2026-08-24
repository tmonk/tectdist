#!/usr/bin/env python3
"""Assemble and verify the immutable BasicTeX runtime image (plan B1).

Assembles a content-addressed image directory from an extracted BasicTeX
payload, verifies every file against the frozen files.sha256 manifest,
enforces the core payload size gate, and emits image-manifest.json:

    {
      "profile": "basictex-2026",
      "image_files_sha256": "...",   # digest of files.sha256 (identity)
      "payload_sha256": "...",       # digest of this assembled image
      "compressed_size_bytes": ...,  # zstd/tar.gz compressed payload
      "size_gate_bytes": ...,
      "package_count": ...
    }

Usage:
    python3 scripts/basictex_image.py --payload <TL root> [--output DIR]

Exit status is nonzero when any file mismatches the frozen manifest or the
size gate is exceeded.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tarfile

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "reference/basictex-2026"

SIZE_GATE_FLOOR = 200 * 1024 * 1024          # 200 MiB
SIZE_GATE_MULTIPLIER = 1.5                    # × official installer size


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload", required=True)
    parser.add_argument("--output", default=str(ROOT / "reference/basictex-2026/image"))
    parser.add_argument("--skip-compress", action="store_true")
    ns = parser.parse_args(argv)

    root = Path(ns.payload).resolve()
    out = Path(ns.output).resolve()
    frozen_digests = {}
    for line in (REFERENCE / "files.sha256").read_text().splitlines():
        digest, _, name = line.partition("  ")
        frozen_digests[name] = digest
    print(f"image: verifying {len(frozen_digests)} frozen entries against {root}")

    # 1. Verify every frozen entry exists with the recorded digest.
    mismatches = []
    missing = []
    for name, expected in sorted(frozen_digests.items()):
        path = root / name
        if not path.is_file():
            missing.append(name)
            continue
        if sha256(path) != expected:
            mismatches.append(name)
    if missing:
        print(f"image: FAIL — {len(missing)} frozen files absent from payload "
              f"(first 5: {missing[:5]})")
        return 1
    if mismatches:
        print(f"image: FAIL — {len(mismatches)} digests mismatch (first 5: {mismatches[:5]})")
        return 1
    print("image: all frozen entries verified")

    # 2. Verify no extra files beyond the manifest.
    extras = [str(path.relative_to(root)) for path in sorted(root.rglob("*"))
              if path.is_file() and str(path.relative_to(root)) not in frozen_digests]
    if extras:
        print(f"image: FAIL — {len(extras)} non-manifest files present "
              f"(first 5: {extras[:5]}); the core image must match the locked closure exactly")
        return 1

    # 3. Assemble output copy (content-addressed staging).
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(root, out, symlinks=True)
    payload_digest = hashlib.sha256(
        subprocess.run(["tar", "-cf", "-", "."], cwd=out,
                       capture_output=True).stdout).hexdigest()
    print(f"image: assembled at {out} (payload_sha256 {payload_digest[:16]}…)")

    # 4. Size gate.
    total = sum(path.stat().st_size for path in Path(out).rglob("*") if not path.is_symlink())
    installer = REFERENCE / "installer/BasicTeX.pkg"
    if ns.skip_compress or shutil.which("zstd") is None:
        compressed = total  # conservative upper bound when compression unavailable
        compressor = "uncompressed-upper-bound"
    else:
        handle, archive = tempfile.mkstemp(suffix=".tar.zst")
        os.close(handle)
        with tarfile.open(archive, "w") as tar:
            tar.add(out, arcname=".")
        zstd = subprocess.run(["zstd", "-q", "-3", "-o", archive + ".zst", "--rm", archive],
                              capture_output=True)
        if zstd.returncode != 0:
            compressed = total
            compressor = "uncompressed-upper-bound"
        else:
            compressed = Path(archive + ".zst").stat().st_size
            compressor = "tar.zst-3"
            Path(archive + ".zst").unlink(missing_ok=True)
    gate = max(SIZE_GATE_FLOOR, int(SIZE_GATE_MULTIPLIER * installer.stat().st_size))
    ok = compressed <= gate
    print(f"image: compressed core payload {compressed:,} bytes ({compressor}); "
          f"gate {gate:,} bytes -> {'PASS' if ok else 'FAIL'}")

    manifest = {
        "profile": "basictex-2026",
        "image_files_sha256": hashlib.sha256(
            (REFERENCE / "files.sha256").read_bytes()).hexdigest(),
        "payload_sha256": payload_digest,
        "uncompressed_size_bytes": total,
        "compressed_size_bytes": compressed,
        "compressor": compressor,
        "size_gate_bytes": gate,
        "size_gate_pass": ok,
    }
    (out / "image-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    import os
    sys.exit(main())
