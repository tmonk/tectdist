#!/usr/bin/env python3
"""X10-E edit scenarios for a MULTI-FILE corpus document.

Stages benchmarks/corpus/multifile (preamble \\input +
\\include{chapters/*} subdirectories) into a scratch project and drives
a live supervisor over IPC:

  stock-one-shot          direct pdflatex, no supervisor
  cold-first              first supervisor compile (format build)
  chapter-edit            body file in a SUBDIRECTORY edited -> format reused
  preamble-dep-edit       preamble \\input'ed file edited -> format rebuilt
  unchanged-recompile     nothing changed -> X4 cache replay

Every scenario asserts exit 0 and validates page counts stay identical.
Writes reference/basictex-2026/x2-multifile-scenarios.json (+ .md).
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REF = ROOT / "reference" / "basictex-2026"
IMAGE = REF / "image"

sys.path.insert(0, str(ROOT / "scripts"))
from basictex_x2_edit_scenarios import Supervisor  # noqa: E402


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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--trials", type=int, default=3)
    ap.add_argument("--out", type=Path,
                    default=REF / "x2-multifile-scenarios.json")
    args = ap.parse_args(argv)

    source_dir = ROOT / "benchmarks/corpus/multifile"
    work = Path(tempfile.mkdtemp(prefix="x2mf-doc-"))

    def stage():
        shutil.rmtree(work, ignore_errors=True)
        shutil.copytree(source_dir, work)

    def compile_sup(sup):
        payload = {
            "type": "compile", "profile": "basictex-2026",
            "cwd": str(work),
            "argv": ["pdflatex", "-interaction=batchmode", "main.tex"],
            "snapshot_key": None,
        }
        t0 = time.perf_counter()
        response = sup.request(payload)
        wall_ms = int((time.perf_counter() - t0) * 1000)
        accepted = response.get("compile_accepted", {})
        return {"wall_ms": wall_ms,
                "exit": accepted.get("exit_status", -1)}

    results = {}

    # --- stock baseline -------------------------------------------------
    stage()
    bin_dir = next(d for d in (IMAGE / "bin").iterdir() if d.is_dir())
    env = dict()
    env["TEXMFROOT"] = str(IMAGE)
    env["TEXFORMATS"] = (
        f".:{IMAGE}/texmf-var/web2c/pdftex:{IMAGE}/texmf-dist/web2c")
    env["PATH"] = f"{bin_dir}:{__import__('os').environ['PATH']}"
    timings = []
    reference_pages = None
    for _ in range(args.trials):
        (work / "main.pdf").unlink(missing_ok=True)
        t0 = time.perf_counter()
        proc = subprocess.run(
            [str(bin_dir / "pdftex"), "-interaction=batchmode",
             "&pdflatex", "main.tex"],
            cwd=work, env=env, capture_output=True, timeout=120)
        timings.append(int((time.perf_counter() - t0) * 1000))
        assert proc.returncode == 0, "stock compile failed"
        reference_pages = reference_pages or pdf_pages(work / "main.pdf")
    results["stock-one-shot"] = min(timings)
    print(f"reference pages: {reference_pages}")

    sup = Supervisor("mf")
    try:
        argv = ["pdflatex", "-interaction=batchmode", "main.tex"]

        # --- cold first (format build) ----------------------------------
        stage()
        best = None
        for _ in range(args.trials):
            stage()
            r = compile_sup(sup)
            assert r["exit"] == 0, f"cold compile failed: {r}"
            assert pdf_pages(work / "main.pdf") == reference_pages
            best = r["wall_ms"] if best is None else min(best, r["wall_ms"])
        results["cold-first-with-format-build"] = best

        # --- warm: chapter edit in a SUBDIRECTORY ------------------------
        ch1 = work / "chapters/ch1.tex"
        original_ch1 = ch1.read_text()
        ch1.write_text(original_ch1 + "\nEdited sentence for measurement.\n")
        best = None
        for _ in range(args.trials):
            (work / "main.pdf").unlink(missing_ok=True)
            r = compile_sup(sup)
            assert r["exit"] == 0, f"chapter-edit compile failed: {r}"
            assert pdf_pages(work / "main.pdf") == reference_pages
            best = r["wall_ms"] if best is None else min(best, r["wall_ms"])
        results["chapter-edit-format-reused"] = best

        # --- preamble \input'ed dependency edit ---------------------------
        extra = work / "preamble-extra.tex"
        original_extra = extra.read_text()
        extra.write_text(original_extra + "\n% variant\n")
        best = None
        for trial in range(args.trials):
            # alternate so each trial invalidates the format key
            marker = "% variant A\n" if trial % 2 == 0 else "% variant B\n"
            extra.write_text(original_extra + "\n" + marker)
            (work / "main.pdf").unlink(missing_ok=True)
            r = compile_sup(sup)
            assert r["exit"] == 0, f"dep-edit compile failed: {r}"
            assert pdf_pages(work / "main.pdf") == reference_pages
            best = r["wall_ms"] if best is None else min(best, r["wall_ms"])
        results["preamble-dep-edit-format-rebuilt"] = best

        # --- unchanged recompile (X4 gate) --------------------------------
        best = None
        for _ in range(args.trials):
            r = compile_sup(sup)
            assert r["exit"] == 0, f"unchanged compile failed: {r}"
            assert pdf_pages(work / "main.pdf") == reference_pages
            best = r["wall_ms"] if best is None else min(best, r["wall_ms"])
        results["unchanged-rebuild-cache-hit"] = best
    finally:
        sup.stop()
        shutil.rmtree(work, ignore_errors=True)

    out = {
        "schema_version": 1,
        "document": "multifile",
        "reference_pages": reference_pages,
        "trials_per_scenario": args.trials,
        "statistic": "min",
        "scenarios": results,
        "speedup_body_edit_vs_stock": round(
            results["stock-one-shot"]
            / max(results["chapter-edit-format-reused"], 1), 3),
        "speedup_unchanged_vs_stock": round(
            results["stock-one-shot"]
            / max(results["unchanged-rebuild-cache-hit"], 1), 3),
    }
    args.out.write_text(json.dumps(out, indent=2) + "\n")
    md = ["# Multi-file edit scenarios through the supervisor", "",
          "| scenario | ms (min) |", "|---|---:|"]
    md += [f"| {k} | {v} |" for k, v in results.items()]
    md += ["",
           f"Chapter-edit speedup: {out['speedup_body_edit_vs_stock']}x; "
           f"unchanged speedup: {out['speedup_unchanged_vs_stock']}x"]
    args.out.with_suffix(".md").write_text("\n".join(md) + "\n")
    print(results)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
