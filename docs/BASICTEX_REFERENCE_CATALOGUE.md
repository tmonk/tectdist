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
| 1 | `crates/tectdist-core/src/runtime.rs` | `TECTDIST_BASICTEX_ROOT` (7) | The single centralised runtime-root resolver (`detect_runtime_pack_source`): prefers `TECTDIST_RUNTIME_ROOT`, accepts the legacy oracle-image root during the M1 transition only. All supervisor/CLI resolution flows through it — their own direct reads were removed in the first M1 increment. | Removed at M1/PACK-008–009: the legacy fallback arm is deleted, leaving `TECTDIST_RUNTIME_ROOT` as the only production variable; oracle execution remains behind the `oracle-tools` feature (`OracleRunner`) |

History: at M0 this table baselined scattered direct reads in
`tectdist-cli/src/main.rs` (3) and `tectdist-supervisor/src/main.rs` (4);
both dropped to zero when resolution was consolidated.

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
