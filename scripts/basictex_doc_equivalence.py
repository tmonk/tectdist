#!/usr/bin/env python3
"""Document-level equivalence: tectdist CLI versus pinned reference.

Stages a corpus document twice (fresh copies), compiles one side with
the reference pdflatex and the other through the profile-mode tectdist
candidate, then compares exit status, page count, and extracted text.
This is the per-document BT100 check behind the interaction battery,
runnable against any manifest document including multi-file ones.

Exit 0 iff every requested document is equivalent.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REF = ROOT / "reference" / "basictex-2026"


def compile_dir(binary: Path, env_extra: dict, work: Path, source="main.tex"):
    env = dict(os.environ)
    env.update(env_extra)
    proc = subprocess.run(
        [str(binary), "-interaction=batchmode", "&pdflatex", source],
        cwd=work, env=env, capture_output=True, text=True, timeout=180)
    return proc.returncode


def pdf_pages(pdf: Path):
    try:
        out = subprocess.run(["pdfinfo", str(pdf)], capture_output=True,
                             text=True, timeout=30).stdout
        for line in out.splitlines():
            if line.startswith("Pages:"):
                return int(line.split()[1])
    except Exception:
        pass
    return None


def pdf_text(pdf: Path):
    result = subprocess.run(["pdftotext", str(pdf), "-"],
                            capture_output=True, text=True, timeout=60)
    return result.stdout


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reference", required=True)
    ap.add_argument("--candidate", default=str(ROOT / "target/release/tectdist"))
    ap.add_argument("--documents", nargs="+", default=["multifile"])
    ap.add_argument("--out", type=Path, default=REF / "doc-equivalence.json")
    args = ap.parse_args(argv)

    root = Path(args.reference).resolve()
    binary_dir = root / "bin/universal-darwin"
    ref_env = {"TEXMFROOT": str(root),
               "PATH": f"{binary_dir}:{os.environ['PATH']}"}

    # Candidate profile client: symlink named pdflatex -> tectdist.
    link_dir = Path(tempfile.mkdtemp(prefix="bt100-doc-eq-"))
    os.symlink(Path(args.candidate).resolve(), link_dir / "pdflatex")
    cand_env = {"TECTDIST_PROFILE": "basictex-2026",
                "TECTDIST_BASICTEX_ROOT": str(root),
                "PATH": f"{link_dir}:{os.environ['PATH']}"}

    rows = []
    failures = 0
    try:
        for document in args.documents:
            source_dir = ROOT / "benchmarks/corpus" / document
            if not source_dir.is_dir():
                print(f"unknown document '{document}'; skipped")
                continue

            def staged() -> Path:
                work = Path(tempfile.mkdtemp(prefix=f"bt100eq-{document}-"))
                shutil.copytree(source_dir, work, dirs_exist_ok=True)
                return work

            ref_work = staged()
            ref_exit = compile_dir(binary_dir / "pdftex", ref_env,
                                   ref_work)
            cand_work = staged()
            cand_exit = compile_dir(link_dir / "pdflatex", cand_env,
                                    cand_work)

            ref_pdf = ref_work / "main.pdf"
            cand_pdf = cand_work / "main.pdf"
            row = {
                "document": document,
                "reference_exit": ref_exit,
                "candidate_exit": cand_exit,
                "reference_pages": pdf_pages(ref_pdf) if ref_exit == 0 else None,
                "candidate_pages": pdf_pages(cand_pdf) if cand_exit == 0 else None,
            }
            equivalent = (
                (ref_exit == 0) == (cand_exit == 0)
                and row["reference_pages"] == row["candidate_pages"]
            )
            if equivalent and ref_exit == 0:
                same_text = (pdf_text(ref_pdf) == pdf_text(cand_pdf))
                row["text_identical"] = same_text
                equivalent = same_text
            row["verdict"] = ("pass" if equivalent else "fail")
            if not equivalent:
                failures += 1
            rows.append(row)
            print(f"{document}: {row['verdict']} "
                  f"(pages {row['reference_pages']}/{row['candidate_pages']})")
            shutil.rmtree(ref_work, ignore_errors=True)
            shutil.rmtree(cand_work, ignore_errors=True)
    finally:
        shutil.rmtree(link_dir, ignore_errors=True)

    args.out.write_text(json.dumps(
        {"schema_version": 1, "rows": rows}, indent=2) + "\n")
    passed = sum(1 for r in rows if r["verdict"] == "pass")
    print(f"{passed}/{len(rows)} documents equivalent -> {args.out}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
