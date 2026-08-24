#!/usr/bin/env python3
"""Generate the BT100 package ledger from the frozen TLPDB (plan §8.1).

Every package in the frozen BasicTeX manifest receives a ledger row — no
exclusions at release time. Fields derivable locally are populated now;
verdict columns are filled by the compatibility runner
(scripts/basictex_smoke.py) and merged back into the final report.

Usage:
    python3 scripts/basictex_ledger.py [--output PATH]
"""
import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "reference/basictex-2026"


def parse_tlpdb(path):
    packages = {}
    current = None
    in_runfiles = False
    runfiles = []
    for line in Path(path).read_text(errors="replace").splitlines():
        if line.startswith("name "):
            if current is not None:
                current["run_file_count"] = len(runfiles)
            current = {"revision": "", "licence": "", "depends": [],
                       "run_file_count": 0, "styles": []}
            in_runfiles = False
            runfiles = []
            packages[line[5:].strip()] = current
            continue
        if current is None:
            continue
        directive = re.match(r"^([a-z-]+)", line)
        if directive and not line.startswith(" "):
            word = directive.group(1)
            in_runfiles = word == "runfiles"
            rest = line[len(word):].strip()
            if word == "revision":
                current["revision"] = rest
            elif word == "catalogue-licence":
                current["licence"] = rest
            elif word == "depend":
                current["depends"].append(rest)
            elif in_runfiles or word == "runfiles":
                files = re.sub(r"^size=\d+\s*", "", rest) if word == "runfiles" else rest
                runfiles.extend(files.split())
                for file_name in files.split():
                    if file_name.endswith((".sty", ".cls")):
                        current["styles"].append(
                            file_name.rsplit("/", 1)[-1].rsplit(".", 1)[0])
        elif line.startswith(" ") and in_runfiles:
            runfiles.extend(line.split())
            for file_name in line.split():
                if file_name.endswith((".sty", ".cls")):
                    current["styles"].append(
                        file_name.rsplit("/", 1)[-1].rsplit(".", 1)[0])
    if current is not None:
        current["run_file_count"] = len(runfiles)
    return packages


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",
                        default=str(REFERENCE / "package-ledger.json"))
    ns = parser.parse_args(argv)

    packages = parse_tlpdb(REFERENCE / "texlive.tlpdb")
    ledger = []
    for name in sorted(packages):
        meta = packages[name]
        ledger.append({
            "package": name,
            "revision": meta["revision"],
            "licence": meta["licence"] or "unknown",
            "depends": meta["depends"],
            "run_file_count": meta["run_file_count"],
            "loadable_styles": sorted(set(meta["styles"])),
            # Verdict fields filled by basictex_smoke.py / combination runs.
            "smoke_verdict": None,
            "combination_verdict": None,
        })

    out = Path(ns.output)
    out.write_text(json.dumps({
        "schema_version": 1,
        "image_files_sha256": json.load(
            open(REFERENCE / "platform-manifest.json"))["image_files_sha256"],
        "rows": ledger,
    }, indent=2) + "\n")

    style_providers = sum(1 for row in ledger if row["loadable_styles"])
    print(f"ledger: {len(ledger)} package rows "
          f"({style_providers} provide loadable styles) -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
