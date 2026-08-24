#!/usr/bin/env python3
"""Formal X3 action-broker gate measurement (plan §10.6).

Boots a private supervisor instance and measures, per core helper:

  - cold miss duration (exact execution through the pinned image),
  - warm hit p50/min for the restored result,
  - invalidation correctness after an input mutation.

Gates (§10.6): unchanged-action restore < 2 ms p50, 100% output equivalence.

Usage:
    python3 scripts/basictex_actions_bench.py \
        --reference <TL root> --candidate-supervisor <path> [--trials 20]
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


class SupervisorHandle:
    def __init__(self, exe, image_root):
        self.dir = Path(tempfile.mkdtemp(prefix="bt100-actions-"))
        self.socket = self.dir / "s.sock"
        env = dict(os.environ)
        env["TECTDIST_SUPERVISOR_SOCKET"] = str(self.socket)
        env["TECTDIST_BASICTEX_ROOT"] = str(image_root)
        env["TECTDIST_ACTION_CACHE"] = str(self.dir / "cache")
        env["PATH"] = f"{Path(image_root) / 'bin/universal-darwin'}:{env.get('PATH', '')}"
        self.child = subprocess.Popen(
            [exe, "serve"], env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                socket.socket(socket.AF_UNIX).connect(str(self.socket))
                return
            except (ConnectionRefusedError, FileNotFoundError):
                time.sleep(0.02)
        raise RuntimeError("supervisor did not start")

    def request(self, payload: dict) -> dict:
        s = socket.socket(socket.AF_UNIX)
        s.connect(str(self.socket))
        s.sendall(json.dumps(payload).encode() + b"\n")
        s.settimeout(120)
        data = s.recv(65536)
        s.close()
        return json.loads(data)

    def stop(self):
        try:
            self.request({"type": "shutdown"})
        except Exception:
            pass
        try:
            self.child.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.child.kill()
            self.child.wait(timeout=2)
        shutil.rmtree(self.dir, ignore_errors=True)


def timed_request(handle, payload, repeats):
    times = []
    last = None
    for _ in range(repeats):
        t0 = time.perf_counter()
        response = handle.request(payload)
        times.append((time.perf_counter() - t0) * 1000)
        last = response
    return times, last


def measure_tool(handle, name, setup, argv, inputs, outputs, mutate=None,
                 trials=20, binary_dir=None, env=None):
    work = Path(tempfile.mkdtemp(prefix=f"bt100-act-{name}-"))
    if setup:
        setup(work, binary_dir, env)
    base_payload = {
        "type": "action", "tool": name, "cwd": str(work),
        "argv": argv, "inputs": [str(p) for p in inputs],
        "outputs": [str(p) for p in outputs],
    }
    # Cold miss.
    first = handle.request(base_payload)
    if not first.get("ok"):
        return {"pipeline": name, "verdict": "fail",
                "error": first.get("error")}
    miss_ms = first["action_result"]["duration_ms"]
    # Warm hits.
    times, _ = timed_request(handle, base_payload, trials)
    hit_p50 = statistics.median(times)
    # Invalidation.
    invalidated_ok = True
    if mutate:
        mutate(work, binary_dir, env)
        response = handle.request(base_payload)
        invalidated_ok = (
            response.get("ok")
            and response["action_result"]["cache_hit"] is False
            and response["action_result"]["exit_status"] == 0)
    shutil.rmtree(work, ignore_errors=True)
    return {
        "helper": name,
        "cold_miss_ms": round(miss_ms, 1),
        "hit_p50_ms": round(hit_p50, 2),
        "hit_min_ms": round(min(times), 2),
        "invalidation_ok": invalidated_ok,
        "gate_2ms_restore": hit_p50 < 2.0,
        "verdict": "pass" if (hit_p50 < 2.0 and invalidated_ok) else "fail",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", required=True)
    parser.add_argument("--supervisor",
                        default=str(ROOT / "target/debug/tectdist-supervisor"))
    parser.add_argument("--trials", type=int, default=20)
    parser.add_argument("--output",
                        default=str(ROOT / "reference/basictex-2026/"
                                    "action-benchmarks.json"))
    ns = parser.parse_args(argv)

    image_root = Path(ns.reference).resolve()
    handle = SupervisorHandle(ns.supervisor, image_root)
    results = []

    def write_file(work, name, content):
        path = work / name
        path.write_text(content)
        return path

    # --- BibTeX ---
    def bib_setup(work, binary_dir=None, env=None):
        write_file(work, "refs.bib",
                   "@book{k1, author={Alpha}, title={T}, publisher={P}, year={2001}}\n")
        write_file(work, "main.aux",
                   "\\relax\n\\citation{k1}\n\\bibstyle{plain}\n"
                   "\\bibdata{refs}\n\\bibcite{k1}{1}\n")

    def bib_mutate(work, binary_dir=None, env=None):
        write_file(work, "refs.bib",
                   "@book{k1, author={Beta}, title={T}, publisher={P}, year={2001}}\n")

    binary_dir = image_root / "bin/universal-darwin"
    tool_env = dict(os.environ)
    tool_env["TEXMFROOT"] = str(image_root)
    results.append(measure_tool(
        handle, "bibtex", bib_setup,
        ["bibtex", "main"], [Path("main.aux"), Path("refs.bib")],
        [Path("main.bbl"), Path("main.blg")], mutate=bib_mutate,
        trials=ns.trials))

    # --- MakeIndex ---
    def idx_setup(work, binary_dir=None, env=None):
        write_file(work, "main.idx", "\\indexentry{alpha}{1}\n\\indexentry{beta}{2}\n")

    def idx_mutate(work, binary_dir=None, env=None):
        write_file(work, "main.idx", "\\indexentry{gamma}{3}\n")

    results.append(measure_tool(
        handle, "makeindex", idx_setup,
        ["makeindex", "main"], [Path("main.idx")],
        [Path("main.ind"), Path("main.ilg")], mutate=idx_mutate,
        trials=ns.trials))

    # --- MetaPost ---
    def mp_setup(work, binary_dir=None, env=None):
        write_file(work, "fig.mp",
                   "beginfig(1)\ndraw (0,0)--(10mm,0);\nendfig;\nend.\n")

    def mp_mutate(work, binary_dir=None, env=None):
        write_file(work, "fig.mp",
                   "beginfig(1)\ndraw (0,0)--(20mm,0);\nendfig;\nend.\n")

    results.append(measure_tool(
        handle, "mpost", mp_setup,
        ["mpost", "-interaction=batchmode", "fig.mp"], [Path("fig.mp")],
        [Path("fig.1"), Path("fig.log")], mutate=mp_mutate,
        trials=ns.trials))

    # --- dvips (setup produces the DVI through the reference latex) ---
    def dvips_setup(work, binary_dir, env):
        write_file(work, "main.tex",
                   "\\documentclass{article}\\begin{document}"
                   "DVI pipeline.\\end{document}\n")
        result = subprocess.run(
            [str(binary_dir / "latex"), "-interaction=batchmode", "main.tex"],
            cwd=work, env=env, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr[-300:]

    def dvips_mutate(work, binary_dir, env):
        write_file(work, "main.tex",
                   "\\documentclass{article}\\begin{document}"
                   "DVI pipeline v2.\\end{document}\n")
        subprocess.run(
            [str(binary_dir / "latex"), "-interaction=batchmode", "main.tex"],
            cwd=work, env=env, capture_output=True, text=True)

    if (binary_dir / "dvips").exists():
        results.append(measure_tool(
            handle, "dvips", dvips_setup,
            ["dvips", "main.dvi"], [Path("main.dvi")],
            [Path("main.ps")], mutate=dvips_mutate,
            trials=min(ns.trials, 10), binary_dir=binary_dir, env=tool_env))

    # --- tex4ht (HTML asset set) ---
    if (binary_dir / "htlatex").exists():
        def tex4ht_setup(work, binary_dir, env):
            write_file(work, "main.tex",
                       "\\documentclass{article}\\begin{document}"
                       "HTML pipeline.\\end{document}\n")

        def tex4ht_mutate(work, binary_dir, env):
            write_file(work, "main.tex",
                       "\\documentclass{article}\\begin{document}"
                       "HTML pipeline v2.\\end{document}\n")

        results.append(measure_tool(
            handle, "htlatex", tex4ht_setup,
            ["htlatex", "main.tex"], [Path("main.tex")],
            [Path("main.html"), Path("main.css")], mutate=tex4ht_mutate,
            trials=min(ns.trials, 5), binary_dir=binary_dir, env=tool_env))

    handle.stop()

    passed = sum(1 for entry in results if entry.get("verdict") == "pass")
    payload = {"schema_version": 1, "gate": "restore < 2 ms p50",
               "trials_per_hit": ns.trials, "results": results,
               "passed": passed, "total": len(results)}
    Path(ns.output).write_text(json.dumps(payload, indent=2) + "\n")
    for entry in results:
        print("%-12s %s | hit p50 %.2f ms | miss %.1f ms | "
              "invalidation %s" % (
                  entry.get("helper", entry.get("pipeline")),
                  entry.get("verdict"), entry.get("hit_p50_ms", -1),
                  entry.get("cold_miss_ms", -1),
                  entry.get("invalidation_ok")))
    print(f"actions: {passed}/{len(results)} helpers meet the 2 ms gate")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
