# Releasing

The release is prepared locally (annotated tag at HEAD), but pushing to
GitHub and publishing to Homebrew are manual steps done by a maintainer
with push access.  Current release: **v0.2.0** (biber 2.17 built from
source, pairing enforced at runtime).

The remote repo history was rewritten once for the single-release v0.1.0
(a squashed `release: v0.1.0` commit); backups of the superseded history
(not in the repo):

```sh
/tmp/tectdist-pre-rewrite.bundle
/tmp/tectdist-pre-squash.bundle
```

## 1. The release model

* Each release is **one matched unit**: the software's declared pairing
  (`src/tectdist/pairing.py`) — tectonic minor, biber, biblatex, `.bcf`
  format — the formula (which mirrors `TECTONIC_VERSION`), and the docs.
  See §4b, "Bumping the pairing".
* The formula sources its source tree from the **immutable deterministic
  release asset** (`tectdist-<version>.tar.gz`, built with
  `git archive | gzip -n` from the tag and uploaded once), **not** from
  GitHub's codeload tarballs: codeload regenerates tarballs over time and
  is NOT byte-stable, and Homebrew's ghcr.io mirror can differ from a
  direct curl.  The tag never moves after the release commit.
* Users download source tarballs from canonical upstreams only (our
  release asset, `plk/biber` on GitHub, CPAN modules via metacpan), all
  sha256-pinned — no prebuilt binaries anywhere, no SourceForge.

## 2. Prepare a release (the procedure)

```sh
# 1. bump the version + changelog
#    (src/tectdist/version.py, CHANGELOG.md [x.y.z] entry)
# 2. run the release gate — must be ALL GREEN:
python3 tests/battery.py         # includes the pairing release gate
python3 tests/check_formula.py
python3 tests/check_purity.py dist/tectdist
brew style tmonk/brew/tectdist
brew audit --strict tmonk/brew/tectdist

# 3. commit, then create the annotated tag at the release commit
git tag -a vX.Y.Z -m "tectdist X.Y.Z: <summary>"

# 4. build the deterministic tarball from the tag
git archive --format=tar vX.Y.Z | gzip -n > /tmp/tectdist-X.Y.Z.tar.gz
shasum -a 256 /tmp/tectdist-X.Y.Z.tar.gz

# 5. create the release (gh creates the tag on the REMOTE at the current
#    remote HEAD — force-align it to the release commit afterwards so the
#    remote tag reproduces the asset)
gh release create vX.Y.Z /tmp/tectdist-X.Y.Z.tar.gz \
  --repo tmonk/tectdist --title "tectdist X.Y.Z" --notes-file /tmp/notes.md
git push origin vX.Y.Z --force

# 6. verify determinism from the REMOTE tag
git fetch origin tag vX.Y.Z --force
git archive --format=tar vX.Y.Z | gzip -n | shasum -a 256
#   must equal the sha from step 4 (and the asset's digest)

# 7. fill the formula sha256 (the asset's sha — cannot be precomputed
#    before the upload) into Formula/tectdist.rb, commit, push main
brew fetch --force tmonk/brew/tectdist   # verifies the pinned sha
#   (brew fetch exit 0 = the downloaded file matches the formula's sha)

# 8. mirror the formula into the tap repo (byte-identical), commit + push
cp Formula/tectdist.rb /opt/homebrew/Library/Taps/tmonk/homebrew-brew/Formula/tectdist.rb
```

## 3. Make `brew tap tmonk/brew` work

Done — the tap repo is `github.com/tmonk/homebrew-brew`, holding
`Formula/tectdist.rb` (a copy of the formula in this repo).  `brew tap
tmonk/brew` resolves to it; keep the two copies of the formula byte-identical
(sha256 included).

## 4. Create the GitHub release

Tag is annotated locally (step 5 above creates the release and its asset).
Use the `[x.y.z]` section of `CHANGELOG.md` as the body.  The formula sha256
pins the uploaded asset (step 7); never re-upload or move the tag afterwards
(the asset would no longer match).

## 4a. Biber provenance (built from source)

Since v0.2.0 the formula **builds biber from source** — the same approach as
homebrew-core's own `biber` formula:

| part | source | pinning |
|---|---|---|
| biber 2.17 | `https://github.com/plk/biber/archive/refs/tags/v2.17.tar.gz` | sha256 |
| 119 CPAN modules | metacpan (`cpan.metacpan.org`, the canonical CPAN host) | one sha256 per resource |

