#!/usr/bin/env python3
"""Qualify every output pipeline present in the BasicTeX image (plan B1).

Runs each core pipeline against the pinned reference image and records a
verdict per pipeline into reference/basictex-2026/pipeline-qualification.json:

  direct-pdf      pdflatex -> PDF (1 page)
  xdv-xdvipdfmx   xelatex -> XDV -> xdvipdfmx -> PDF
  dvi             latex -> DVI
  dvips           latex -> DVI -> dvips -> PS       (if dvips in image)
  metapost        mpost -> rendered figure
  tex4ht          htlatex -> HTML                   (if tex4ht in image)
  synctex         pdflatex -synctex=1 -> .synctex.gz

Usage:
    python3 scripts/basictex_pipelines.py --reference <TL root> [--output PATH]
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]

DOC = r"""\documentclass{article}
\begin{document}
Pipeline qualification document.
\end{document}
"""


def run(binary_dir, work, command, env):
    return subprocess.run(command, cwd=work, env=env,
                          capture_output=True, text=True)


def qualify(name, binary_dir, env, steps, expect):
    work = Path(tempfile.mkdtemp(prefix=f"bt100-pipe-{name}-"))
    try:
        (work / "main.tex").write_text(DOC)
        for step in steps:
            result = run(binary_dir, work, [str(binary_dir / step[0]), *step[1:]], env)
            if result.returncode != 0:
                return {"pipeline": name, "verdict": "fail",
                        "failed_step": step[0],
                        "stderr_tail": result.stderr[-300:]}
        missing = [artifact for artifact in expect if not (work / artifact).exists()]
        if missing:
            return {"pipeline": name, "verdict": "fail",
                    "missing_artifacts": missing}
        return {"pipeline": name, "verdict": "pass"}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", required=True)
    parser.add_argument("--output", default=None)
    ns = parser.parse_args(argv)

    root = Path(ns.reference).resolve()
    binary_dir = root / "bin/universal-darwin"
    out = Path(ns.output) if ns.output else \
        ROOT / "reference/basictex-2026/pipeline-qualification.json"

    env = dict(os.environ)
    env["TEXMFROOT"] = str(root)
    # Internal helper scripts (htlatex/mk4ht, epstopdf, ...) resolve engines
    # through PATH; the exact BasicTeX binaries must win over any installed
    # shim for the pipeline to be a true reference qualification.
    env["PATH"] = f"{binary_dir}:{env.get('PATH', '')}"

    def has(binary):
        return (binary_dir / binary).exists()

    results = []
    results.append(qualify(
        "direct-pdf", binary_dir, env,
        [("pdflatex", "-interaction=nonstopmode", "main.tex")], ["main.pdf"]))
    results.append(qualify(
        "xdv-xdvipdfmx", binary_dir, env,
        [("xelatex", "-no-pdf", "-interaction=nonstopmode", "main.tex"),
         ("xdvipdfmx", "main.xdv")], ["main.pdf", "main.xdv"]))
    results.append(qualify(
        "dvi", binary_dir, env,
        [("latex", "-interaction=nonstopmode", "main.tex")], ["main.dvi"]))
    if has("dvips"):
        results.append(qualify(
            "dvips", binary_dir, env,
            [("latex", "-interaction=nonstopmode", "main.tex"),
             ("dvips", "main.dvi")], ["main.ps"]))
    results.append(qualify(
        "synctex", binary_dir, env,
        [("pdflatex", "-synctex=1", "-interaction=nonstopmode", "main.tex")],
        ["main.synctex.gz"]))

    # MetaPost: a minimal figure.
    mp_work = Path(tempfile.mkdtemp(prefix="bt100-pipe-metapost-"))
    try:
        (mp_work / "fig.mp").write_text(
            "beginfig(1)\ndraw (0,0)--(10mm,0);\nendfig;\nend.\n")
        result = run(binary_dir, mp_work, [str(binary_dir / "mpost"), "fig.mp"], env)
        ok = result.returncode == 0 and (mp_work / "fig.1").exists()
        results.append({"pipeline": "metapost",
                        "verdict": "pass" if ok else "fail"})
    finally:
        shutil.rmtree(mp_work, ignore_errors=True)

    # tex4ht via htlatex script (needs perl + tex4ht binaries).
    if has("htlatex"):
        results.append(qualify(
            "tex4ht", binary_dir, env,
            [("htlatex", "main.tex")], ["main.html"]))

    passed = sum(1 for entry in results if entry["verdict"] == "pass")
    payload = {
        "schema_version": 1,
        "pipelines": results,
        "passed": passed,
        "total": len(results),
    }
    Path(ns.out if hasattr(ns, "out") else out).write_text(
        json.dumps(payload, indent=2) + "\n")
    for entry in results:
        print(f"pipeline {entry['pipeline']}: {entry['verdict']}")
    print(f"pipelines: {passed}/{len(results)} passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
