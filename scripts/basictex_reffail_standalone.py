#!/usr/bin/env python3
"""Probe reference-failure interaction components standalone.

Every package that appears in a reference-failure pair from
bt100-interactions.json is compiled ALONE under the pinned BasicTeX
reference (minimal \\usepackage document). This determines whether a
pair failure is explained by one component failing on its own, or is
genuinely pair-specific.

Binaries are copied to /tmp first: executing TeX binaries directly out
of the Dropbox-synced tree intermittently hangs.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REF = ROOT / "reference" / "basictex-2026"

DOC = r"""\documentclass{article}
\usepackage{%s}
\begin{document}
Standalone probe.
\end{document}
"""

BABEL_DOC = r"""\documentclass{article}
\usepackage[%s]{babel}
\begin{document}
Standalone probe.
\end{document}
"""


def source_for(pkg: str, style: str) -> str:
    """Choose a probe document appropriate to the package family."""
    if pkg.startswith("babel-"):
        # Language packages ship .ldf files loaded through babel options,
        # never as standalone styles.
        return BABEL_DOC % pkg[len("babel-"):]
    return DOC % style


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reference", required=True)
    ap.add_argument("--ledger", type=Path, default=REF / "package-ledger.json")
    ap.add_argument("--interactions", type=Path,
                    default=REF / "bt100-interactions.json")
    ap.add_argument("--out", type=Path,
                    default=REF / "reffail-standalone.json")
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--all", action="store_true",
                    help="probe every style-providing package, not just "
                         "those appearing in reference-failure pairs")
    ap.add_argument("--include-babel", action="store_true",
                    help="also probe babel-<language> packages via the "
                         "babel-option template")
    args = ap.parse_args(argv)

    ledger = json.loads(args.ledger.read_text())
    interactions = json.loads(args.interactions.read_text())

    style_of = {}
    for row in ledger["rows"]:
        if row["loadable_styles"]:
            style_of[row["package"]] = row["loadable_styles"][0]
        elif args.include_babel and row["package"].startswith("babel-"):
            style_of[row["package"]] = row["package"]  # placeholder

    if args.all:
        targets = sorted(style_of)
    else:
        targets = sorted({pkg
                          for r in interactions["results"]
                          if r["verdict"] == "reference-failure"
                          for pkg in r["case"].split("+")})
    print(f"probing {len(targets)} packages standalone")

    root = Path(args.reference).resolve()
    # Use the reference binaries in place: copying them elsewhere breaks
    # kpathsea SELFAUTOPARENT-relative texmf discovery. The smoke runner
    # executes this tree directly without issues.
    binary_dir = root / "bin/universal-darwin"

    env = dict(os.environ)
    env["TEXMFROOT"] = str(root)
    env["PATH"] = f"{binary_dir}:{env.get('PATH', '')}"

    results = []
    counters = {"standalone-pass": 0, "standalone-fail": 0,
                "no-style": 0}
    for pkg in targets:
        entry = {"package": pkg, "style": style_of.get(pkg)}
        if pkg not in style_of:
            entry["verdict"] = "no-style"
            counters["no-style"] += 1
            results.append(entry)
            continue
        work = Path(tempfile.mkdtemp(prefix="bt100-probe-"))
        (work / "main.tex").write_text(source_for(pkg, entry["style"]))
        try:
            proc = subprocess.run(
                [str(binary_dir / "pdflatex"), "-interaction=batchmode",
                 "-halt-on-error", "main.tex"],
                cwd=work, env=env, capture_output=True, text=True,
                timeout=args.timeout)
            status = proc.returncode
        except subprocess.TimeoutExpired:
            status = None
        entry["exit"] = status

        # For family templates also record how the package behaves under
        # the plain \usepackage convention the interaction runner uses;
        # attribution needs the matching convention.
        if pkg.startswith("babel-"):
            (work / "up.tex").write_text(DOC % entry["style"])
            try:
                proc2 = subprocess.run(
                    [str(binary_dir / "pdflatex"), "-interaction=batchmode",
                     "-halt-on-error", "up.tex"],
                    cwd=work, env=env, capture_output=True, text=True,
                    timeout=args.timeout)
                up_status = proc2.returncode
            except subprocess.TimeoutExpired:
                up_status = None
            entry["usepackage_verdict"] = (
                "standalone-pass" if up_status == 0 else "standalone-fail")
        if status == 0:
            entry["verdict"] = "standalone-pass"
            counters["standalone-pass"] += 1
        else:
            log = (work / "main.log")
            err = ""
            if log.exists():
                match = re.search(r"^(! .*)$", log.read_text(errors="replace"),
                                  re.M)
                err = match.group(1) if match else ""
                if not err and status is None:
                    err = "timeout"
            entry["verdict"] = "standalone-fail"
            entry["error"] = err[:200]
            counters["standalone-fail"] += 1
        shutil.rmtree(work, ignore_errors=True)
        results.append(entry)

    out = {
        "schema_version": 1,
        "interactions_image_sha256": interactions.get("image_files_sha256"),
        "counters": counters,
        "results": results,
    }
    if args.out.exists():
        try:
            prev = json.loads(args.out.read_text())
            merged = {r["package"]: r for r in prev.get("results", [])}
            merged.update({r["package"]: r for r in results})
            all_results = sorted(merged.values(), key=lambda r: r["package"])
            out["results"] = all_results
            out["counters"] = {
                "standalone-pass": sum(
                    1 for r in all_results if r["verdict"] == "standalone-pass"),
                "standalone-fail": sum(
                    1 for r in all_results if r["verdict"] == "standalone-fail"),
                "no-style": sum(
                    1 for r in all_results if r["verdict"] == "no-style"),
            }
        except (json.JSONDecodeError, KeyError):
            pass
    args.out.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    args.out.with_suffix(".md").write_text(
        "# Standalone probes for reference-failure components\n\n"
        + "\n".join(f"- `{k}`: {v}" for k, v in counters.items()) + "\n")
    print(f"{counters} -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
