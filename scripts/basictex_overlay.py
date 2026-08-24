#!/usr/bin/env python3
"""Overlay generation tracking for the BasicTeX profile (plan B1/§11).

Every mutable overlay (TEXMFHOME, TEXMFLOCAL, project tree) gets a content
digest and a monotonically increasing generation counter stored beside it.
The generation changes whenever any tracked file's digest changes; snapshot
and action keys must embed the generation so stale reuse is impossible.
Digest validation — never mtime — decides equality (plan §12).

Usage:
    python3 scripts/basictex_overlay.py generation <overlay-dir>...
    python3 scripts/basictex_overlay.py digest <overlay-dir>

`generation` updates <overlay>/.tectdist-overlay.json and prints the new
generation number. `digest` prints the current content digest without
mutating anything (used inside snapshot keys).
"""
import hashlib
import json
from pathlib import Path
import sys

STATE_FILE = ".tectdist-overlay.json"
TRACKED_SUFFIXES = {".tex", ".sty", ".cls", ".def", ".cfg", ".bib", ".bst",
                    ".ist", ".fd", ".tfm", ".vf", ".ttf", ".otf", ".pfb",
                    ".map", ".enc", ".clo", ".bbx", ".cbx", ".lbx"}
IGNORED_NAMES = {STATE_FILE, "ls-R"}


def content_digest(root: Path) -> str:
    """Digest of every tracked file's path + bytes, order-independent."""
    entries = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name in IGNORED_NAMES:
            continue
        if path.suffix.lower() not in TRACKED_SUFFIXES:
            continue
        rel = str(path.relative_to(root))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        entries.append(f"{rel}:{digest}")
    combined = "\n".join(sorted(entries))
    return hashlib.sha256(combined.encode()).hexdigest()


def main(argv=None):
    if len(argv) < 2 or argv[0] not in ("generation", "digest"):
        print(__doc__)
        return 2
    mode = argv[0]
    failures = 0
    for argument in argv[1:]:
        root = Path(argument)
        if not root.is_dir():
            print(f"overlay: {root}: not a directory")
            failures += 1
            continue
        digest = content_digest(root)
        if mode == "digest":
            print(f"{root}: {digest}")
            continue
        state_path = root / STATE_FILE
        try:
            state = json.loads(state_path.read_text())
        except (OSError, json.JSONDecodeError):
            state = {"generation": 0}
        previous_digest = state.get("digest")
        if previous_digest == digest:
            print(f"{root}: generation {state['generation']} (unchanged)")
            continue
        # Digest changed (or first observation): bump the generation only
        # when the change is real relative to the last recorded generation,
        # i.e. always on first sight, otherwise +1 per observed change.
        state["generation"] = state.get("generation", 0) + 1
        state["digest"] = digest
        state_path.write_text(json.dumps(state, indent=2) + "\n")
        print(f"{root}: generation {state['generation']}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
