"""Paired, randomised benchmark CLI.

Smoke mode is intentionally quick. Qualification callers select --trials 30
and repeat independent sessions; the output schema records both settings.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import tempfile
import time
import uuid

from .competitors import describe, from_environment
from .correctness import validate
from .manifest import validate as validate_manifest
from .results import utc_now, validate as validate_result, write
from .scenarios import environment as scenario_environment, prepare
from .statistics import paired_summary
from .system_info import collect

ROOT = Path(__file__).resolve().parents[2]


def repository_provenance():
    """Capture the actual worktree identity without requiring Git in runners."""
    override = os.environ.get("GITHUB_SHA")
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                capture_output=True, text=True, check=True).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                                    capture_output=True, text=True, check=True).stdout.strip())
    except (OSError, subprocess.CalledProcessError):
        commit, dirty = "unknown", True
    return override or commit, dirty


def manifest(path):
    try:
        import tomllib
    except ImportError:  # benchmark runner may be invoked with Python 3.9
        raise SystemExit("benchmark runner requires Python 3.11+ for TOML manifests")
    with open(path, "rb") as stream:
        return tomllib.load(stream)


def command_for(name, command, main, document):
    """Use the compatible spelling required by each concrete competitor."""
    if name in ("direct-tectonic", "previous-tectdist"):
        arguments = ["--keep-intermediates", "--keep-logs"]
    elif name == "texlive-latexmk":
        mode = "-xelatex" if "fontspec" in document.get("requires", ()) else "-pdf"
        arguments = [mode, "-interaction=nonstopmode", "-halt-on-error"]
    else:
        arguments = []
    if document.get("requires_shell_escape"):
        arguments += ["-Z", "shell-escape"] if name == "direct-tectonic" else ["-shell-escape"]
    return list(command) + arguments + [main]


def competitor_applicable(name, document):
    """Exclude only workloads a control fundamentally cannot orchestrate."""
    if name == "direct-tectonic" and (
            document.get("requires_index") or document.get("requires_glossary")):
        return False
    return True


def absolute_command(command):
    """Resolve an explicit repository-relative executable before chdir()."""
    command = list(command)
    if command and not os.path.isabs(command[0]) and (
            os.sep in command[0] or (os.altsep and os.altsep in command[0])):
        command[0] = str((ROOT / command[0]).resolve())
    return command


def _read_trace(path):
    """Read best-effort opt-in JSONL spans without making tracing a dependency."""
    if not path.is_file():
        return []
    spans = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            spans.append(json.loads(line))
        except json.JSONDecodeError:
            spans.append({"span": "trace.invalid", "raw": line})
    return spans


def _process_count_from_trace(spans):
    """Infer a conservative count without polling and perturbing the timing."""
    spawned = sum(span.get("span") in ("engine.spawn", "indexer.run")
                  for span in spans)
    return 1 + spawned, "trace-estimate" if spans else "root-process-lower-bound"


def _stage_counts(spans):
    """Count explicit engine passes and external stages from stable spans."""
    names = [span.get("span") for span in spans]
    engine_passes = sum(name == "engine.pass" for name in names)
    if not engine_passes:
        # Python/external traces expose a run plus optional rerun rather than
        # driver pass events. Count only known engine spans, never processes.
        engine_passes = sum(name in ("engine.run", "engine.rerun_after_index")
                            for name in names)
    external_tools = sum(name in ("indexer.run", "bibliography.run", "biber.run")
                         for name in names)
    return engine_passes, external_tools


def _tree_size(path):
    if path is None or not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _resource_metrics(spans, environment, cache_growth=None):
    """Record cold-resource work without pretending an absent probe saw zero."""
    download_spans = [span for span in spans if span.get("span") in (
        "bundle.download", "package.download", "resource.download")]
    decompression_spans = [span for span in spans if span.get("span") in (
        "bundle.decompress", "package.decompress", "resource.decompress")]
    bytes_value = environment.get("TECTDIST_BYTES_DOWNLOADED")
    try:
        bytes_downloaded = int(bytes_value) if bytes_value is not None else None
    except ValueError:
        bytes_downloaded = None
    if bytes_downloaded is None and cache_growth is not None:
        bytes_downloaded = max(0, cache_growth)
    measurement = ("trace-and-explicit-counter" if spans or bytes_value is not None else
                   "cache-growth-estimate" if cache_growth is not None else "unavailable")
    return {
        "download_observed": bool(download_spans) or bool(bytes_downloaded),
        "bytes_downloaded": bytes_downloaded,
        "download_duration_ms": sum(span.get("duration_ns", 0)
                                    for span in download_spans) / 1_000_000,
        "decompression_duration_ms": sum(span.get("duration_ns", 0)
                                         for span in decompression_spans) / 1_000_000,
        "measurement": measurement,
    }


def supervisor_command():
    """Locate the native benchmark supervisor for per-child resource metrics.

    Explicit configuration wins (TECTDIST_BENCH_SUPERVISOR); otherwise a built
    workspace artifact is used when present. Without it the runner falls back
    to cumulative RUSAGE_CHILDREN deltas and labels the method accordingly.
    """
    configured = os.environ.get("TECTDIST_BENCH_SUPERVISOR")
    if configured:
        return configured if Path(configured).is_file() else None
    for profile in ("release", "debug"):
        path = ROOT / "target" / profile / "tectdist-bench"
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return None


def _base_payload(wall_ms, result, spans):
    process_count, process_count_method = _process_count_from_trace(spans)
    engine_passes, external_tools = _stage_counts(spans)
    return {"wall_time_ms": wall_ms,
            "exit_status": result.returncode if result is not None else None,
            "stdout": result.stdout if result is not None else "",
            "stderr": result.stderr if result is not None else "",
            "process_count": process_count,
            "process_count_method": process_count_method,
            "engine_pass_count": engine_passes,
            "external_tool_count": external_tools}


def _child_rusage_delta():
    try:
        import resource
        return resource.getrusage(resource.RUSAGE_CHILDREN)
    except ImportError:  # pragma: no cover - non-POSIX runner
        return None


def sample(command, cwd, environment=None):
    """One untraced timed build.

    The timed path never sets ``TECTDIST_TRACE_FILE``: candidate-only trace
    writes must not appear inside product wall time (plan X0.1). Cache-tree
    sizing also happens strictly outside the measured interval. When the
    native supervisor is available, per-child CPU and peak RSS come from
    wait4 around child execution only instead of cumulative RUSAGE_CHILDREN.
    """
    environment = dict(os.environ if environment is None else environment)
    environment.pop("TECTDIST_TRACE_FILE", None)
    cache_value = environment.get("TECTONIC_CACHE_DIR") or environment.get("XDG_CACHE_HOME")
    cache_root = Path(cache_value) if cache_value else None
    cache_before = _tree_size(cache_root)  # outside the timed interval

    supervisor = supervisor_command()
    metrics_path = None
    before = _child_rusage_delta()
    start = time.perf_counter_ns()
    if supervisor:
        handle, metrics_path = tempfile.mkstemp(prefix="tectdist-metrics-", suffix=".json")
        os.close(handle)
        wrapped = [supervisor, "--output", metrics_path, "--"] + list(command)
        result = subprocess.run(wrapped, cwd=cwd, capture_output=True, text=True,
                                errors="replace", env=environment)
    else:
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True,
                                errors="replace", env=environment)
    wall_ms = (time.perf_counter_ns() - start) / 1_000_000
    cache_growth = _tree_size(cache_root) - cache_before if cache_root else None  # untimed
    after = _child_rusage_delta()

    payload = _base_payload(wall_ms, result, [])
    payload["measurement_class"] = "untraced-timed"
    payload["trace_spans"] = []
    payload["resources"] = _resource_metrics([], environment, cache_growth)
    metrics = None
    if metrics_path is not None:
        try:
            metrics = json.loads(Path(metrics_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            metrics = None
        finally:
            Path(metrics_path).unlink(missing_ok=True)
    if metrics and "error" not in metrics:
        payload["wall_time_ms"] = metrics["wall_time_ms"]
        payload["user_cpu_ms"] = metrics.get("user_cpu_ms")
        payload["system_cpu_ms"] = metrics.get("system_cpu_ms")
        payload["peak_rss"] = metrics.get("peak_rss")
        payload["peak_rss_unit"] = metrics.get("peak_rss_unit")
        payload["resource_method"] = metrics.get("resource_method", "wait4-direct-child")
    elif before is not None and after is not None:
        # Fallback: cumulative children delta. Peak RSS is a running maximum
        # across every child this runner has ever waited on, never a clean
        # per-build figure.
        payload["user_cpu_ms"] = (after.ru_utime - before.ru_utime) * 1000
        payload["system_cpu_ms"] = (after.ru_stime - before.ru_stime) * 1000
        payload["peak_rss"] = after.ru_maxrss
        payload["peak_rss_unit"] = "bytes" if os.uname().sysname == "Darwin" else "KiB"
        payload["resource_method"] = "rusage-children-cumulative"
    return payload


def traced_diagnostic_sample(command, cwd, environment=None):
    """One untimed traced repetition on a separate identical project copy.

    Stage data comes from here only; these records are excluded from paired
    statistics and must never support a product-speed claim (plan X0.1).
    """
    environment = dict(os.environ if environment is None else environment)
    trace_file = Path(cwd) / ".tectdist-trace.jsonl"
    environment["TECTDIST_TRACE_FILE"] = str(trace_file)
    start = time.perf_counter_ns()
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True,
                            errors="replace", env=environment)
    wall_ms = (time.perf_counter_ns() - start) / 1_000_000
    spans = _read_trace(trace_file)
    payload = _base_payload(wall_ms, result, spans)
    payload["measurement_class"] = "traced-diagnostic"
    payload["excluded_from_claims"] = True
    payload["trace_spans"] = spans
    payload["resources"] = _resource_metrics(spans, environment)
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default=str(ROOT / "benchmarks/corpus/manifest.toml"))
    parser.add_argument("--candidate", required=True, nargs="+", help="candidate command")
    parser.add_argument("--document", action="append")
    parser.add_argument("--scenario", default="warm-clean")
    parser.add_argument("--cold-source", choices=("controlled-local", "public-network", "not-applicable"),
                        default="not-applicable",
                        help="declare cache/package source for cold-empty-cache results")
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--qualification", action="store_true",
                        help="enforce release-grade trial and provenance inputs")
    parser.add_argument("--expensive-case", action="store_true",
                        help="use the plan's 15-pair threshold for book-scale workloads")
    parser.add_argument("--pair-seed", type=int, default=0,
                        help="seed for randomising the sequence of balanced AB/BA pairs")
    parser.add_argument("--diagnose", action="store_true",
                        help="add untimed traced diagnostic repetitions for the candidate")
    parser.add_argument("--output", required=True)
    ns = parser.parse_args(argv)
    if ns.qualification:
        minimum_trials = 15 if ns.expensive_case else 30
        minimum_warmups = 1 if ns.expensive_case else 5
        if ns.trials < minimum_trials or ns.warmups < minimum_warmups:
            raise SystemExit("qualification mode requires at least %d warmups and %d paired trials" %
                             (minimum_warmups, minimum_trials))
        missing = [name for name in ("TECTDIST_BUNDLE_SOURCE", "TECTDIST_BUNDLE_ID",
                                     "TECTDIST_BUNDLE_MANIFEST_SHA256",
                                     "TECTDIST_FORMAT_CACHE_ID",
                                     "TECTDIST_TEXLIVE_SOURCE", "TECTDIST_TEXLIVE_ID",
                                     "TECTDIST_TEXLIVE_MANIFEST_SHA256",
                                     "TECTDIST_TEXLIVE_FORMAT_ID")
                   if not os.environ.get(name)]
        if missing:
            raise SystemExit("qualification mode requires " + ", ".join(missing))
    if ns.scenario == "cold-empty-cache" and ns.cold_source == "not-applicable":
        raise SystemExit("cold-empty-cache results require --cold-source controlled-local or public-network")
    data = manifest(ns.manifest)
    errors = validate_manifest(data, ROOT / "benchmarks")
    if errors:
        raise SystemExit("invalid benchmark manifest:\n- " + "\n- ".join(errors))
    docs = [d for d in data.get("document", []) if not ns.document or d["id"] in ns.document]
    competitors = from_environment(absolute_command(ns.candidate))
    competitors = {name: absolute_command(command)
                   for name, command in competitors.items()}
    if len(competitors) < 2:
        raise SystemExit("configure at least one competitor with TECTDIST_BENCH_*")
    if ns.qualification:
        # Product-speed claims compare independent complete implementations.
        # Engine-only and previous-tectdist controls remain available for
        # diagnostics, but are not substitutes for a TeX Live control.
        required = {"texlive-latexmk"}
        missing = sorted(required.difference(competitors))
        if missing:
            raise SystemExit("qualification mode requires competitors: " + ", ".join(missing))
    repository_commit, dirty = repository_provenance()
    if ns.qualification and (repository_commit == "unknown" or dirty):
        raise SystemExit("qualification mode requires a clean, identified repository revision")
    output = {"schema_version": 1, "repository_commit": repository_commit,
              "dirty": dirty, "runner_commit": repository_commit, "qualification": ns.qualification,
              "trial_class": "expensive" if ns.expensive_case else "ordinary",
              "balance_seed": ns.pair_seed, "session_id": str(uuid.uuid4()),
              "timestamp_utc": utc_now(), "platform": collect(), "runs": []}
    pair_rng = random.Random(ns.pair_seed)
    if not supervisor_command():
        print("tectdist-bench: native supervisor not found; using cumulative "
              "RUSAGE_CHILDREN fallback (build target/release/tectdist-bench)")
    for document in docs:
        if ns.scenario not in document.get("scenarios", []):
            continue
        source = ROOT / "benchmarks" / document["path"]
        for competitor_name, competitor_command in competitors.items():
            if competitor_name == "candidate":
                continue
            if not competitor_applicable(competitor_name, document):
                continue
            # Balanced AB/BA stratification (plan X0.4): each tool runs first
            # in exactly half the timed trials; the extra orientation for odd
            # trial counts is chosen at random; the sequence of balanced pairs
            # is then shuffled with a recorded seed.
            half = ns.trials // 2
            extra = (["candidate", competitor_name] if pair_rng.random() < 0.5
                     else [competitor_name, "candidate"])
            orders = ([["candidate", competitor_name]] * half +
                      [[competitor_name, "candidate"]] * half)
            if ns.trials % 2:
                orders.append(extra)
            pair_rng.shuffle(orders)
            samples = []
            diagnostics = []
            for ignored in range(ns.warmups + ns.trials):
                order = (orders[(ignored - ns.warmups) % len(orders)]
                         if ignored >= ns.warmups else orders[ignored % len(orders)])
                results = {}
                with tempfile.TemporaryDirectory(prefix="tectdist-bench-") as temporary:
                    for name in order:
                        work = Path(temporary) / name
                        prepare(source, work, ns.scenario, document["main"])
                        command = command_for(name, competitors[name], document["main"], document)
                        run_environment = scenario_environment(work, ns.scenario)
                        if ns.scenario == "warm-existing-output":
                            # Establish ordinary project intermediates outside
                            # the timed sample, then retain them for the run.
                            seeded = sample(command, work, run_environment)
                            if seeded["exit_status"] != 0:
                                raise SystemExit("warm-existing-output setup failed for %s/%s" %
                                                 (document["id"], name))
                        run = sample(command, work, run_environment)
                        pdf = work / (Path(document["main"]).stem + ".pdf")
                        run["correctness"] = validate(str(pdf), document.get("expected_pages"),
                                                       document.get("expected_text", ()),
                                                       run["stdout"] + run["stderr"],
                                                       document.get("forbid_log_patterns", ()),
                                                       document.get("requires_bibliography", False),
                                                       document.get("requires_index", False),
                                                       document.get("requires_glossary", False),
                                                       document.get("requires_shell_escape", False))
                        if pdf.is_file():
                            run["output_sha256"] = hashlib.sha256(pdf.read_bytes()).hexdigest()
                        if run["exit_status"] != 0 or not run["correctness"]["ok"]:
                            raise SystemExit("correctness failure for %s/%s: %s" %
                                             (document["id"], name,
                                              "; ".join(run["correctness"]["errors"])))
                        results[name] = run
                    if ns.diagnose and ignored >= ns.warmups:
                        # Untimed traced repetition on a separate identical
                        # project copy; excluded from paired statistics.
                        traced_work = Path(temporary) / "candidate-traced"
                        prepare(source, traced_work, ns.scenario, document["main"])
                        traced_command = command_for("candidate", competitors["candidate"],
                                                     document["main"], document)
                        diagnostic = traced_diagnostic_sample(
                            traced_command, traced_work,
                            scenario_environment(traced_work, ns.scenario))
                        if diagnostic["exit_status"] != 0:
                            raise SystemExit("traced diagnostic failed for %s" % document["id"])
                        diagnostics.append({"order": order,
                                            "tools": {"candidate": diagnostic}})
                if ignored >= ns.warmups:
                    samples.append({"order": order, "tools": results})
            differences = [s["tools"]["candidate"]["wall_time_ms"] - s["tools"][competitor_name]["wall_time_ms"] for s in samples]
            output["runs"].append({"tool": {"candidate": describe("candidate", ns.candidate),
                                             "competitor": describe(competitor_name, competitor_command)},
                                   "document": document["id"],
                                   "claim": bool(document.get("claim")),
                                   "scenario": ns.scenario, "cold_source": ns.cold_source,
                                   "balance_seed": ns.pair_seed,
                                   "samples": samples, "summary": paired_summary(differences)})
            if diagnostics:
                output["runs"][-1]["traced_diagnostics"] = diagnostics
    result_errors = validate_result(output)
    if result_errors:
        raise SystemExit("invalid benchmark result:\n- " + "\n- ".join(result_errors))
    write(ns.output, output)


if __name__ == "__main__":
    main()
