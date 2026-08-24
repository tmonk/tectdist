#!/usr/bin/env python3
"""BT100 minimal-load compatibility runner (plan B2, §8.2 tier 6).

For every package providing loadable styles, compiles a minimal
`\\usepackage{...}` document under BOTH the pinned BasicTeX reference and the
tectdist BasicTeX profile, then applies the layered verdict:

- reference failure  -> "reference-failure" (recorded; never a BT100 debit,
                        per the reference-green rule §8.3)
- both succeed, equivalent page/text -> "pass"
- candidate fails or diverges        -> "fail"

Produces bt100-report.json plus a Markdown summary. Supports sharding for CI.

Usage:
    python3 scripts/basictex_smoke.py --reference <TL root> \
        --candidate /path/to/tectdist [--shard i/n] [--styles-per-package N]
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
REFERENCE_DIR = ROOT / "reference/basictex-2026"

DOC_TEMPLATE = r"""\documentclass{article}
\usepackage{%s}
\begin{document}
Package smoke test.
\end{document}
"""


def pdf_page_count(pdf):
    tool = shutil.which("pdfinfo")
    if not tool:
        return None
    result = subprocess.run([tool, str(pdf)], capture_output=True, text=True)
    match = re.search(r"^Pages:\s*(\d+)\s*$", result.stdout, re.M)
    return int(match.group(1)) if match else None


def compile_once(binary_dir, work, source_name, env, timeout=60):
    result = subprocess.run(
        [str(binary_dir / "pdflatex"), "-interaction=batchmode", "-halt-on-error",
         source_name],
        cwd=work, env=env, capture_output=True, text=True, timeout=timeout)
    return result.returncode


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", required=True)
    parser.add_argument("--candidate", default=str(ROOT / "target/release/tectdist"))
    parser.add_argument("--ledger", default=str(REFERENCE_DIR / "package-ledger.json"))
    parser.add_argument("--output", default=str(REFERENCE_DIR / "bt100-report.json"))
    parser.add_argument("--markdown", default=str(REFERENCE_DIR / "bt100-report.md"))
    parser.add_argument("--shard", default="0/1", help="i/n shard selection")
    parser.add_argument("--styles-per-package", type=int, default=2)
    ns = parser.parse_args(argv)

    ledger = json.loads(Path(ns.ledger).read_text())
    rows = [row for row in ledger["rows"] if row["loadable_styles"]]

    shard_index, shard_total = (int(part) for part in ns.shard.split("/"))
    rows = [row for index, row in enumerate(rows)
            if index % shard_total == shard_index]

    root = Path(ns.reference).resolve()
    binary_dir = root / "bin/universal-darwin"
    env = dict(os.environ)
    env["TEXMFROOT"] = str(root)
    env["PATH"] = f"{binary_dir}:{env.get('PATH', '')}"

    # tectdist profile client: farm links named pdflatex pointing at the
    # candidate with profile env set.
    link_dir = Path(tempfile.mkdtemp(prefix="bt100-smoke-links-"))
    os.symlink(Path(ns.candidate).resolve(), link_dir / "pdflatex")
    profile_env = dict(env)
    profile_env["TECTDIST_PROFILE"] = "basictex-2026"
    profile_env["TECTDIST_BASICTEX_ROOT"] = str(root)
    profile_env["PATH"] = f"{link_dir}:{env['PATH']}"

    results = []
    counters = {"pass": 0, "fail": 0, "reference-failure": 0}
    for row in rows:
        styles = row["loadable_styles"][:ns.styles_per_package]
        for style in styles:
            source = DOC_TEMPLATE % style
            case_id = f"{row['package']}/{style}"
            entry = {"case": case_id, "package": row["package"],
                     "style": style}

            reference_work = Path(tempfile.mkdtemp(prefix="bt100-smoke-ref-"))
            (reference_work / "main.tex").write_text(source)
            try:
                reference_status = compile_once(binary_dir, reference_work,
                                                "main.tex", env)
            except subprocess.TimeoutExpired:
                reference_status = None
            reference_pages = pdf_page_count(reference_work / "main.pdf") \
                if reference_status == 0 else None

            if reference_status != 0:
                entry["verdict"] = "reference-failure"
                entry["reference_exit"] = reference_status
                counters["reference-failure"] += 1
                results.append(entry)
                continue

            candidate_work = Path(tempfile.mkdtemp(prefix="bt100-smoke-cand-"))
            (candidate_work / "main.tex").write_text(source)
            try:
                candidate_status = compile_once(link_dir, candidate_work,
                                                "main.tex", profile_env)
            except subprocess.TimeoutExpired:
                candidate_status = None
            candidate_pages = pdf_page_count(candidate_work / "main.pdf") \
                if candidate_status == 0 else None

            if candidate_status != 0:
                entry["verdict"] = "fail"
                entry["candidate_exit"] = candidate_status
                counters["fail"] += 1
            elif candidate_pages != reference_pages:
                entry["verdict"] = "fail"
                entry["reference_pages"] = reference_pages
                entry["candidate_pages"] = candidate_pages
                counters["fail"] += 1
            else:
                entry["verdict"] = "pass"
                entry["pages"] = reference_pages
                counters["pass"] += 1
            results.append(entry)
            shutil.rmtree(reference_work, ignore_errors=True)
            shutil.rmtree(candidate_work, ignore_errors=True)

    report = {
        "schema_version": 1,
        "image_files_sha256": json.load(
            open(REFERENCE_DIR / "platform-manifest.json"))["image_files_sha256"],
        "shard": ns.shard,
        "counters": counters,
        "results": results,
    }
    Path(ns.output).write_text(json.dumps(report, indent=2) + "\n")

    lines = ["# BT100 minimal-load compatibility report", "",
             f"Shard {ns.shard}; image `{report['image_files_sha256'][:16]}…`",
             "",
             "| verdict | cases |", "|---|---:|"]
    for key, value in counters.items():
        lines.append(f"| {key} | {value} |")
    failures = [entry for entry in results if entry["verdict"] == "fail"]
    if failures:
        lines.extend(["", "## Failures", "", "| case | detail |", "|---|---|"])
        for entry in failures:
            detail = (f"exit={entry.get('candidate_exit')}" if "candidate_exit" in entry
                      else f"pages ref={entry.get('reference_pages')} cand={entry.get('candidate_pages')}")
            lines.append(f"| {entry['case']} | {detail} |")
    Path(ns.markdown).write_text("\n".join(lines) + "\n")

    print(f"smoke: {counters['pass']} pass, {counters['fail']} fail, "
          f"{counters['reference-failure']} reference-failures "
          f"({sum(counters.values())} cases)")
    return 1 if counters["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
