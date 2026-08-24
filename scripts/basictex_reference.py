#!/usr/bin/env python3
"""Generate the pinned BasicTeX reference manifests (plan BT100-003).

Reads the extracted BasicTeX payload tree and emits every manifest artefact
required by BASICTEX_X10_PLAN.md §2.2 into reference/basictex-2026/:

  installed-packages.txt   package name + revision from texlive.tlpdb
  texlive.tlpdb            copy of the installed database
  files.sha256             SHA-256 of every installed file
  binaries.txt             bin/<platform>/ entries with target identity
  formats.txt              formats present in texmf-var/web2c
  fmtutil-list.txt         fmtutil.cnf enabled lines
  updmap-state.txt         updmap configuration files
  kpathsea-vars.json       key Kpathsea variable values as resolved
  package-closure.json     packages + dependency closure summary
  platform-manifest.json   image identity: digests, platform, TL revision
  licence-report.json      per-package licence fields from the TLPDB

Usage:
    python3 scripts/basictex_reference.py [--payload PATH] [--output PATH]
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import re
import subprocess
import sys


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_tlpdb(path):
    """Return {name: {revision, licence, depend, runfiles, binfiles}}."""
    packages = {}
    current = None
    for line in Path(path).read_text(errors="replace").splitlines():
        if line.startswith("name "):
            current = {"name": line[5:].strip(), "revision": "", "licence": "",
                       "depend": [], "runfiles": [], "binfiles": [], "docfiles": []}
            packages[current["name"]] = current
            continue
        if current is None:
            continue
        if line.startswith("revision "):
            current["revision"] = line[9:].strip()
        elif line.startswith("depend "):
            current["depend"].append(line[7:].strip())
        elif line.startswith("execute "):
            pass
        elif line.startswith("catalogue-licence "):
            current["licence"] = line[len("catalogue-licence "):].strip()
        elif line.startswith("runfiles "):
            current["runfiles"] = sorted(line[9:].split())
        elif line.startswith("binfiles "):
            parts = line[9:].split(None, 1)
            if len(parts) == 2:
                arch = parts[0]
                current["binfiles"].extend(f"bin/{arch}/{f}"
                                           for f in parts[1].split())
        elif line.startswith("docfiles "):
            # BasicTeX installs docs only where configured; record anyway.
            current["docfiles"] = sorted(line.split()[1:])
    return packages


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload", required=True,
                        help="extracted Payload/usr/local/texlive/<year>basic directory")
    parser.add_argument("--output", default=None,
                        help="manifest output directory (default: reference/basictex-2026)")
    ns = parser.parse_args(argv)

    root = Path(ns.payload).resolve()
    if not root.is_dir():
        raise SystemExit(f"payload directory not found: {root}")
    out = Path(ns.output) if ns.output else \
        Path(__file__).resolve().parents[1] / "reference/basictex-2026"
    out.mkdir(parents=True, exist_ok=True)
    print(f"reference: payload {root}")

    tlpdb_path = root / "tlpkg/texlive.tlpdb"
    packages = parse_tlpdb(tlpdb_path)
    print(f"reference: {len(packages)} packages in TLPDB")

    def write(name, text):
        (out / name).write_text(text)
        print(f"reference: wrote {name}")

    # installed-packages.txt
    lines = [f"{name}\t{meta['revision']}"
             for name, meta in sorted(packages.items())]
    write("installed-packages.txt", "\n".join(lines) + "\n")

    # texlive.tlpdb copy
    shutil_copy = tlpdb_path.read_bytes()
    (out / "texlive.tlpdb").write_bytes(shutil_copy)

    # files.sha256 — hash everything under root.
    hashes = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            rel = path.relative_to(root)
            hashes.append(f"{sha256(path)}  {rel}")
    write("files.sha256", "\n".join(hashes) + "\n")

    # binaries.txt — resolve symlink chains for identity.
    bindir = next((root / "bin").iterdir())
    platform_name = f"{bindir.parent.name}/{bindir.name}" if False else bindir.name
    entries = []
    for binary in sorted(bindir.iterdir()):
        target = os_readlink_chain(binary)
        size = binary.stat().st_size if not binary.is_symlink() else 0
        entries.append(f"{binary.name}\t{'link->' + target if target else 'file'}\t{size}")
    write("binaries.txt", "\n".join(entries) + "\n")

    # formats.txt — generated format files shipped/generated in texmf-var.
    formats = []
    web2c = root / "texmf-var/web2c"
    if web2c.is_dir():
        for fmt in sorted(web2c.rglob("*.fmt")):
            formats.append(f"{fmt.stem}\t{fmt.relative_to(web2c)}")
    write("formats.txt", "\n".join(formats) + "\n")

    # fmtutil-list.txt — enabled lines from all fmtutil.cnf sources.
    cnf_lines = []
    for cnf in list((root / "texmf-dist/web2c").glob("fmtutil*.cnf")) + \
               list((root / "texmf-config/web2c").glob("fmtutil*.cnf")):
        for line in cnf.read_text(errors="replace").splitlines():
            stripped = line.split("#")[0].strip()
            if stripped and not stripped.startswith("#"):
                cnf_lines.append(f"{cnf.name}: {stripped}")
    write("fmtutil-list.txt", "\n".join(sorted(cnf_lines)) + "\n")

    # updmap-state.txt — updmap configuration files.
    updmap = []
    for cfg in list(root.rglob("updmap.cfg")):
        updmap.append(f"### {cfg.relative_to(root)}")
        updmap.extend(cfg.read_text(errors="replace").splitlines())
    write("updmap-state.txt", "\n".join(updmap) + "\n")

    # kpathsea-vars.json via the extracted kpsewhich itself.
    env = dict(os.environ)
    env["TEXMFROOT"] = str(root)
    env["PATH"] = f"{bindir}:{env.get('PATH', '')}"
    variables = ["TEXMFROOT", "TEXMFDIST", "TEXMFHOME", "TEXMFLOCAL",
                 "TEXMFVAR", "TEXMFSYSVAR", "TEXMFCNF", "TEXFORMATS",
                 "WEB2C", "TEXFONTMAPS"]
    values = {}
    for variable in variables:
        result = subprocess.run([str(bindir / "kpsewhich"), f"-var-value={variable}"],
                                env=env, capture_output=True, text=True, timeout=30)
        values[variable] = result.stdout.strip()
    (out / "kpathsea-vars.json").write_text(json.dumps(values, indent=2) + "\n")

    # package-closure.json — packages with dependency summaries.
    closure = {name: {"revision": meta["revision"],
                      "depends": meta["depend"],
                      "run_file_count": len(meta["runfiles"]),
                      "bin_file_count": len(meta["binfiles"])}
               for name, meta in sorted(packages.items())}
    (out / "package-closure.json").write_text(json.dumps(closure, indent=2) + "\n")

    # platform-manifest.json — image identity.
    release = (root / "release-texlive.txt").read_text(errors="replace")
    revision_match = re.search(r"version 20\d\d", release)
    platform_manifest = {
        "distribution": "BasicTeX",
        "texlive_year": revision_match.group(0).split()[-1] if revision_match else "unknown",
        "platform_binary_dir": platform_name,
        "host_platform": f"{platform.system()}-{platform.machine()}",
        "package_count": len(packages),
        "binary_count": len(entries),
        "format_count": len(formats),
        "tree_sha256_note": "see files.sha256; image identity = digest of files.sha256",
    }
    files_digest = hashlib.sha256(
        Path(out / "files.sha256").read_bytes()).hexdigest()
    platform_manifest["image_files_sha256"] = files_digest
    (out / "platform-manifest.json").write_text(json.dumps(platform_manifest, indent=2) + "\n")

    # licence-report.json
    licences = {name: meta["licence"] or "unknown"
                for name, meta in sorted(packages.items())}
    (out / "licence-report.json").write_text(json.dumps(licences, indent=2) + "\n")

    installer_pkg = Path(__file__).resolve().parents[1] / \
        "reference/basictex-2026/installer/BasicTeX.pkg"
    if installer_pkg.is_file():
        print("reference: installer sha512:",
              hashlib.sha512(installer_pkg.read_bytes()).hexdigest())
    print(f"reference: manifests complete in {out}")


def os_readlink_chain(path):
    seen = 0
    while path.is_symlink() and seen < 8:
        path = path.resolve(strict=False)
        seen += 1
    text = str(path)
    marker = "/texlive/"
    return text[text.index(marker) + len(marker):] if marker in text else ""


if __name__ == "__main__":
    import os
    sys.exit(main())
