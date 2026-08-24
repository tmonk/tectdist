#!/usr/bin/env python3
"""Fetch the pinned, compact ITP3 QFT LaTeX benchmark workload."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "benchmarks" / "external" / "itp3-qft"
BASE_URL = "https://web.itp3.uni-stuttgart.de/latex-benchmark/git/benchmark/"
FILES = {
    "QFT.tex": "706f62fdc5e4aa79c59918ef1df429c594baf75465421d470735deaefdd7ad37",
    "bib/QFT.bib": "995be65b540ac96bc97810dd7631fb8a4b11d1ba06adeaca0261896c3878a423",
    "bib/bibstyle.bst": "e687df7460e305c12c332f0bb79899b43ae91550d1adccffbb2724c72c57bd38",
    "data/classical_field_theory.tex": "06156a3bb685cd1eb08fe08403e4f48a95a4326bc0eee4850ce8804996b04c3d",
    "data/dirac_field.tex": "21bfe2ecbd644b4604411c399e4611a297793f0fb66638403d1bbe70d7559395",
    "data/klein_gordon_field.tex": "b02ac86bfad385bc8cc8b304e89c024b5f1eaab159ea447ca8457558255e102e",
    "data/preliminaries.tex": "cd0f0773b1d4a16b5358c36a369665ea6cb1d95f2bcf96d651099d017e3b5b96",
    "figures/eep.pdf": "3b4f66beede56ccbcf02459631391daac4fdf19def9fddc6cfc03ac81626c57f",
    "figures/itp3_logo_institut_simple_hellgrau.png": "10304c247c632bde88ff23d64431f9e127f1638d1fb3560a7b6730458a40cfda",
    "figures/ontology.pdf": "34b650f7b4ec557f73f7b6fdba47ee4e37049681c3c3f0bbcd8b6451c94835db",
    "figures/spin-statistics.pdf": "dcaf01f93eb28b87b39e284fed461e8a648420954e91cf7c529ac5e83095f42c",
    "figures/tikz/cauchy.tikz": "f487deae03d07e1646fdc71e51aaf5aa87e5a45aef13011b2af6206f76536fa7",
    "figures/tikz/contour_retarded.tikz": "a09195bf9e27c95ec70f5316d9a20e80b09a9925a498d1a6ea468e81558ef971",
    "figures/tikz/feynman_contour.tikz": "89153ebd8b323a3c2a2fe1c8ee58764709b7a794cb92e227c29893aa952ebc72",
    "figures/tikz/free_boson.tikz": "68b22c5e1406ff7f5152fb18160ba1a4ece0cbdb625be509831476ce9745304d",
    "figures/tikz/lorentz_trafo.tikz": "0429ed1875a788cc7e9fcde3f06a12a1f038e9d3d5d0d64740b18f7034da5715",
    "figures/tikz/structure_lorentz_group.tikz": "280064d923482560e1deb40d725608e785be221881ab54b5835496634200fb35",
    "figures/tikz/symmetry_transformation.tikz": "3d49e2468ac0989d2c79a77695f9212aee992a0c793265d1d3271efb5defa0f7",
    "inc/commands.tex": "19b7041301e3729d1be8f9fc730501d0ea7d31b209e01cfb4bc345b779ff24b6",
    "inc/packages.tex": "ae11135b5721d2279c1eb739d06bebd3fb08322e062f9ebeac9c721314526d7e",
    "inc/settings.tex": "45b2a4edfe11483cc461028a3f0d429c1cc9fe902a6a0035ba02db72cd825cf0",
}


def fetch(destination=DESTINATION):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Stage alongside the destination so the final rename cannot cross devices.
    with tempfile.TemporaryDirectory(
            prefix=".tectdist-itp3-", dir=destination.parent) as temporary:
        staging = Path(temporary) / "itp3-qft"
        for relative, expected in FILES.items():
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with urllib.request.urlopen(BASE_URL + relative, timeout=60) as response:
                with target.open("wb") as output:
                    shutil.copyfileobj(response, output)
            actual = hashlib.sha256(target.read_bytes()).hexdigest()
            if actual != expected:
                raise RuntimeError(f"checksum mismatch for {relative}: {actual}")
        metadata = {"source": BASE_URL, "files": FILES,
                    "total_bytes": sum((staging / name).stat().st_size for name in FILES)}
        (staging / "tectdist-source.json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if destination.exists():
            shutil.rmtree(destination)
        os.replace(staging, destination)
    return destination


def main():
    output = fetch()
    print(f"fetch_itp3_fixture.py: {len(FILES)} files, "
          f"{sum((output / name).stat().st_size for name in FILES)} bytes -> {output}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"fetch_itp3_fixture.py: {error}", file=sys.stderr)
        raise SystemExit(1)
