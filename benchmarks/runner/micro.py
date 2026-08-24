"""Small-command benchmark runner for startup and dispatch budgets."""
import argparse
import json
import os
from pathlib import Path
import statistics
import subprocess
import tempfile
import time

from .results import utc_now
from .system_info import collect


def percentile(values, fraction):
    values = sorted(values)
    return values[min(len(values) - 1, round((len(values) - 1) * fraction))]


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--command", required=True, nargs=argparse.REMAINDER,
                        help="command and arguments to measure; place this last")
    parser.add_argument("--trials", type=int, default=30)
    parser.add_argument("--warmups", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    ns = parser.parse_args(argv)
    if not ns.command:
        raise SystemExit("--command requires an executable")
    if ns.trials < 1 or ns.warmups < 0:
        raise SystemExit("trials must be positive and warmups must be non-negative")
    samples = []
    for number in range(ns.warmups + ns.trials):
        started = time.perf_counter_ns()
        result = subprocess.run(ns.command, capture_output=True, text=True)
        elapsed = (time.perf_counter_ns() - started) / 1_000_000
        if result.returncode:
            raise SystemExit("microbenchmark command failed: " + result.stderr.strip())
        if number >= ns.warmups:
            samples.append(elapsed)
    payload = {
        "schema_version": 1,
        "kind": "microbenchmark",
        "timestamp_utc": utc_now(),
        "platform": collect(),
        "command": ns.command,
        "samples_ms": samples,
        "summary": {"count": len(samples), "p50_ms": statistics.median(samples),
                    "p95_ms": percentile(samples, .95)},
    }
    directory = ns.output.parent
    directory.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".tectdist-micro-", dir=directory)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temporary, ns.output)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


if __name__ == "__main__":
    main()
