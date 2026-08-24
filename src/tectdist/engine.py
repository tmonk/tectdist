"""External Tectonic executor shared by direct and latexmk invocations."""

import os

from .plan import ExecutionResult
from .trace import span


def run_external(argv, runner):
    """Run an already-resolved engine argv without a shell or wrapper."""
    with span("engine.spawn", executable=argv[0] if argv else ""):
        with span("engine.run"):
            return ExecutionResult(returncode=runner(argv), engine_passes=1)


def existing_output_directory(args):
    """Return Tectonic's output directory from a translated argument list."""
    try:
        return args[args.index("-o") + 1]
    except (ValueError, IndexError):
        return "."


def ensure_output_directory(path):
    """Avoid a syscall on the usual existing-directory fast path."""
    if os.path.isdir(path):
        return
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        pass
