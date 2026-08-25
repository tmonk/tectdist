#!/usr/bin/env python3
"""Build a per-project preamble snapshot format (plan X2 / §6.4).

Extracts the preamble from a source document, appends \\dump, and runs the
fork-server pdftex in -ini mode WITHOUT the socket environment (so the hook
is inert and the dump completes). The resulting format contains all
class/package state preloaded; fork-server children resume from this state
at full speed.

Usage:
    python3 scripts/basictex_project_format.py \
        --source <main.tex> --image <BT image root> \
        --output-dir <project dir> [--format-name proj]

The format is written as <output-dir>/<format-name>.fmt and usable via a
first-line &reference or -fmt=<name> flag.
"""
import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


def extract_preamble(source_text):
    """Return (preamble, body) split at the first ^\\begin{document}."""
    match = re.search(r"(?m)^\\begin\{document\}", source_text)
    if match:
        return source_text[:match.start()], source_text[match.start():]
    # No begin{document}: entire input is preamble; body is empty.
    return source_text, "% no body: input had no \\begin{document}\n\\end{document}\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True,
                        help="path to the document's main .tex file")
    parser.add_argument("--image", required=True,
                        help="BasicTeX image root (TEXMFROOT)")
    parser.add_argument("--output-dir", default=None,
                        help="where to write the .fmt (default: source dir)")
    parser.add_argument("--format-name", default=None,
                        help="fmt name (default: <source stem>-pre)")
    parser.add_argument("--extra-packages", nargs="*",
                        help="additional \\usepackage targets to include")
    ns = parser.parse_args(argv)

    source = Path(ns.source).resolve()
    if not source.is_file():
        raise SystemExit(f"source not found: {source}")
    image_root = Path(ns.image).resolve()
    out_dir = Path(ns.output_dir) if ns.output_dir else source.parent
    fmt_name = ns.format_name or (source.stem + "-pre")

    text = source.read_text(errors="replace")
    preamble, body = extract_preamble(text)
    if ns.extra_packages:
        for pkg in ns.extra_packages:
            preamble += f"\\usepackage{{{pkg}}}\n"
    preamble += "\\dump\n"

    preamble_file = out_dir / f"{fmt_name}.tex"
    preamble_file.parent.mkdir(parents=True, exist_ok=True)
    preamble_file.write_text(preamble)
    body_file = out_dir / f"{fmt_name}-body.tex"
    body_file.write_text(body)
    print(f"project-format: preamble written -> {preamble_file}")
    print(f"project-format: paired body   -> {body_file}")

    binary = image_root / "bin/forkproto/pdftex"
    if not binary.is_file():
        # Fall back to universal-darwin/pdftex.
        binary = next(
            (d / "pdftex" for d in sorted((image_root / "bin").iterdir(), reverse=True)
             if (d / "pdftex").is_file()),
            None,
        )
    if binary is None or not binary.is_file():
        raise SystemExit("no pdftex binary found in image")

    env = dict(os.environ)
    env["TEXMFROOT"] = str(image_root)
    # Do NOT set TEXMFCNF: pointing it at the image root hides
    # texmf.cnf, so the engine starts with compiled-in array bounds and
    # aborts loading the stock fmt with "! Must increase the
    # hyph_size". Leaving TEXMFCNF unset lets the normal cnf lookup
    # provide the values the fmt was built with.
    # texmf-var/web2c/pdftex holds the stock pdflatex.fmt; without it
    # kpathsea falls back to mktexfmt and the ini run aborts.
    env["TEXFORMATS"] = (
        f".:{out_dir}:{image_root}/texmf-var/web2c/pdftex:"
        f"{image_root}/texmf-dist/web2c")
    env["PATH"] = f"{binary.parent}:{env.get('PATH', '')}"
    env.pop("TECTDIST_FORKSERVER_SOCKET", None)
    env.pop("TECTDIST_FORK_JOB", None)

    result = subprocess.run(
        [str(binary), "-ini", "-interaction=batchmode",
         "&pdflatex", preamble_file.name],
        cwd=str(out_dir), env=env, capture_output=True, text=True,
        timeout=120,
    )

    expected_fmt = out_dir / f"{fmt_name}.fmt"
    if not expected_fmt.is_file():
        print(f"project-format: FAILED — no {expected_fmt} produced", file=sys.stderr)
        if result.stdout:
            print(result.stdout[-500:], file=sys.stderr)
        if result.stderr:
            print(result.stderr[-500:], file=sys.stderr)
        return 1

    size = expected_fmt.stat().st_size
    digest = hashlib.sha256(expected_fmt.read_bytes()).hexdigest()
    print(f"project-format: OK — {expected_fmt} ({size:,} bytes, "
          f"sha256 {digest[:16]}…)")
    return 0


import hashlib
import os

if __name__ == "__main__":
    sys.exit(main())
