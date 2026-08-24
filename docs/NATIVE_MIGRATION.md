# Native migration status

The Rust workspace contains the Phase B and Phase C implementation. Native
builds enable the embedded Tectonic executor by default; `--no-default-features`
produces the Phase B external-only diagnostic build. The Python implementation
remains in-tree as the differential reference during qualification.

`EmbeddedTectonicExecutor` uses the pinned Tectonic `ProcessingSessionBuilder`
for the default native path. It maps the primary input, output directory,
format/cache, SyncTeX, retained diagnostics, and job-name post-processing.
Explicit search paths map to the driver's opt-in extra-path API. Shell escape
remains disabled by default and is enabled only by a compatible shell-escape
flag, through Tectonic's security settings; `TECTONIC_UNTRUSTED_MODE` still
overrides and disables insecure features. Unknown `-Z` settings fail rather
than being silently ignored. The external executor remains the tested
diagnostic fallback.

Both native compile modes expose the declared Tectonic/Biber pairing in
`tectdist doctor --json`, together with `TECTDIST_BUNDLE_ID` and
`TECTDIST_FORMAT_CACHE_ID` when qualification invokes the binary. Qualification
also records the explicit bundle source and manifest hash. The external mode checks the configured Tectonic
minor version before compilation and caches the result by executable identity;
`TECTDIST_SKIP_PAIRING=1` remains available for controlled test fixtures.

Embedded index and glossary runs use generated-artifact events (`.idx` or
`.glo`) instead of scanning the output directory. Their real external tool is
bounded by `TECTDIST_EXTERNAL_TOOL_TIMEOUT_SECS` (or the millisecond test
override) and failures propagate as compiler failures. The source installer
builds the SHA-256-pinned upstream MakeIndex 2.12 source (about 522 KB) into the
native farm, avoiding a TeX Live dependency and never substituting a stub for
an index-required build.

`tectdist warm` is a one-shot cache seed: it compiles a private minimal
document into a temporary directory, then removes that directory. It warms
only normal Tectonic dependency caches; it does not retain document outputs,
run a daemon, or create a tectdist incremental cache.

Build the default embedded candidate with the pinned Rust dependency lock.
On macOS, `build.py` discovers Homebrew's keg-only Tectonic dependencies and
sets their pkg-config paths automatically:

```sh
python3 build.py --native --output target/release/tectdist
TECTDIST_NATIVE=target/release/tectdist python3 tests/differential.py
```

Build the external-only fallback with `python3 build.py --native
--no-embedded --output target/release/tectdist-external`.

This branch does not publish the native binary or modify the Homebrew formula
until those gates are satisfied.
