#!/usr/bin/env python3
"""Failure-equivalence check between reference BasicTeX and tectdist.

For every package with a standalone-fail probe verdict, compile the
same probe document under BOTH the pinned reference and the tectdist
candidate. BT100 requires directional equivalence: wherever the
reference fails, the candidate must fail too (and vice versa on
reference-green cases, already covered by smoke/interactions).

Outputs reference/basictex-2026/fail-equivalence.json.
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

sys.path.insert(0, str(ROOT / "scripts"))
from basictex_reffail_standalone import source_for, file_kind  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reference", required=True)
    ap.add_argument("--candidate", default=str(ROOT / "target/release/tectdist"))
    ap.add_argument("--probes", type=Path,
                    default=REF / "reffail-standalone.json")
    ap.add_argument("--ledger", type=Path, default=REF / "package-ledger.json")
    ap.add_argument("--out", type=Path, default=REF / "fail-equivalence.json")
    ap.add_argument("--timeout", type=int, default=90)
    args = ap.parse_args(argv)

    probes = json.loads(args.probes.read_text())
    ledger = json.loads(args.ledger.read_text())
    style_of = {row["package"]: (row["loadable_styles"][0]
                                 if row["loadable_styles"] else None)
                for row in ledger["rows"]}

    root = Path(args.reference).resolve()
    binary_dir = root / "bin/universal-darwin"
    env = dict(os.environ)
    env["TEXMFROOT"] = str(root)
    env["PATH"] = f"{binary_dir}:{env.get('PATH', '')}"

    # Candidate profile client: symlink named pdflatex with profile env.
    link_dir = Path(tempfile.mkdtemp(prefix="bt100-feq-links-"))
    os.symlink(Path(args.candidate).resolve(), link_dir / "pdflatex")
    cand_env = dict(env)
    cand_env["TECTDIST_PROFILE"] = "basictex-2026"
    cand_env["TECTDIST_BASICTEX_ROOT"] = str(root)
    cand_env["PATH"] = f"{link_dir}:{env['PATH']}"

    def run(binary, work, src, e):
        try:
            proc = subprocess.run(
                [str(binary), "-interaction=batchmode", "-halt-on-error", src],
                cwd=work, env=e, capture_output=True, text=True,
                timeout=args.timeout)
            return proc.returncode
        except subprocess.TimeoutExpired:
            return None

    rows = []
    counters = {"equivalent-fail": 0, "equivalent-pass": 0,
                "mismatch": 0}
    for entry in probes["results"]:
        pkg = entry["package"]
        if entry.get("verdict") != "standalone-fail":
            continue
        style = style_of.get(pkg) or entry["style"]
        if not style:
            continue
        work = Path(tempfile.mkdtemp(prefix="bt100-feq-"))
        kind = file_kind(binary_dir, env, style)
        (work / "main.tex").write_text(source_for(pkg, style, kind))
        ref_status = run(binary_dir / "pdflatex", work, "main.tex", env)
        cand_status = run(link_dir / "pdflatex", work, "main.tex", cand_env)
        if (ref_status == 0) == (cand_status == 0):
            verdict = ("equivalent-pass" if ref_status == 0
                       else "equivalent-fail")
        else:
            verdict = "mismatch"
        counters[verdict] += 1
        rows.append({"package": pkg, "ref_exit": ref_status,
                     "candidate_exit": cand_status, "verdict": verdict})
        shutil.rmtree(work, ignore_errors=True)

    shutil.rmtree(link_dir, ignore_errors=True)

    out = {"schema_version": 1, "counters": counters, "rows": rows}
    args.out.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(f"{counters} -> {args.out}")
    mismatches = [r["package"] for r in rows if r["verdict"] == "mismatch"]
    if mismatches:
        print("MISMATCHES:", ", ".join(mismatches))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
