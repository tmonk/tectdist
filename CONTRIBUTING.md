# Contributing to tectdist

Thanks for helping!  tectdist is a small, focused project: a drop-in TeX Live
replacement backed by Tectonic.  Keep the scope tight and the behaviour
verifiable.

## Ground rules

- **No third-party dependencies.**  Everything (package, build, tools, tests)
  is Python 3 stdlib, compatible with stock `python3` ≥ 3.9 (macOS
  `/usr/bin/python3`).
- **No bash.**  The old bash dispatcher was rewritten into
  `src/tectdist/`; all new code is Python.
- **Drop-in behaviour is sacred.**  The web2c flag vocabulary and the
  exit-code/argv semantics are covered by the battery; do not change them
  without updating tests.
- **Tectonic is the only engine.**  New "engine" features mean new Tectonic
  behaviour, not a new backend.
- **License:** AGPL-3.0.  By contributing you agree your changes are licensed
  under it.

## Development setup

The dev environment is managed by [uv](https://docs.astral.sh/uv/) —
**dev-only**: the package, installers, battery and built artifact run on a
stock `python3` with no uv and no site-packages.

```sh
git clone <your-fork> tectdist && cd tectdist
uv sync                          # one-time: .venv with pytest + pytest-benchmark
uv run python make_links.py      # build the bin/ symlink farm
uv run python tests/battery.py   # run the full battery (needs tectonic; see below)
uv run pytest benchmarks/        # benchmark suite + zipapp purity audit
```

Runtime tools (`tectonic`, `ghostscript`, poppler, `qpdf`) are only needed for
the `[real]` tier.  Without them:

```sh
uv run python tests/battery.py --mock-only    # mock tier only; real sections SKIP
```

Performance work?  Measure before and after with the bench suite:

```sh
uv run pytest benchmarks/ --benchmark-only --benchmark-disable-gc \
    --benchmark-json=benchmarks/baseline.json   # before your change
uv run pytest benchmarks/ --benchmark-only --benchmark-disable-gc \
    --benchmark-json=benchmarks/after.json      # after; see BENCHMARKS.md
```

## Where things live

| File | What it is |
|---|---|
| `src/tectdist/flags.py` | the tool farm and web2c flag tables (single source of truth) |
| `src/tectdist/dispatcher.py` | argv[0] dispatch, engine resolution, flag translation |
| `src/tectdist/latexmk.py` | the latexmk-compatible driver |
| `src/tectdist/tools.py` | proxies, Ghostscript tools, stubs, kpsewhich |
| `src/tectdist/version.py` | `VERSION` — bump it with every release |
| `tests/battery.py` | the acceptance battery |
| `tests/check_purity.py` | zipapp import audit (stdlib-only promise) |
| `benchmarks/` | pytest-benchmark suite (+ `baseline.json` / `after.json`) |
| `pyproject.toml`, `uv.lock`, `.python-version` | the uv dev environment |
| `Formula/tectdist.rb` | the Homebrew formula (kept in sync with `flags.py`) |
| `build.py` | builds `dist/tectdist`, the single-file release artifact |

## Making changes

1. **Write the test first.**  Add a case to the matching section of
   `tests/battery.py` (`[mock]` for argv/flag mechanics, `[real]` for
   end-to-end behaviour).  A green run before your change is the contract.
2. **Change the code.**  Keep the module structure above; update
   `flags.py` when you add a tool name, and `Formula/tectdist.rb` when the
   farm changes (see the `FORMULA_FARM_NAMES` derivation in `flags.py`).
3. **Run the battery** until it is all green:
   ```sh
   python3 tests/battery.py
   ```
4. **Verify the release artifact** still builds and behaves:
   ```sh
   python3 build.py
   ./dist/tectdist --version
   ```
5. **Performance changes?** Measure before and after with the bench suite
   (`uv run pytest benchmarks/ --benchmark-only`; see BENCHMARKS.md) and note
   the deltas — the shim-overhead cases should not regress.
6. **Bump `VERSION`** in `src/tectdist/version.py` and add a CHANGELOG entry.

## Testing checklist

- `uv run python tests/battery.py` → `ALL GREEN` (with tectonic + gs + poppler)
- `python3 tests/battery.py` → `ALL GREEN` on a stock `python3` (no uv needed)
- `uv run python tests/battery.py --mock-only` → real sections `SKIP`, not fail
- `uv run python tests/battery.py --jobs 4` → same result
- `uv run pytest benchmarks/` → green (benchmarks + purity audit)
- `uv run python build.py` && `./dist/tectdist --version` → matches `version.py`
- `uv run python tests/check_purity.py` → `OK — stdlib-only`
- `uv run python -m py_compile src/tectdist/*.py` → clean
- `python3 -m py_compile src/tectdist/*.py` → clean on stock 3.9/3.14

## Submitting

- Keep commits small and conventional (`feat:`, `fix:`, `test:`, `docs:`).
- Reference the battery results in the PR description.
- If you touch the farm or the formula, mention it explicitly.

## Releasing (maintainers)

1. Bump `VERSION` in `src/tectdist/version.py`.
2. Update `CHANGELOG.md` (new section at the top).
3. Update the `url`/`sha256` in `Formula/tectdist.rb` to the new tag tarball.
4. Tag `v<VERSION>` and push.  Publish the tag's source tarball where the
   formula points.
