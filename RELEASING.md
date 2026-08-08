# Releasing

The release is prepared locally (annotated tag `v0.1.0` at HEAD; the git
history is a single squashed `release: v0.1.0` commit), but pushing to
GitHub and publishing to Homebrew are manual steps done by a maintainer
with push access.

The remote repo still carries the superseded pre-release history and the old
`v0.1.0`/`v0.1.1` tags (pointing at commits that predate the single-release
squash — the old `v0.1.1` tarball even contains the internal review doc that
was purged).  This release replaces all of it.

Backups of the superseded history (not in the repo):

```sh
/tmp/tectdist-pre-rewrite.bundle
/tmp/tectdist-pre-squash.bundle
```

## 1. Replace the remote history and tags

```sh
git push --force-with-lease origin main
git push origin :refs/tags/v0.1.0 :refs/tags/v0.1.1   # drop the stale tags
git push origin v0.1.0 --force
```

> Anyone who installed from a pre-release tarball and reinstalls later hits
> a sha256 mismatch; the formula only references `v0.1.0`, so this only
> affects pinned historical installs.

## 2. Fill the formula sha256 (cannot be precomputed)

GitHub's codeload tarballs are **not byte-reproducible** from a local
`git archive` (gzip settings differ), so the sha256 in
`Formula/tectdist.rb` is a placeholder.  After pushing the tag:

```sh
curl -sL https://github.com/tmonk/tectdist/archive/refs/tags/v0.1.0.tar.gz | shasum -a 256
```

Paste the result into `Formula/tectdist.rb`, commit, push, and re-tag if
the tag itself was already pushed (`git tag -f -a v0.1.0 -m "tectdist 0.1.0"`
and force-push the tag again).  Verify with:

```sh
brew audit --strict Formula/tectdist.rb
brew install --build-from-source --formula Formula/tectdist.rb
brew test --formula tectdist
```

## 3. Make `brew tap tmonk/tectdist` work

`brew tap tmonk/tectdist` resolves to the GitHub repo
`github.com/tmonk/homebrew-tectdist` (taps are `homebrew-<name>` repos).
Either:

- rename this repo to `homebrew-tectdist` (simplest if the tap is the only
  public home of the formula), **or**
- host the formula in a separate `tmonk/homebrew-tectdist` repo.

Until one of those exists, users can tap with an explicit URL:

```sh
brew tap tmonk/tectdist https://github.com/tmonk/tectdist.git
brew install tmonk/tectdist/tectdist
```

## 4. Create the GitHub release

Tag `v0.1.0` is annotated locally.  On GitHub create a release from it, with
the `[0.1.0]` section of `CHANGELOG.md` as the body.  The source tarball is
generated automatically from the tag; the formula sha256 in step 2 must match
it.

## 5. Post-release smoke test

```sh
brew tap tmonk/tectdist
brew install tmonk/tectdist/tectdist
tectdist --version          # prints 0.1.0
latexmk --version
```

Then run the project's own release gate (also CI-able):

```sh
python3 tests/battery.py        # ALL GREEN
python3 tests/check_purity.py   # stdlib-only OK
```
