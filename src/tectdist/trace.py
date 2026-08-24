"""Opt-in JSON-lines tracing for one tectdist invocation.

``TECTDIST_TRACE_FILE`` is intentionally private implementation telemetry,
not a user-facing stable API. Appending makes nested library calls safe and
allows a benchmark runner to collect separate process traces in one file.
"""

import json
import os
import time


def emit(name, start_ns, **fields):
    path = os.environ.get("TECTDIST_TRACE_FILE")
    if not path:
        return
    payload = {"schema_version": 1, "span": name,
               "start_ns": start_ns, "duration_ns": time.perf_counter_ns() - start_ns}
    payload.update(fields)
    try:
        with open(path, "a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, sort_keys=True) + "\n")
    except OSError:
        # Telemetry must never prevent a document compilation.
        pass


class span:
    def __init__(self, name, **fields):
        self.name = name
        self.fields = fields
        self.start_ns = 0

    def __enter__(self):
        self.start_ns = time.perf_counter_ns()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.fields["ok"] = exc_type is None
        emit(self.name, self.start_ns, **self.fields)
        return False
