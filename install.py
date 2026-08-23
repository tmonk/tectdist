#!/usr/bin/env python3
"""Set up a source checkout for command-line use.

One command builds the TeX-compatible command farm and adds it to PATH.  The
shell config is chosen from ``$SHELL``; pass a file to override it.

Run:
    python3 install.py
    python3 install.py ~/.bashrc  # optional explicit shell config
"""

import os
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
BIN = os.path.join(HERE, "bin")
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


def path_line(rc):
    if is_fish_config(rc):
        return f"fish_add_path {fish_quote(BIN)}"
    return f"export PATH={shell_quote(BIN)}:\"$PATH\""


def add_path_entry(rc):
    """Add the PATH entry to ``rc``. Return True when the file changed."""
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
            f.write(f"\n{MARKER}\n{path_line(rc)}\n")
        print(f"install.py: added '{BIN}' to PATH in {rc}")
        return True


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if any(a in ("-h", "--help") for a in args):
        print(__doc__.strip())
        return 0
    if len(args) > 1:
        print("usage: python3 install.py [SHELL_CONFIG]", file=sys.stderr)
        return 2

    # Keep setup genuinely one-command: a fresh checkout need not run
    # make_links.py separately.
    from make_links import main as make_links_main
    make_links_main()

    rc = os.path.expanduser(args[0]) if args else default_rc()
    add_path_entry(rc)
    print("\nReady. Open a new shell, then run:")
    print("  tectdist doctor")
    print("  tectdist main.tex")
    return 0


if __name__ == "__main__":
    sys.exit(main())
