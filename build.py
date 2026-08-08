#!/usr/bin/env python3
"""Build dist/tectdist — a single self-contained executable (Python zipapp).

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


def main():
    ap = argparse.ArgumentParser(description="build the tectdist zipapp")
    ap.add_argument("-o", "--output",
                    default=os.path.join(HERE, "dist", "tectdist"),
                    help="output path (default: dist/tectdist)")
    ap.add_argument("--python", default="/usr/bin/env python3",
                    help="interpreter in the shebang line")
    args = ap.parse_args()

    out = os.path.abspath(args.output)
    os.makedirs(os.path.dirname(out), exist_ok=True)

    tmp = tempfile.mkdtemp(prefix="tdist-build-")
    try:
        # stage <stage>/tectdist/... and a root __main__.py so the archive
        # runs the `tectdist` package (relative imports work inside it)
        stage_pkg = os.path.join(tmp, "tectdist")
        shutil.copytree(PKG, stage_pkg)
        with open(os.path.join(tmp, "__main__.py"), "w") as f:
            f.write("import sys\n"
                    "from tectdist.dispatcher import main\n"
                    "if __name__ == '__main__':\n"
                    "    sys.exit(main())\n")
        for root, dirs, files in os.walk(stage_pkg):
            for d in list(dirs):
                if d == "__pycache__":
                    shutil.rmtree(os.path.join(root, d))
                    dirs.remove(d)
            for fname in list(files):
                if fname.startswith("."):   # .DS_Store and friends: no macOS
                    os.remove(os.path.join(root, fname))   # metadata in the artifact
                    files.remove(fname)
        # deflated zipapp: same layout as `python -m zipapp` but compressed,
        # which shrinks the artifact (46.8 KiB -> ~14 KiB) and speeds up cold
        # reads; behaviour is identical (imports resolve the same)
        archive = os.path.join(tmp, "archive.zip")
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            zf.writestr("__main__.py",
                        "import sys\n"
                        "from tectdist.dispatcher import main\n"
                        "if __name__ == '__main__':\n"
                        "    sys.exit(main())\n")
            for root, dirs, files in os.walk(stage_pkg):
                for fname in files:
                    full = os.path.join(root, fname)
                    zf.write(full, os.path.relpath(full, tmp))
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
