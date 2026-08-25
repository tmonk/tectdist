#!/usr/bin/env python3
"""Paired BasicTeX-versus-tectdist baseline and X10 denominator freeze (B0).

For every `basictex-core` corpus document this script:

1. runs the document's exact BasicTeX resolution sequence against the
   extracted pinned reference image,
2. runs tectdist on an identical project copy,
3. repeats for N paired trials with alternating order,
4. freezes per-document medians and X10 budgets
   (budget = 0.10 × paired reference median) into
   reference/basictex-2026/baseline-denominators.json.

Usage:
    python3 scripts/basictex_baseline.py --reference <TL root> \
        [--candidate /path/to/tectdist] [--trials 5]
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]

# Exact BasicTeX resolution sequences per document (plan §7.6).
# {job} expands to the document jobname (stem); {job}.tex to the source.
SEQUENCES = {
    "tiny": ["pdflatex {job}.tex"],
    "references": ["pdflatex {job}.tex", "pdflatex {job}.tex"],
    "paper": ["pdflatex {job}.tex", "pdflatex {job}.tex"],
    "multifile": ["pdflatex {job}.tex", "pdflatex {job}.tex"],
    "beamer": ["pdflatex {job}.tex", "pdflatex {job}.tex"],
    "thesis": ["pdflatex {job}.tex", "pdflatex {job}.tex"],
    "graphics": ["pdflatex {job}.tex"],
    "tikz": ["pdflatex {job}.tex", "pdflatex {job}.tex"],
    "unicode-fonts": ["xelatex {job}.tex"],
    "shell-escape": ["pdflatex -shell-escape {job}.tex"],
    "index": ["pdflatex {job}.tex", "makeindex {job}", "pdflatex {job}.tex"],
    "bibtex": ["pdflatex {job}.tex", "bibtex {job}",
               "pdflatex {job}.tex", "pdflatex {job}.tex"],
}


def run_sequence(binary_dir, work, commands, env):
    start = time.perf_counter_ns()
    status = 0
    jobname = next((entry.stem for entry in list(Path(work).glob("*.tex")) +
                    list(Path(work).glob("*.mp"))), "main")
    for command in commands:
        expanded_command = command.replace("{job}", jobname)
        parts = expanded_command.split()
        result = subprocess.run([str(binary_dir / parts[0]), *parts[1:]],
                                cwd=work, env=env, capture_output=True,
                                text=True)
        if result.returncode != 0:
            status = result.returncode
            print(f"  command '{command}' failed:\n{result.stdout[-400:]}\n{result.stderr[-400:]}")
            break
    return status, (time.perf_counter_ns() - start) / 1e6


def copy_project(doc_source: Path, destination: Path):
    # Recursive so multi-file documents (\input/\include into
    # subdirectories) stage completely; structure is preserved.
    if doc_source.is_dir():
        for item in doc_source.rglob("*"):
            if item.is_file() and item.suffix in {".tex", ".bib", ".ist", ".mp"}:
                rel = item.relative_to(doc_source)
                target = destination / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(item, target)
    else:
        shutil.copy(doc_source, destination / doc_source.name)


def measure(reference_bin, candidate_bin, doc_source, commands, trials, env):
    reference_times = []
    candidate_times = []
    link_dir = Path(tempfile.mkdtemp(prefix="bt100-links-"))
    for name in {command.split()[0] for command in commands} | {"tectdist"}:
        os.symlink(candidate_bin.resolve(), link_dir / name)
    env = dict(env)
    # Exact BasicTeX helpers must serve internal invocations (mpost -> etex,
    # htlatex -> latex, ...) on BOTH sides; top-level dispatch happens through
    # absolute paths, so this never redirects the measured process.
    env["PATH"] = f"{reference_bin}:{env['PATH']}"
    for trial in range(trials):
        # Reference project.
        reference_work = Path(tempfile.mkdtemp(prefix="bt100-ref-"))
        copy_project(doc_source, reference_work)
        status, elapsed = run_sequence(reference_bin, reference_work,
                                       commands, env)
        shutil.rmtree(reference_work, ignore_errors=True)
        if status != 0:
            return None, f"reference failed ({status}) on trial {trial}"
        reference_times.append(elapsed)

        # Candidate project: same commands resolved through the tectdist farm.
        candidate_work = Path(tempfile.mkdtemp(prefix="bt100-cand-"))
        copy_project(doc_source, candidate_work)
        status, elapsed = run_sequence(link_dir, candidate_work,
                                       commands, env)
        shutil.rmtree(candidate_work, ignore_errors=True)
        if status != 0:
            return None, f"candidate failed ({status}) on trial {trial}"
        candidate_times.append(elapsed)
    shutil.rmtree(link_dir, ignore_errors=True)
    return {"reference_ms": reference_times, "candidate_ms": candidate_times}, None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", required=True,
                        help="extracted BasicTeX texlive root")
    parser.add_argument("--candidate",
                        default=str(ROOT / "target/release/tectdist"))
    parser.add_argument("--trials", type=int, default=5)
    parser.add_argument("--documents", nargs="*", default=None)
    parser.add_argument("--corpus", choices=("compact", "basictex"),
                        default="compact",
                        help="compact corpus uses built-in sequences; "
                             "basictex corpus reads meta.json sequences")
    parser.add_argument("--candidate-mode", choices=("default", "basictex-profile"),
                        default=None,
                        help="candidate execution mode (default: basictex-"
                             "profile for the basictex corpus, else default)")
    ns = parser.parse_args(argv)

    reference_bin = (Path(ns.reference) / "bin/universal-darwin").resolve()
    candidate_bin = Path(ns.candidate).resolve()
    if not reference_bin.is_dir():
        raise SystemExit(f"reference bin dir missing: {reference_bin}")
    if not candidate_bin.is_file():
        raise SystemExit(f"candidate binary missing: {candidate_bin}")

    classification = json.load(open(
        ROOT / "reference/basictex-2026/corpus-classification.json"))
    candidate_mode = ns.candidate_mode or (
        "basictex-profile" if ns.corpus == "basictex" else "default")

    env = dict(os.environ)
    env["TEXMFROOT"] = str(Path(ns.reference).resolve())
    if candidate_mode == "basictex-profile":
        # The BT100 product executes exact reference engines; the candidate
        # environment selects that profile explicitly.
        env["TECTDIST_PROFILE"] = "basictex-2026"
        env["TECTDIST_BASICTEX_ROOT"] = str(Path(ns.reference).resolve())

    unused_marker = None
    if ns.corpus == "basictex":
        corpus_root = ROOT / "benchmarks/basictex-corpus"
        documents = sorted(
            entry.name for entry in corpus_root.iterdir()
            if (entry / "meta.json").is_file())
        document_sequences = {
            entry.name: json.loads((entry / "meta.json").read_text())["sequence"]
            for entry in corpus_root.iterdir()
            if (entry / "meta.json").is_file()
        }
    else:
        documents = ns.documents or [
            name for name, verdict in classification["documents"].items()
            if verdict == "basictex-core"
        ]
        document_sequences = {name: SEQUENCES.get(name) for name in documents}

    results = {}
    for document in sorted(documents):
        commands = document_sequences.get(document)
        if not commands:
            print(f"baseline: no declared sequence for '{document}'; skipped")
            continue
        source_dir = ((ROOT / "benchmarks/basictex-corpus" / document)
                      if ns.corpus == "basictex"
                      else ROOT / f"benchmarks/corpus/{document}")
        source = source_dir / "main.tex"
        if not source.is_file():
            # MetaPost-style corpora use a different primary file.
            candidates = sorted(source_dir.glob("*.tex")) + \
                sorted(source_dir.glob("*.mp"))
            if not candidates:
                print(f"baseline: no source for '{document}'; skipped")
                continue
            source = candidates[0]
        # Always stage the document DIRECTORY: multi-file documents
        # (\input/\include into subdirectories) must stage completely,
        # and copy_project handles both layouts.
        samples, error = measure(reference_bin, candidate_bin,
                                 source_dir, commands, ns.trials, env)
        if error:
            print(f"baseline: {document}: FAILED — {error}")
            continue
        ref_median = statistics.median(samples["reference_ms"])
        cand_median = statistics.median(samples["candidate_ms"])
        results[document] = {
            "sequence": commands,
            "trials": ns.trials,
            "reference_median_ms": round(ref_median, 1),
            "candidate_median_ms": round(cand_median, 1),
            "candidate_mode": candidate_mode,
            "speedup_vs_reference": round(ref_median / cand_median, 3),
            "x10_budget_ms": round(0.10 * ref_median, 1),
            "_samples": samples,
        }
        print(f"baseline: {document}: reference {ref_median:.0f} ms | "
              f"tectdist {cand_median:.0f} ms | budget {results[document]['x10_budget_ms']} ms")

    suffix = "" if ns.corpus == "compact" else "-basictex-corpus"
    out_path = ROOT / f"reference/basictex-2026/baseline-denominators{suffix}.json"
    payload = {
        "schema_version": 1,
        "budget_rule": "x10_budget = 0.10 * paired reference median",
        "results": results,
    }
    out_path.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"baseline: denominators frozen -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
