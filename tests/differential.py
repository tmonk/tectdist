#!/usr/bin/env python3
"""Compare a native tectdist candidate against the Python reference.

This intentionally has no Cargo dependency: CI can point TECTDIST_NATIVE at a
prebuilt artifact and use the same mock engine fixtures as the acceptance
battery. It is a migration gate, not a replacement for that battery.
"""
import argparse
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / "bin" / "pdflatex"


def run(command, arguments, cwd, env):
    return subprocess.run([str(command), *arguments], cwd=cwd, env=env,
                          capture_output=True, text=True)


def visible_files(directory):
    """Return deterministic observable side effects, excluding test plumbing."""
    ignored = {"engine", "engine.args", "sample.tex", "pdflatex", "latexmk"}
    return sorted(str(path.relative_to(directory)) + ("/" if path.is_dir() else "")
                  for path in directory.rglob("*")
                  if path.name not in ignored)


def prepare_case(root, name):
    directory = root / name
    directory.mkdir()
    (directory / "sample.tex").write_text(
        "\\documentclass{article}\\begin{document}ok\\end{document}\n",
        encoding="utf-8")
    engine = directory / "engine"
    engine.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$@\" > engine.args\nexit \"${ENGINE_EXIT:-0}\"\n",
        encoding="utf-8")
    engine.chmod(0o755)
    return directory, engine


def assert_compile_case(root, native, label, arguments, overlay):
    observed = []
    for implementation, command in (("python", PYTHON), ("native", native)):
        directory, engine = prepare_case(root, f"{label}-{implementation}")
        if implementation == "native":
            native_program = directory / "pdflatex"
            native_program.symlink_to(command)
            command = native_program
        environment = os.environ.copy()
        environment.update(TECTONIC=str(engine), TECTDIST_SKIP_PAIRING="1",
                           TECTDIST_ENGINE_MODE="external")
        environment.update(overlay)
        result = run(command, arguments, directory, environment)
        engine_args = ((directory / "engine.args").read_text(encoding="utf-8")
                       if (directory / "engine.args").is_file() else None)
        observed.append((implementation, result.returncode, engine_args,
                         visible_files(directory)))
    reference, candidate = observed
    if reference[1:] != candidate[1:]:
        raise SystemExit("differential mismatch for %r\npython=%r\nnative=%r" %
                         (arguments, reference[1:], candidate[1:]))


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--native", default=os.environ.get("TECTDIST_NATIVE"))
    ns = parser.parse_args(argv)
    if not ns.native:
        print("differential: SKIPPED (set TECTDIST_NATIVE)")
        return 0
    native = Path(ns.native).resolve()
    if not native.is_file() or not os.access(native, os.X_OK):
        raise SystemExit("native candidate is not executable: %s" % native)
    with tempfile.TemporaryDirectory(prefix="tectdist-differential-") as scratch:
        root = Path(scratch)
        cases = [
            (["-synctex=1", "-output-directory=out", "sample.tex"], {}),
            (["-interaction=batchmode", "sample.tex"], {}),
            (["-fmt=latex", "-main-memory", "9000000",
              "-include-directory=local", "sample.tex"], {"TEXINPUTS": "styles:"}),
            (["-jobname=renamed", "sample.tex"], {}),
            (["-synctex", "0", "-output-directory", "out", "sample.tex"], {}),
            (["-recorder", "-file-line-error", "-halt-on-error", "sample.tex"], {}),
            (["--keep-logs", "sample.tex"], {}),
            (["--", "-odd.tex"], {}),
            (["-main-memory=123", "-extra-mem-top", "456", "sample.tex"], {}),
            (["sample.tex"], {"ENGINE_EXIT": "42"}),
        ]
        for index, (arguments, overlay) in enumerate(cases):
            assert_compile_case(root, native, f"case-{index}", arguments, overlay)

        # Exercise the native latexmk route through argv[0], including its
        # one-shot delegation to the shared engine compatibility path.
        directory, engine = prepare_case(root, "latexmk")
        env = os.environ.copy()
        env.update(TECTONIC=str(engine), TECTDIST_SKIP_PAIRING="1",
                   TECTDIST_ENGINE_MODE="external")
        native_latexmk = directory / "latexmk"
        native_latexmk.symlink_to(native)
        reference = run(ROOT / "bin" / "latexmk", ["-pdf", "-synctex=1", "sample.tex"], directory, env)
        reference_args = (directory / "engine.args").read_text()
        native_result = run(native_latexmk, ["-pdf", "-synctex=1", "sample.tex"], directory, env)
        native_args = (directory / "engine.args").read_text()
        if reference.returncode != native_result.returncode or reference_args != native_args:
            raise SystemExit("latexmk differential mismatch\npython=%r %r\nnative=%r %r" %
                             (reference.returncode, reference_args,
                              native_result.returncode, native_args))
    print("differential: OK")


if __name__ == "__main__":
    raise SystemExit(main())
