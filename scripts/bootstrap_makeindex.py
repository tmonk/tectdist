#!/usr/bin/env python3
"""Build the small upstream MakeIndex tool without installing TeX Live."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

URL = "https://mirrors.ibiblio.org/CTAN/indexing/makeindex.zip"
SHA256 = "49afc4afccd5a9871aa0b51831a89556193d244bde4e25b57c2c9b1725825887"
SOURCES = ("genind.c", "mkind.c", "qsort.c", "scanid.c", "scanst.c", "sortid.c")


def build(destination):
    destination = Path(destination).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="tectdist-makeindex-") as temporary:
        root = Path(temporary)
        archive = root / "makeindex.zip"
        with urllib.request.urlopen(URL, timeout=60) as response, archive.open("wb") as stream:
            shutil.copyfileobj(response, stream)
        actual = hashlib.sha256(archive.read_bytes()).hexdigest()
        if actual != SHA256:
            raise RuntimeError("MakeIndex source checksum mismatch: " + actual)
        with zipfile.ZipFile(archive) as package:
            package.extractall(root / "source")
        source = root / "source" / "makeindex" / "src"
        compiler = os.environ.get("CC") or shutil.which("cc")
        if not compiler:
            raise RuntimeError("a C compiler is required to build MakeIndex")
        output = root / "makeindex"
        subprocess.run([compiler, "-O2", *(str(source / name) for name in SOURCES),
                        "-o", str(output)], check=True)
        os.chmod(output, 0o755)
        temporary_output = destination.with_name(destination.name + ".tmp")
        shutil.copy2(output, temporary_output)
        os.replace(temporary_output, destination)
    return destination


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 1:
        print("usage: bootstrap_makeindex.py OUTPUT", file=sys.stderr)
        return 2
    output = build(arguments[0])
    print(f"bootstrap_makeindex.py: MakeIndex {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
