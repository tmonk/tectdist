#!/usr/bin/env python3
"""Optional setup: add tectdist/bin to PATH so `pdflatex`, `latexmk`, etc.
work as bare commands.  Non-destructive and idempotent.  The line added is
shell-neutral, so any bash/zsh/fish-compatible rc file works.

Run:
    python3 install.py            # adds PATH line to ~/.zshrc (macOS default)
    python3 install.py ~/.bashrc  # or target any rc file explicitly
"""

import os
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
BIN = os.path.join(HERE, "bin")
MARKER = "# tectdist (Tectonic-backed TeX distribution)"


def main():
    rc = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/.zshrc")
    rc = os.path.expanduser(rc)
    if not os.path.isfile(rc):
        print(f"install.py: {rc} does not exist; creating it.", file=sys.stderr)
        os.makedirs(os.path.dirname(rc), exist_ok=True)
        open(rc, "a").close()
    with open(rc, encoding="utf-8", errors="replace") as f:
        content = f.read()
    if "tectdist/bin" in content or "texdist/bin" in content or MARKER in content:
        print(f"install.py: tectdist already on PATH in {rc} (nothing to do).")
    else:
        # the repo path lands inside a double-quoted shell string: escape the
        # characters that would otherwise break or inject into the user's rc
        esc = BIN.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$")
        with open(rc, "a", encoding="utf-8") as f:
            f.write(f"\n{MARKER}\nexport PATH=\"{esc}:$PATH\"\n")
        print(f"install.py: added '{BIN}' to PATH in {rc}")
    print("install.py: start a new shell, then try: "
          "pdflatex --version ; latexmk --version")
    return 0


if __name__ == "__main__":
    sys.exit(main())
