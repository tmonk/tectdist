#!/usr/bin/env python3
"""Product-level adversarial mutation corpus (plan X4 acceptance, §18.3).

Verifies that tectdist's rerun and reuse decisions stay correct under
mutations designed to defeat timestamp- or size-based caching:

1. same bytes, changed mtime          -> rebuild succeeds, output unchanged
2. changed bytes, same size + mtime   -> output MUST reflect the new content
3. included-file edit                 -> output MUST reflect the include
4. bibliography edit, same size+mtime -> citations MUST update

Usage:
    python3 tests/mutation_corpus.py [--native /path/to/tectdist]

Exits nonzero on the first stale-output or correctness failure.
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmarks"))

from runner.correctness import _pdf_text  # noqa: E402


def compile_document(binary, directory, main="main.tex"):
    # argv[0] dispatch requires a recognised tool name; link the binary under
    # its canonical name inside each scratch directory.
    link = Path(directory) / "tectdist"
    if not link.exists():
        os.symlink(Path(binary).resolve(), link)
    return subprocess.run([str(link), main], cwd=directory,
                          capture_output=True, text=True)


def pdf_text(directory, stem="main"):
    text, error = _pdf_text(str(Path(directory) / f"{stem}.pdf"))
    if error:
        raise RuntimeError(error)
    return text


def force_state(path, mtime):
    os.utime(path, (mtime, mtime))


def case_same_mtime_same_size(binary, work):
    """Same bytes with a bumped mtime: safe to reuse, must stay correct."""
    source = work / "main.tex"
    source.write_text("\\documentclass{article}\\begin{document}Mutation A\\end{document}\n")
    assert compile_document(binary, work).returncode == 0
    first = pdf_text(work)
    stamp = time.time() + 1234
    force_state(source, stamp)
    assert compile_document(binary, work).returncode == 0
    second = pdf_text(work)
    if "Mutation A" not in second:
        raise SystemExit("mutation corpus FAILED: unchanged-input rerun lost content")
    if "Mutation A" not in first:
        raise SystemExit("mutation corpus FAILED: baseline content missing")


def case_changed_bytes_same_size_and_mtime(binary, work):
    """Adversarial: different bytes padded to identical size and mtime."""
    body_a = "Mutation Alpha"
    body_b = "Mutation Omega"  # identical length
    assert len(body_a) == len(body_b)
    source = work / "main.tex"
    source.write_text(f"\\documentclass{{article}}\\begin{{document}}{body_a}\\end{{document}}\n")
    original_stat = None
    assert compile_document(binary, work).returncode == 0
    original_stat = source.stat()
    text_a = pdf_text(work)
    if body_a not in text_a:
        raise SystemExit("mutation corpus FAILED: baseline content missing")
    # Rewrite bytes; restore exact size (already equal) and mtime.
    source.write_text(f"\\documentclass{{article}}\\begin{{document}}{body_b}\\end{{document}}\n")
    assert source.stat().st_size == original_stat.st_size, \
        "test setup broken: sizes differ"
    force_state(source, original_stat.st_mtime)
    assert compile_document(binary, work).returncode == 0
    text_b = pdf_text(work)
    if body_b not in text_b:
        raise SystemExit(
            "mutation corpus FAILED: stale output served after same-size/same-mtime edit")
    print("changed-bytes-same-size-mtime: updated correctly")


def case_included_file_edit(binary, work):
    include = work / "part.tex"
    include.write_text("Included Part One")
    (work / "main.tex").write_text(
        "\\documentclass{article}\\begin{document}\\input{part}\\end{document}\n")
    assert compile_document(binary, work).returncode == 0
    if "Part One" not in pdf_text(work):
        raise SystemExit("mutation corpus FAILED: include baseline missing")
    include.write_text("Included Part Two")
    assert compile_document(binary, work).returncode == 0
    text = pdf_text(work)
    if "Part Two" not in text:
        raise SystemExit("mutation corpus FAILED: stale include content")
    print("included-file-edit: updated correctly")


def case_bibliography_edit(binary, work):
    bib = work / "refs.bib"
    bib.write_text(
        "@article{k1, author={Knuth}, title={First Title}, journal={J}, year={1984}}\n")
    (work / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n\\cite{k1}\n\\bibliographystyle{plain}\n"
        "\\bibliography{refs}\n\\end{document}\n")
    stat_before = bib.stat()
    assert compile_document(binary, work).returncode == 0
    first = pdf_text(work)
    if "Knuth" not in first:
        raise SystemExit("mutation corpus FAILED: bibliography baseline missing")
    # Same-size title change with restored mtime.
    bib.write_text(
        "@article{k1, author={Knuth}, title={Sixth Title}, journal={J}, year={1984}}\n")
    assert bib.stat().st_size == stat_before.st_size, "test setup broken: bib sizes differ"
    force_state(bib, stat_before.st_mtime)
    assert compile_document(binary, work).returncode == 0
    second = pdf_text(work)
    # plain.bst renders titles in sentence case: "Sixth title."
    if "Sixth title" not in second:
        raise SystemExit(
            "mutation corpus FAILED: stale bibliography after same-size/same-mtime edit")
    print("bibliography-edit: updated correctly")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native", default=os.environ.get("TECTDIST_NATIVE"),
                        help="tectdist binary to exercise (default: $TECTDIST_NATIVE)")
    ns = parser.parse_args(argv)
    if not ns.native or not Path(ns.native).is_file():
        raise SystemExit("provide --native /path/to/tectdist or $TECTDIST_NATIVE")

    cases = [
        ("same-mtime-same-size", case_same_mtime_same_size),
        ("changed-bytes-same-size-and-mtime", case_changed_bytes_same_size_and_mtime),
        ("included-file-edit", case_included_file_edit),
        ("bibliography-edit", case_bibliography_edit),
    ]
    for name, function in cases:
        with tempfile.TemporaryDirectory(prefix=f"tectdist-mut-{name}-") as temporary:
            function(ns.native, Path(temporary))
            print(f"{name}: ok")
    print("mutation corpus passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
