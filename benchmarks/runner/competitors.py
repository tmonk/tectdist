"""Competitor definitions; commands are explicit and stored in raw results."""
import hashlib
import os
import shlex
import shutil
import subprocess


def _executable(command):
    """Resolve commands wrapped by `env NAME=value` without losing identity."""
    environment = os.environ.copy()
    index = 0
    if command and os.path.basename(command[0]) == "env":
        index = 1
        while index < len(command) and "=" in command[index]:
            name, value = command[index].split("=", 1)
            environment[name] = value
            index += 1
    executable = command[index] if index < len(command) else command[0]
    resolved = shutil.which(executable, path=environment.get("PATH")) or executable
    return resolved, environment


def describe(name, command):
    resolved, environment = _executable(command)
    try:
        version = subprocess.run([resolved, "--version"], text=True,
                                 errors="replace", env=environment,
                                 capture_output=True, timeout=15).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        version = ""
    try:
        binary_size = os.path.getsize(resolved)
        with open(resolved, "rb") as stream:
            binary_sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
    except OSError:
        binary_size = None
        binary_sha256 = None
    if name == "texlive-latexmk":
        bundle = {
            "source": os.environ.get("TECTDIST_TEXLIVE_SOURCE", "unknown"),
            "identity": os.environ.get("TECTDIST_TEXLIVE_ID", "unknown"),
            "manifest_sha256": os.environ.get(
                "TECTDIST_TEXLIVE_MANIFEST_SHA256", "unknown"),
            "format_cache_identity": os.environ.get(
                "TECTDIST_TEXLIVE_FORMAT_ID", "unknown"),
        }
    else:
        bundle = {
            "source": os.environ.get("TECTDIST_BUNDLE_SOURCE",
                                     os.environ.get("TECTONIC_BUNDLE_URL", "default")),
            "identity": os.environ.get("TECTDIST_BUNDLE_ID", "unknown"),
            "manifest_sha256": os.environ.get(
                "TECTDIST_BUNDLE_MANIFEST_SHA256", "unknown"),
            "format_cache_identity": os.environ.get("TECTDIST_FORMAT_CACHE_ID", "unknown"),
        }
    return {"name": name, "path": os.path.abspath(resolved),
            "command": command, "version_output": version,
            "binary_size_bytes": binary_size,
            "binary_sha256": binary_sha256,
            # These are explicit runner inputs rather than guesses from an
            # arbitrary user cache. Qualification invocations must declare
            # immutable identities; smoke results preserve "unknown".
            "bundle": bundle}


def from_environment(candidate):
    """Discover only explicitly configured competitors, avoiding PATH ambiguity."""
    competitors = {"candidate": candidate}
    for label, env in (("direct-tectonic", "TECTDIST_BENCH_DIRECT_TECTONIC"),
                       ("previous-tectdist", "TECTDIST_BENCH_PREVIOUS"),
                       ("texlive-latexmk", "TECTDIST_BENCH_LATEXMK"),
                       ("cluttex", "TECTDIST_BENCH_CLUTTEX")):
        value = os.environ.get(env)
        if value:
            competitors[label] = shlex.split(value)
    return competitors
