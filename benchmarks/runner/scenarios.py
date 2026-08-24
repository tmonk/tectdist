"""Scenario setup. Each trial receives an isolated source copy."""
import os
import shutil
from pathlib import Path


def prepare(source, destination, scenario, main):
    shutil.copytree(source, destination)
    target = Path(destination) / main
    if scenario == "source-small-edit" and target.is_file():
        # A comment changes source bytes without changing document semantics.
        with target.open("a", encoding="utf-8") as stream:
            stream.write("\n% tectdist deterministic small benchmark edit\n")
    elif scenario == "source-structural-edit" and target.is_file():
        # Insert before the final document end so the result is valid LaTeX
        # while forcing a visible structural change and normal rerun handling.
        text = target.read_text(encoding="utf-8")
        marker = "\\end{document}"
        insertion = "\\section*{Deterministic benchmark structural edit}\n"
        if marker in text:
            target.write_text(text.rsplit(marker, 1)[0] + insertion + marker + text.rsplit(marker, 1)[1],
                              encoding="utf-8")
        else:
            with target.open("a", encoding="utf-8") as stream:
                stream.write("\n" + insertion)


def environment(destination, scenario, inherited=None):
    """Return a reproducible per-trial environment overlay.

    Tectonic and related tooling honor XDG cache placement. A cold run gets a
    brand-new empty directory; warm runs retain the caller's configured cache
    while project output state remains isolated in ``destination``.
    """
    result = dict(os.environ if inherited is None else inherited)
    if scenario == "cold-empty-cache":
        cache = Path(destination) / ".tectdist-cold-cache"
        cache.mkdir(parents=True, exist_ok=True)
        result["XDG_CACHE_HOME"] = str(cache)
        # Tectonic's pinned driver honors this explicitly on macOS as well as
        # XDG platforms; keep both so the cache state is declared and empty.
        result["TECTONIC_CACHE_DIR"] = str(cache)
    return result