The CPAN resource set is the exact set homebrew-core's own `biber` formula
carries (proven to build in core CI on brew perl 5.42), with **Text::BibTeX
pinned to the 2.17-era 0.89** (≥ the 0.88 the Build.PL requires).  biber
2.17's `Build.PL` requires perl ≥ 5.32, so the formula depends on the brew
`perl` formula (macOS system perl is 5.30.3 on macOS ≤ 15) and stages every
module unconditionally — deterministic on all platforms.  The formula also
patches a missing semicolon in biber 2.17's `Biber/Section.pm`
(`del_everykeys`) that newer perls (5.36+) reject at compile time (upstream
fixed it in a later release).

The v0.1.0 binary biber assets on that release are **superseded** (kept as
history; the v0.2.0 release carries only the source tarball).

## 4b. Bumping the pairing (tectonic <-> biber)

Each tectdist release declares its pairing in `src/tectdist/pairing.py`
(`TECTONIC_VERSION`, `BIBER_VERSION`, `BIBLATEX_VERSION`, `BCF_VERSION`);
`Formula/tectdist.rb` mirrors `TECTONIC_VERSION`, and a release gate
(`tests/battery.py` + the weekly watcher) fails when the formula stops
mirroring the declaration.  The pairing is **enforced at runtime**: every
`tectdist` invocation compares the actual installed tectonic against the
declaration and fails fast with instructions when brew's tectonic moves;
`tectdist doctor` prints the full report.  (There is deliberately no
install-time dependency pinning — the runtime check + watcher + lockstep
releases carry the guarantee instead, which is what keeps the formula
homebrew-core-clean.)

The pairing chain:

| tectonic | bundled biblatex | .bcf format | biber |
| --- | --- | --- | --- |
| 0.17 | 3.17 | 3.8 | 2.17 |

**When to bump:** only when tectonic's bundled biblatex changes (i.e. brew's
tectonic moves to a new minor).  Never chase "latest biber" — biber 2.21
speaks .bcf 3.11 and aborts on the .bcf 3.8 that biblatex 3.17 writes.

