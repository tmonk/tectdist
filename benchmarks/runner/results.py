"""Result bundle construction and atomic JSON writing."""
import json
import os
import tempfile
from datetime import datetime, timezone


def validate(payload):
    """Return human-readable errors for the runner's versioned result shape."""
    errors = []
    for field in ("schema_version", "session_id", "timestamp_utc", "platform", "runs"):
        if field not in payload:
            errors.append("missing top-level field: " + field)
    if payload.get("schema_version") != 1:
        errors.append("unsupported schema_version")
    if "qualification" in payload and not isinstance(payload["qualification"], bool):
        errors.append("qualification must be a boolean")
    for run in payload.get("runs", []):
        for field in ("tool", "document", "scenario", "samples", "summary"):
            if field not in run:
                errors.append("run missing field: " + field)
        if run.get("scenario") == "cold-empty-cache" and run.get("cold_source") not in (
                "controlled-local", "public-network"):
            errors.append("cold-empty-cache run requires declared cold_source")
        for pair in run.get("samples", []):
            if len(pair.get("order", [])) != 2:
                errors.append("paired sample must record two-item order")
            tools = pair.get("tools", {})
            if len(tools) < 2:
                errors.append("paired sample must record two tools")
            for sample in tools.values():
                for field in ("wall_time_ms", "exit_status", "process_count",
                              "process_count_method", "engine_pass_count",
                              "external_tool_count", "correctness", "trace_spans",
                              "resources"):
                    if field not in sample:
                        errors.append("sample missing field: " + field)
                resources = sample.get("resources", {})
                for field in ("download_observed", "bytes_downloaded",
                              "download_duration_ms", "decompression_duration_ms",
                              "measurement"):
                    if field not in resources:
                        errors.append("sample resources missing field: " + field)
                correctness = sample.get("correctness", {})
                if not isinstance(correctness, dict) or "ok" not in correctness or "errors" not in correctness:
                    errors.append("sample correctness is incomplete")
    return errors


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def write(path, payload):
    errors = validate(payload)
    if errors:
        raise ValueError("invalid benchmark result:\n- " + "\n- ".join(errors))
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".tectdist-result-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
