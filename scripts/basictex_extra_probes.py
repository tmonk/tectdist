#!/usr/bin/env python3
"""Extra-family probes for packages without loadable styles (BT100).

Two generic families, both compiled under the pinned reference AND the
profile-mode tectdist candidate:

  font  — package provides .tfm run files: probe compiles
          \\font\\probe=<stem} plus sample text
  mpost — package provides .mp run files: probe runs mpost on a
          wrapper that \\inputs the package's primary .mp

Verdicts (merged into reffail-standalone.json so the report/classify
pipeline picks them up):
  equivalent-pass   both sides compile
  equivalent-fail   both sides fail identically
  mismatch          directional divergence (gates FAIL)
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

FONT_DOC = "\\font\\probe=%s\\relax\n\\begin{document}\n{\\probe Probe text 123}\n\\end{document}\n"


def read_tlpdb_runfiles(path: Path):
    packages = {}
    current = None
    in_run = False
    for line in path.read_text(errors="replace").splitlines():
        if line.startswith("name "):
            current = {"tfm": [], "mp": []}
            packages[line[5:].strip()] = current
            in_run = False
        elif current is not None:
            if not line.startswith(" "):
                word = line.split(" ", 1)[0]
                in_run = word == "runfiles"
                continue
            if in_run:
                for f in line.split():
                    if f.endswith(".tfm") and not current["tfm"]:
                        current["tfm"].append(f)
                    elif f.endswith(".mp") and not current["mp"]:
                        current["mp"].append(f)
    return packages


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reference", required=True)
    ap.add_argument("--candidate", default=str(ROOT / "target/release/tectdist"))
    ap.add_argument("--ledger", type=Path, default=REF / "package-ledger.json")
    ap.add_argument("--tlpdb", type=Path, default=REF / "texlive.tlpdb")
    ap.add_argument("--out", type=Path,
                    default=REF / "extra-family-probes.json")
    ap.add_argument("--timeout", type=int, default=90)
    args = ap.parse_args(argv)

    ledger = json.loads(args.ledger.read_text())
    # Only probe packages the report currently considers UNTESTED.
    report = json.loads((REF / "bt100-report.json").read_text())
    untested = {row["package"] for row in report["rows"]
                if row["bt100_verdict"] == "untested"}

    packages = read_tlpdb_runfiles(args.tlpdb)

    targets = []
    for pkg in sorted(untested):
        meta = packages.get(pkg)
        if not meta:
            continue
        if meta["tfm"] and meta["mp"]:
            continue  # ambiguous; keep single-family
        if meta["tfm"]:
            targets.append((pkg, "font", meta["tfm"][0][:-4]))
        elif meta["mp"]:
            targets.append((pkg, "mpost", meta["mp"][0][:-3]))
    print(f"probing {len(targets)} extra-family packages "
          f"(font={sum(1 for t in targets if t[1]=='font')}, "
          f"mpost={sum(1 for t in targets if t[1]=='mpost')})")

    root = Path(args.reference).resolve()
    binary_dir = root / "bin/universal-darwin"
    env = dict(os.environ)
    env["TEXMFROOT"] = str(root)
    env["PATH"] = f"{binary_dir}:{env.get('PATH', '')}"

    link_dir = Path(tempfile.mkdtemp(prefix="bt100-extra-links-"))
    for engine in ("pdflatex", "mpost"):
        os.symlink(Path(args.candidate).resolve(), link_dir / engine)

    def run_ref(cmd, work):
        try:
            return subprocess.run(cmd, cwd=work, env=env,
                                  capture_output=True,
                                  timeout=args.timeout).returncode
        except subprocess.TimeoutExpired:
            return None

    def run_cand(cmd, work):
        cenv = dict(env)
        cenv["TECTDIST_PROFILE"] = "basictex-2026"
        cenv["TECTDIST_BASICTEX_ROOT"] = str(root)
        cenv["PATH"] = f"{link_dir}:{env['PATH']}"
        try:
            return subprocess.run(cmd, cwd=work, env=cenv,
                                  capture_output=True,
                                  timeout=args.timeout).returncode
        except subprocess.TimeoutExpired:
            return None

    results = []
    counters = {"equivalent-pass": 0, "equivalent-fail": 0, "mismatch": 0}
    for pkg, family, stem in targets:
        work = Path(tempfile.mkdtemp(prefix="bt100-extra-"))
        if family == "font":
            source = FONT_DOC % stem
            (work / "probe.tex").write_text(source)
            ref_cmd = [str(binary_dir / "pdflatex"), "-interaction=batchmode",
                       "-halt-on-error", "&pdflatex", "probe.tex"]
            cand_cmd = [str(link_dir / "pdflatex"), "-interaction=batchmode",
                        "-halt-on-error", "&pdflatex", "probe.tex"]
        else:
            (work / "probe.mp").write_text(f"input {stem};\nend.\n")
            ref_cmd = [str(binary_dir / "mpost"), "-interaction=batchmode",
                       "probe.mp"]
            cand_cmd = [str(link_dir / "mpost"), "-interaction=batchmode",
                        "probe.mp"]

        ref_exit = run_ref(ref_cmd, work)
        cand_exit = run_cand(cand_cmd, work)

        if (ref_exit == 0) == (cand_exit == 0):
            verdict = ("equivalent-pass" if ref_exit == 0
                       else "equivalent-fail")
        else:
            verdict = "mismatch"
        counters[verdict] += 1
        entry = {"package": pkg, "family": family, "style": stem,
                 "verdict": verdict,
                 "ref_exit": ref_exit, "candidate_exit": cand_exit}
        if verdict != "equivalent-pass":
            log = work / ("probe.log" if family == "font" else "probe.log")
            if log.exists():
                for line in log.read_text(errors="replace").splitlines():
                    if line.startswith("!"):
                        entry["error"] = line[:120]
                        break
        results.append(entry)
        shutil.rmtree(work, ignore_errors=True)

    shutil.rmtree(link_dir, ignore_errors=True)

    out_path = args.out
    out = {"schema_version": 1, "counters": counters, "results": results}
    out_path.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")

    # Merge into reffail-standalone.json so report/classify see them.
    sa_path = REF / "reffail-standalone.json"
    if sa_path.exists():
        merged = json.loads(sa_path.read_text())
        by_pkg = {r["package"]: r for r in merged.get("results", [])}
        for r in results:
            by_pkg[r["package"]] = {
                "package": r["package"],
                "style": r.get("style"),
                "kind": r.get("family"),
                "verdict": ("standalone-pass"
                            if r["verdict"] == "equivalent-pass"
                            else "standalone-fail"),
                "error": r.get("error", ""),
            }
        merged_results = sorted(by_pkg.values(),
                                key=lambda r: r["package"])
        merged["results"] = merged_results
        merged["counters"] = {
            "standalone-pass": sum(
                1 for r in merged_results if r["verdict"] == "standalone-pass"),
            "standalone-fail": sum(
                1 for r in merged_results if r["verdict"] == "standalone-fail"),
            "no-style": sum(
                1 for r in merged_results if r["verdict"] == "no-style"),
        }
        sa_path.write_text(json.dumps(merged, indent=2, sort_keys=True) + "\n")

    print(counters, "->", out_path)
    mismatches = [r["package"] for r in results if r["verdict"] == "mismatch"]
    if mismatches:
        print("MISMATCHES:", ", ".join(mismatches))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
