#!/usr/bin/env python3
"""Set up a source checkout for command-line use.

One command builds the embedded native binary and its TeX-compatible command
farm, then adds it to PATH. The shell config is chosen from ``$SHELL``; pass a
file to override it. Use ``--external-only`` for the native fallback build or
``--python-reference`` for migration testing.

Run:
    python3 install.py
    python3 install.py --external-only
    python3 install.py --python-reference
    python3 install.py ~/.bashrc  # optional explicit shell config
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
SOURCE_BIN = os.path.join(HERE, "bin")
BIN = os.path.join(HERE, "dist", "native-bin")
NATIVE_EXECUTABLE = os.path.join(HERE, "dist", "native", "tectdist")
MARKER = "# tectdist (Tectonic-backed TeX distribution)"


def shell_quote(value):
    """Return ``value`` as one POSIX-shell word.

    A checkout can legally contain spaces, dollar signs, backticks, or single
    quotes.  The PATH entry is sourced by a shell later, so using a
    double-quoted string here would still evaluate command substitutions in a
    hostile/unusual checkout path.  POSIX single-quoting is literal; splice a
    single quote with the standard ``'\"'\"'`` sequence when necessary.
    """
    return "'" + value.replace("'", "'\"'\"'") + "'"


def fish_quote(value):
    """Return ``value`` as one literal fish-shell word."""
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def default_rc(environ=None, platform=None):
    """Choose the config file read by the user's interactive shell."""
    environ = os.environ if environ is None else environ
    platform = sys.platform if platform is None else platform
    home = environ.get("HOME") or os.path.expanduser("~")
    shell = os.path.basename(environ.get("SHELL", ""))
    if shell == "bash":
        bashrc = os.path.join(home, ".bashrc")
        bash_profile = os.path.join(home, ".bash_profile")
        for existing in (bashrc, bash_profile):
            if os.path.isfile(existing):
                return existing
        return bash_profile if platform == "darwin" else bashrc
    relative = {
        "zsh": ".zshrc",
        "fish": os.path.join(".config", "fish", "config.fish"),
    }.get(shell, ".profile")
    return os.path.join(home, relative)


def is_fish_config(path):
    normalized = path.replace("\\", "/")
    return normalized.endswith(".fish") or "/fish/" in normalized


def path_line(rc, binary_directory=None):
    binary_directory = BIN if binary_directory is None else binary_directory
    if is_fish_config(rc):
        return f"fish_add_path {fish_quote(binary_directory)}"
    return f"export PATH={shell_quote(binary_directory)}:\"$PATH\""


def add_path_entry(rc, binary_directory=None):
    """Add the PATH entry to ``rc``. Return True when the file changed."""
    binary_directory = BIN if binary_directory is None else binary_directory
    rc = os.path.expanduser(rc)
    if not os.path.isfile(rc):
        print(f"install.py: {rc} does not exist; creating it.", file=sys.stderr)
        parent = os.path.dirname(os.path.abspath(rc))
        os.makedirs(parent, exist_ok=True)
        with open(rc, "a", encoding="utf-8"):
            pass
    with open(rc, encoding="utf-8", errors="replace") as f:
        content = f.read()
    if "tectdist/bin" in content or "texdist/bin" in content or MARKER in content:
        print(f"install.py: tectdist already on PATH in {rc} (nothing to do).")
        return False
    else:
        with open(rc, "a", encoding="utf-8") as f:
            f.write(f"\n{MARKER}\n{path_line(rc, binary_directory)}\n")
        print(f"install.py: added '{binary_directory}' to PATH in {rc}")
        return True


def build_native_farm(external_only=False):
    """Build the native binary and an isolated argv[0] compatibility farm."""
    command = [sys.executable, os.path.join(HERE, "build.py"), "--native",
               "--output", NATIVE_EXECUTABLE]
    if external_only:
        command.append("--no-embedded")
    subprocess.run(command, cwd=HERE, check=True)
    sys.path.insert(0, os.path.join(HERE, "src"))
    from tectdist.flags import FARM_NAMES
    os.makedirs(BIN, exist_ok=True)
    names = set(FARM_NAMES)
    names.add("tectdist")
    relative_target = os.path.relpath(NATIVE_EXECUTABLE, BIN)
    for name in names:
        path = os.path.join(BIN, name)
        if os.path.lexists(path):
            os.unlink(path)
        os.symlink(relative_target, path)
    # Tectonic intentionally does not run MakeIndex itself. Install the small,
    # pinned upstream tool at the real farm entry rather than leaving the
    # compatibility stub in charge of index and glossary stages.
    sys.path.insert(0, os.path.join(HERE, "scripts"))
    from bootstrap_makeindex import build as build_makeindex
    makeindex = os.path.join(BIN, "makeindex")
    if os.path.lexists(makeindex):
        os.unlink(makeindex)
    build_makeindex(makeindex)
    return BIN


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if any(a in ("-h", "--help") for a in args):
        print(__doc__.strip())
        return 0
    python_reference = "--python-reference" in args
    external_only = "--external-only" in args
    args = [arg for arg in args if arg not in ("--python-reference", "--external-only")]
    if len(args) > 1 or (python_reference and external_only):
        print("usage: python3 install.py [--python-reference | --external-only] [SHELL_CONFIG]",
              file=sys.stderr)
        return 2

    binary_directory = SOURCE_BIN if python_reference else build_native_farm(external_only)

    rc = os.path.expanduser(args[0]) if args else default_rc()
    add_path_entry(rc, binary_directory)
    print("\nReady. Open a new shell, then run:")
    print("  tectdist doctor")
    print("  tectdist main.tex")
    return 0


if __name__ == "__main__":
    sys.exit(main())
