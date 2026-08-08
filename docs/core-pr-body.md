# tectdist 0.2.0: Standard-TeX-compatible TeX distribution backed by Tectonic

## What it is

`tectdist` is a complete, standard-TeX-compatible TeX distribution backed by
[Tectonic](https://tectonic-typesetting.github.io): a single-file Python
zipapp plus a symlink farm of the classic TeX tool names (`pdflatex`,
`latex`, `xelatex`, `latexmk`, `kpsewhich`, `bibtex`, `epstopdf`, `pdfcrop`,
…).  The dispatcher switches on the invoked name, accepts the classic web2c
flag vocabulary, and proxies poppler/qpdf/ghostscript tools to those real
formulae without shadowing them.

`brew install tmonk/brew/tectdist` gives a user a working TeX system with a
biblatex pipeline out of the box — no TeX Live, no extra packages.

## Dependencies (all pure core formulae)

`tectonic`, `python@3.14` (zipapp interpreter), `ghostscript`, `poppler`,
`qpdf`, `perl`, `libxml2`, `libxslt`, `openssl@3`, `pkgconf` (build).

## Why biber is built from source inside the formula

The formula builds **biber 2.17** from source (the `plk/biber` v2.17 source
tarball plus the CPAN module resources listed below — the same resource set
homebrew-core's own `biber` formula carries), rather than adding
`depends_on "biber"`.  Reason: the version pairing.  Tectonic 0.17 bundles
biblatex 3.17, which writes `.bcf` format 3.8; homebrew-core's `biber`
(2.21) speaks `.bcf` 3.11 and **aborts** on 3.8 (verified empirically).
Because `biber` in core is bumped on its own schedule, a
`depends_on "biber"` would put every tectdist install at the mercy of a
package that can silently break biblatex on any `brew upgrade`.  Building
the matched biber into the formula keeps the pair as one release unit.

The biber resources are source tarballs (GitHub for `plk/biber`, metacpan
for the 119 modules), all sha256-pinned — no prebuilt binaries.

## Why `depends_on "perl"`

biber 2.17's `Build.PL` requires perl ≥ 5.32.  macOS system perl is 5.30.3
on macOS ≤ 15 (5.34.1 on newer) — a version-dependent source of truth.  The
formula uses the brew `perl` formula deterministically on every platform
and stages the full module closure unconditionally (the same set core's
`biber` formula already carries on Linux).

## Runtime pairing check (software behaviour, not formula DSL)

Each release declares its pairing in the software
(`src/tectdist/pairing.py`); the formula mirrors `TECTONIC_VERSION` as a
constant.  The dispatcher compares the actual installed tectonic against
the declaration on every invocation and fails fast with instructions when
brew's tectonic moves; `tectdist doctor` prints the full report.  A weekly
GitHub Actions watcher and lockstep release bumps keep a matched release
available before brew's tectonic moves.  There is no dependency-version
pinning in the formula.

## How it was tested

* Acceptance battery (`tests/battery.py`): 298 checks green (mock flag
  vocabulary/translation + real-engine end-to-end, incl. a biblatex
  end-to-end compile through the installed farm).
* A release gate in the battery keeps `Formula/tectdist.rb`'s
  `TECTONIC_VERSION` equal to `src/tectdist/pairing.py`'s (and the biber
  resource version equal to `BIBER_VERSION`).
* On this fork: `brew style` clean, `brew audit --strict --new --online`
  clean (zero findings), `brew install --build-from-source` green,
  `brew test` green.
* biblatex end-to-end on macOS arm64 through the installed keg: a
  `biblatex`/`biber` document compiles to a PDF whose bibliography contains
  the correct formatted citation.
