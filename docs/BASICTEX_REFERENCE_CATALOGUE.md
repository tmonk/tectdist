# BasicTeX production-reference catalogue (O100-002)

**Status:** maintained per `docs/BASICTEX_X10_PLAN.md` M0.
This file inventories every production reference to BasicTeX paths,
environment variables, or fallback execution, with its planned disposition.

The machine-enforced gate is
`crates/tectdist-core/tests/architecture_basic_tex_independence.rs`:
it fails CI on any NEW production reference and on growth of any baselined
count. Test code (`crates/*/tests/`, benches) and oracle tooling built with
`cfg(feature = "oracle-tools")` are exempt by design.

## Runtime-independence contract (plan §7)

Production must contain **zero** references to:

- BasicTeX installer / expanded payload paths;
- `TECTDIST_BASICTEX_ROOT`;
- `/usr/local/texlive/*basic` or similar system TeX roots;
- any code path that executes a BasicTeX binary as a runtime fallback.

## Baseline violations pending removal

| # | Location | Pattern | Purpose today | Disposition |
|---|---|---|---|---|
| 1 | `crates/tectdist-cli/src/main.rs` | `TECTDIST_BASICTEX_ROOT` (3) | Resolves the pinned BasicTeX image to execute exact one-shot compiles for the `basictex-2026` profile | Removed at M1/PACK-008: exact lane resolves tools from `RuntimePack` via `TECTDIST_RUNTIME_ROOT`; `OracleRunner` moves behind test-only feature |
| 2 | `crates/tectdist-supervisor/src/main.rs` | `TECTDIST_BASICTEX_ROOT` (4) | Supervisor-side resolution of BasicTeX image binaries/formats for exact execution and fork-server workers | Removed at M1/PACK-008–009: supervisor consumes only tectdist-owned runtime packs; BasicTeX execution becomes oracle-test-only |

No other production references exist. No production code links against
Kpathsea from a system TeX; no committed binaries remain in source history
(removed in M0/O100-004).

## Verification commands

```sh
cargo test -p tectdist-core --test architecture_basic_tex_independence
grep -rn "TECTDIST_BASICTEX_ROOT" crates/*/src   # must match baseline only
```

At M1 closure this table must be deleted and the baseline array emptied so
the gate enforces zero unconditionally.
