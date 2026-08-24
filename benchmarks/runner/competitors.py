"""Competitor definitions; commands are explicit and stored in raw results."""
import os
import shutil
import subprocess


def describe(name, command):
    executable = command[0]
    resolved = shutil.which(executable) or executable
    try:
        version = subprocess.run([resolved, "--version"], text=True,
                                 capture_output=True, timeout=15).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        version = ""
    try:
        binary_size = os.path.getsize(resolved)
    except OSError:
        binary_size = None
    return {"name": name, "path": os.path.abspath(resolved),
            "command": command, "version_output": version,
            "binary_size_bytes": binary_size,
            # These are explicit runner inputs rather than guesses from an
            # arbitrary user cache. Qualification invocations must declare
            # immutable identities; smoke results preserve "unknown".
            "bundle": {
                "source": os.environ.get("TECTDIST_BUNDLE_SOURCE",
                                         os.environ.get("TECTONIC_BUNDLE_URL", "default")),
                "identity": os.environ.get("TECTDIST_BUNDLE_ID", "unknown"),
                "manifest_sha256": os.environ.get(
                    "TECTDIST_BUNDLE_MANIFEST_SHA256", "unknown"),
                "format_cache_identity": os.environ.get("TECTDIST_FORMAT_CACHE_ID", "unknown"),
            }}


def from_environment(candidate):
    """Discover only explicitly configured competitors, avoiding PATH ambiguity."""
    competitors = {"candidate": candidate}
    for label, env in (("direct-tectonic", "TECTDIST_BENCH_DIRECT_TECTONIC"),
                       ("previous-tectdist", "TECTDIST_BENCH_PREVIOUS"),
                       ("texlive-latexmk", "TECTDIST_BENCH_LATEXMK"),
                       ("cluttex", "TECTDIST_BENCH_CLUTTEX")):
        value = os.environ.get(env)
        if value:
            competitors[label] = value.split()
    return competitors