**How you are told:** the weekly GitHub Actions watcher
(`.github/workflows/check-tectonic.yml`) compares brew's tectonic (parsed
from the homebrew-core formula) against `pairing.py`'s `TECTONIC_VERSION`,
also checks the formula mirrors it, and opens an issue ("tectonic moved to X
— biber/biblatex pairing needs a bump") the moment either diverges,
deduplicating while the previous issue is still open.  Manual runs:
`workflow_dispatch` on the Actions tab.

**Procedure (triggered by the watcher issue):**

1. Confirm the biblatex version bundled by the new tectonic (release notes /
   bundle listing) and pick the biber version matched to it (the table
   above; biber source tarballs are `plk/biber` GitHub tags — v2.17, v2.18,
   …).
2. Update `src/tectdist/pairing.py`: `TECTONIC_VERSION` and `BIBER_VERSION`
   (and `BIBLATEX_VERSION`/`BCF_VERSION` if they change).
3. Update `Formula/tectdist.rb`: the `TECTONIC_VERSION` constant and the
   biber resource URL/sha (the new `plk/biber` tag).  Adjust the CPAN
   resource pins **only if** the new biber's `Build.PL` requires newer
   minimums than the current pins: recompute from the Build.PL `requires`
   plus the transitive closure (start from homebrew-core's `biber` formula
   resource set, which tracks the current biber).  Keep the Section.pm
   inreplace only if the new release still has the bug.
4. Bump `src/tectdist/version.py` + `CHANGELOG.md`; run the release gate
   (the battery's pairing gate fails if formula and pairing.py diverge).
5. Release as one unit (§2), sync the tap, then close the watcher issue.

## 5. Post-release smoke test

```sh
brew tap tmonk/brew
brew install tmonk/brew/tectdist   # or: brew install tectdist
brew trust --formula tmonk/brew/tectdist   # only if trust is prompted
tectdist --version          # prints X.Y.Z
latexmk --version
tectdist doctor             # verdict: PAIR OK
biber --version             # the bundled version (e.g. 2.17)
```

Then run the project's own release gate (also CI-able):

```sh
python3 tests/battery.py        # ALL GREEN
python3 tests/check_formula.py
python3 tests/check_purity.py   # stdlib-only OK
```

## 6. homebrew-core draft (SUBMISSION-READY, NOT submitted)

A draft of the formula lives on branch `tectdist-0.2.0` of the fork
`github.com/tmonk/homebrew-core`, as `Formula/t/tectdist.rb`.  It is
**byte-identical to the canonical `Formula/tectdist.rb`** — there is exactly
one tectdist version, one formula, everything in it (source-built biber,
runtime pairing check, the lot; sha256 of all three copies:
`20505638...`) — and the `tmonk/brew` tap serves the same bytes.  **No PR
has been opened** (policy: tap-only for now).  The draft is FULLY READY:
opening the PR below is the only step left.

### 6.1. Audit state: ZERO findings

The v0.1.0 draft had two core-policy objections; the v0.2.0 redesign
eliminates both by construction, so the fork is clean:

* **No binary resource** — biber is built from source (119 CPAN source
  resources, the same set homebrew-core's own `biber` formula carries), so
  the "looks like a binary package; homebrew/core is source-only" audit
  finding is gone.
* **No install-time dependency pinning** — the formula declares
  `TECTONIC_VERSION` only as the release pairing constant; enforcement is
  the software's runtime check (`src/tectdist/pairing.py`), which is
  formula-DSL-free.

Verified on the fork: `brew style` 0 offenses, `brew audit --strict --new
--online` clean (exit 0, no problems), `brew install --build-from-source`
green, `brew test` green.

### 6.2. Review questions a maintainer will ask (with answers)

The formula is intentionally shaped the way it is; restate the evidence
rather than adapting to first-pass review:

* **"Why bundle biber instead of `depends_on "biber"`?"** — the version
  pairing: tectonic 0.17 bundles biblatex 3.17, which writes `.bcf` 3.8;
  homebrew-core's `biber` (2.21) speaks `.bcf` 3.11 and aborts on 3.8
  (empirically proven; biber is bumped in core on its own schedule).  A
  `depends_on "biber"` would make every tectdist install depend on a core
  package that can break the biblatex pipeline at any upgrade.  Building
  biber 2.17 in the formula keeps the matched pair as one release unit —
  the same reason core's own biber formula exists as a separate formula.
* **"Why `depends_on "perl"` instead of `uses_from_macos "perl"`?"** —
  biber 2.17's Build.PL requires perl ≥ 5.32; macOS system perl is 5.30.3
  on macOS ≤ 15 (5.34.1 on macOS 26/27) — a version-dependent source of
  truth.  Brew perl everywhere is deterministic, and the ~120-resource
  closure is the same set core's biber formula already carries on Linux.
* **"Why a TeX meta-distribution at all?"** — one command gives a complete
  TeX system (`brew install tmonk/brew/tectdist`): a single-file zipapp,
  the symlink farm of the standard TeX tool names, and a working biblatex
  stack.  All deps are pure core formulae (tectonic, python@3.14,
  ghostscript, poppler, qpdf, perl, libxml2, libxslt, openssl@3); the farm
  proxies poppler/qpdf/ghostscript tools without shadowing them.
* **"Why the runtime pairing check?"** — it is ordinary software behaviour
  (a version comparison at startup, like any tool checking its
  dependencies), not formula DSL pinning; it turns a silent biblatex
  breakage into a loud, actionable failure, and the weekly watcher +
  lockstep releases keep a matched version available.

### 6.3. Submission checklist (when green-lit)

1. Get maintainer buy-in in `#core` (Discord) for the formula — reference
   this section for the reasoning.
2. Refresh the branch from the canonical formula:
   `cp Formula/tectdist.rb <fork>/Formula/t/tectdist.rb`, commit, force-push
   `tectdist-0.2.0`.
3. Re-run the gate locally: `brew style`, `brew audit --strict --new
   --online`, `brew install --build-from-source`, `brew test` on the fork;
   expect ZERO findings.
4. Open the PR (template below).  Expect the review questions in 6.2;
   restate the evidence rather than adapting the formula.
5. If the PR is ever merged, keep the tap formula and the core formula
   byte-identical — same one version, no divergence.

### 6.4. PR template

```
gh pr create --repo Homebrew/homebrew-core \
  --head tmonk:tectdist-0.2.0 \
  --title "tectdist 0.2.0: Standard-TeX-compatible TeX distribution backed by Tectonic" \
  --body-file docs/core-pr-body.md
```

The body (`docs/core-pr-body.md`) states what the formula is (a single-file
Python zipapp plus a symlink farm of the standard TeX tools; the dispatcher
switches on the invoked name), what it depends on (pure-core formulae),
why biber 2.17 is built from source inside the formula (the pairing with
the biblatex 3.17 that tectonic 0.17 bundles; homebrew-core's biber 2.21 is
empirically incompatible), why perl is a hard dependency (biber 2.17 needs
perl ≥ 5.32; macOS system perl is 5.30.3 on macOS ≤ 15), and how it was
tested (acceptance battery, biblatex end-to-end through the installed farm,
brew style/audit/test on the fork).
