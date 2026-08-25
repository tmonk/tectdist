#!/usr/bin/env python3
"""X10-E edit-scenario measurements through the supervisor (plan X2/X10).

Drives a live supervisor over its Unix socket and times four scenarios
against the same document:

  1. cold-first      first compile (format build + body compile)
  2. warm-body-edit  preamble unchanged, body edited -> format reused
  3. preamble-edit   preamble edited -> format rebuilt, body compiled
  4. stock-baseline  same document compiled one-shot without supervisor

Writes reference/basictex-2026/x2-edit-scenarios.json (+ .md).

Requires: built supervisor binary, BasicTeX image on this host.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REF = ROOT / "reference" / "basictex-2026"
IMAGE = REF / "image"

DOC_PREAMBLE = """\\documentclass{article}
\\usepackage{amsmath}
\\usepackage{hyperref}
"""
DOC_BODY = """\\begin{document}
\\title{Edit Scenario Probe}\\maketitle
BODY_SENTENCE
Some math: $e^{i\\pi}+1=0$.
\\end{document}
"""


class Supervisor:
    def __init__(self, tag):
        self.dir = Path(tempfile.mkdtemp(prefix=f"x2-{tag}-"))
        self.socket = self.dir / "s.sock"
        exe = ROOT / "target/release/tectdist-supervisor"
        env = dict(os.environ)
        env["TECTDIST_SUPERVISOR_SOCKET"] = str(self.socket)
        env["TECTDIST_ACTION_CACHE"] = str(self.dir / "cache")
        env["TECTDIST_BASICTEX_ROOT"] = str(IMAGE)
        self.log = open(self.dir / "serve.log", "w")
        self.proc = subprocess.Popen(
            [str(exe), "serve"], env=env, stdout=self.log, stderr=self.log,
            start_new_session=True)
        deadline = time.time() + 5
        while time.time() < deadline:
            if self.socket.exists():
                try:
                    s = socket.socket(socket.AF_UNIX)
                    s.connect(str(self.socket))
                    s.close()
                    return
                except OSError:
                    pass
            time.sleep(0.02)
        raise RuntimeError("supervisor socket never appeared")

    def request(self, payload):
        s = socket.socket(socket.AF_UNIX)
        s.connect(str(self.socket))
        s.sendall(json.dumps(payload).encode() + b"\n")
        data = b""
        while not data.endswith(b"\n"):
            chunk = s.recv(65536)
            if not chunk:
                break
            data += chunk
        s.close()
        return json.loads(data)

    def stop(self):
        try:
            os.killpg(self.proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        self.proc.wait()
        self.log.close()
        shutil.rmtree(self.dir, ignore_errors=True)


def timed_compile(sup, work, argv):
    payload = {
        "type": "compile",
        "profile": "basictex-2026",
        "cwd": str(work),
        "argv": argv,
        "snapshot_key": None,
    }
    t0 = time.perf_counter()
    response = sup.request(payload)
    wall_ms = int((time.perf_counter() - t0) * 1000)
    exit_status = response.get("compile_accepted", {}).get("exit_status", -1)
    duration_ms = response.get("compile_accepted", {}).get("duration_ms", -1)
    return {"wall_ms": wall_ms, "engine_ms": duration_ms,
            "exit": exit_status, "ok": response.get("ok")}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--trials", type=int, default=3,
                    help="timed trials per scenario (min taken)")
    ap.add_argument("--out", type=Path, default=REF / "x2-edit-scenarios.json")
    args = ap.parse_args(argv)

    results = {}
    work = Path(tempfile.mkdtemp(prefix="x2-doc-"))

    # Stock baseline (no supervisor): direct pdftex one-shot.
    bin_dir = next(d for d in (IMAGE / "bin").iterdir() if d.is_dir())
    stock_env = dict(os.environ)
    stock_env["TEXMFROOT"] = str(IMAGE)
    stock_env["TEXFORMATS"] = (
        f".:{IMAGE}/texmf-var/web2c/pdftex:{IMAGE}/texmf-dist/web2c")
    stock_env["PATH"] = f"{bin_dir}:{os.environ['PATH']}"
    source = work / "main.tex"
    source.write_text(DOC_PREAMBLE + DOC_BODY.replace("BODY_SENTENCE", "v1."))
    timings = []
    for _ in range(args.trials):
        pdf = work / "main.pdf"
        pdf.unlink(missing_ok=True)
        t0 = time.perf_counter()
        proc = subprocess.run(
            [str(bin_dir / "pdftex"), "-interaction=batchmode",
             "&pdflatex", "main.tex"],
            cwd=work, env=stock_env, capture_output=True, timeout=120)
        timings.append(int((time.perf_counter() - t0) * 1000))
        assert proc.returncode == 0, "stock compile failed"
    results["stock-one-shot"] = min(timings)

    # Supervisor-driven scenarios.
    sup = Supervisor("meas")
    try:
        argv = ["pdflatex", "-interaction=batchmode", "main.tex"]

        def set_source(preamble_sentence, body_sentence):
            preamble = DOC_PREAMBLE + (
                "% variant\n" if preamble_sentence else "")
            source.write_text(
                preamble + DOC_BODY.replace("BODY_SENTENCE", body_sentence))

        # 1. cold first compile (includes format build).
        set_source(False, "v1.")
        (work / "main.pdf").unlink(missing_ok=True)
        best = None
        for trial in range(args.trials):
            shutil.rmtree(work / ".tectdist", ignore_errors=True)
            (work / "main.pdf").unlink(missing_ok=True)
            r = timed_compile(sup, work, argv)
            assert r["exit"] == 0, f"cold compile failed: {r}"
            best = r["wall_ms"] if best is None else min(best, r["wall_ms"])
        results["cold-first-with-format-build"] = best

        # 2. warm body edit: preamble untouched -> format reused.
        set_source(False, "v2 edited sentence.")
        (work / "main.pdf").unlink(missing_ok=True)
        best = None
        for _ in range(args.trials):
            (work / "main.pdf").unlink(missing_ok=True)
            r = timed_compile(sup, work, argv)
            assert r["exit"] == 0, f"body-edit compile failed: {r}"
            best = r["wall_ms"] if best is None else min(best, r["wall_ms"])
        results["warm-body-edit-format-reused"] = best

        # 3. preamble edit: format must rebuild on EVERY trial (alternate
        # between two distinct preambles so each trial invalidates).
        best = None
        for trial in range(args.trials):
            set_source(trial % 2 == 0, "v2 edited sentence.")
            (work / "main.pdf").unlink(missing_ok=True)
            r = timed_compile(sup, work, argv)
            assert r["exit"] == 0, f"preamble-edit compile failed: {r}"
            best = r["wall_ms"] if best is None else min(best, r["wall_ms"])
        results["preamble-edit-format-rebuilt"] = best
    finally:
        sup.stop()
        shutil.rmtree(work, ignore_errors=True)

    out = {
        "schema_version": 1,
        "trials_per_scenario": args.trials,
        "statistic": "min",
        "scenarios": results,
        "speedup_body_edit_vs_stock": round(
            results["stock-one-shot"]
            / max(results["warm-body-edit-format-reused"], 1), 3),
    }
    args.out.write_text(json.dumps(out, indent=2) + "\n")
    md = ["# X10-E edit scenarios through the supervisor (project format)", "",
          "| scenario | ms (min) |", "|---|---:|"]
    md += [f"| {k} | {v} |" for k, v in results.items()]
    md += ["", f"Body-edit speedup vs stock: {out['speedup_body_edit_vs_stock']}x"]
    args.out.with_suffix(".md").write_text("\n".join(md) + "\n")

    print(f"{results}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
