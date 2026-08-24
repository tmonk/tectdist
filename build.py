#!/usr/bin/env python3
"""Build tectdist artifacts.

The artifact contains the whole tectdist package, so the symlink farm (or any
single symlink named like a TeX tool) works against it exactly as it does
against the source tree — but with no `src/` directory needed at runtime.

Usage:
    python3 build.py               # → dist/tectdist
    python3 build.py -o out/tex    # → out/tex
    python3 build.py --python /usr/bin/python3   # override shebang
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.realpath(__file__))
PKG = os.path.join(HERE, "src", "tectdist")

sys.path.insert(0, os.path.join(HERE, "src"))
from tectdist.version import VERSION  # noqa: E402


def native_build_env():
    """Expose Homebrew's keg-only Tectonic development libraries to Cargo."""
    env = os.environ.copy()
    if sys.platform != "darwin" or not shutil.which("brew"):
        return env
    paths = []
    for formula in ("icu4c@78", "freetype", "harfbuzz", "graphite2", "libpng"):
        try:
            prefix = subprocess.run(["brew", "--prefix", formula], check=True,
                                    capture_output=True, text=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            continue
        paths.append(os.path.join(prefix, "lib", "pkgconfig"))
    if paths:
        previous = env.get("PKG_CONFIG_PATH", "")
        env["PKG_CONFIG_PATH"] = os.pathsep.join(paths + ([previous] if previous else []))
    return env


def main():
    ap = argparse.ArgumentParser(description="build a tectdist artifact")
    ap.add_argument("-o", "--output",
                    default=os.path.join(HERE, "dist", "tectdist"),
                    help="output path (default: dist/tectdist)")
    ap.add_argument("--python", default="/usr/bin/env python3",
                    help="interpreter in the shebang line")
    ap.add_argument("--native", action="store_true",
                    help="build the feature-gated embedded native binary")
    ap.add_argument("--no-embedded", action="store_true",
                    help="build native external-engine mode only")
    args = ap.parse_args()

    out = os.path.abspath(args.output)
    os.makedirs(os.path.dirname(out), exist_ok=True)

    if args.native:
        command = ["cargo", "build", "--locked", "--release", "-p", "tectdist-cli"]
        if args.no_embedded:
            command.append("--no-default-features")
        try:
            subprocess.run(command, cwd=HERE, env=native_build_env(), check=True)
            built = os.path.join(HERE, "target", "release", "tectdist")
            if os.path.realpath(built) != os.path.realpath(out):
                shutil.copy2(built, out)
            os.chmod(out, 0o755)
        except (OSError, subprocess.CalledProcessError) as exc:
            print(f"build.py: native build failed: {exc}", file=sys.stderr)
            return 1
        print(f"build.py: native tectdist {VERSION} → {out} "
              f"({os.path.getsize(out) / 1024 / 1024:.1f} MiB)")
        return 0

    tmp = tempfile.mkdtemp(prefix="tdist-build-")
    try:
        # Deflated zipapp: walk the source package directly instead of first
        # copying it to a staging tree.  This keeps builds simpler and avoids
        # an unnecessary full-directory copy while still excluding generated
        # caches and macOS metadata from the artifact.
        archive = os.path.join(tmp, "archive.zip")
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            zf.writestr("__main__.py",
                        "import sys\n"
                        "from tectdist.dispatcher import main\n"
                        "if __name__ == '__main__':\n"
                        "    sys.exit(main())\n")
            package_root = os.path.dirname(PKG)
            for root, dirs, files in os.walk(PKG):
                dirs[:] = [d for d in dirs if d != "__pycache__"
                           and not d.startswith(".")]
                for fname in files:
                    if fname.startswith("."):
                        continue
                    full = os.path.join(root, fname)
                    zf.write(full, os.path.relpath(full, package_root))
        with open(out, "wb") as f:
            f.write(f"#!{args.python}\n".encode())
            with open(archive, "rb") as src:
                shutil.copyfileobj(src, f)
        os.chmod(out, 0o755)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"build.py: tectdist {VERSION} → {out} "
          f"({os.path.getsize(out) / 1024:.1f} KiB, shebang: "
          f"#!{args.python})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
