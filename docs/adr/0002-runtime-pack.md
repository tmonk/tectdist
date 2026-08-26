# ADR 0002: Tectdist-owned runtime pack replaces BasicTeX image reuse

- **Status:** Accepted
- **Date:** 2026-08-26
- **Plan reference:** `docs/BASICTEX_X10_PLAN.md` §0.1, §3.1, §15; milestones M0/M2

## Context

The previous design treated an extracted BasicTeX tree as both the oracle
and the production compatibility fallback. That violates the runtime
independence contract (plan §7), bloats deployment beyond the footprint
budget (§8), and makes production behaviour depend on a separately
installed distribution.

## Decision

Production tectdist ships a **tectdist-owned runtime pack** assembled
independently of any installed distribution:

- scope derived from the oracle TLPDB's installed run-file/font/format
  closure (oracle decides *what* is in scope, never *where files come
  from*);
- every file fetched from pinned upstream sources and verified against
  the oracle file manifest digests;
- deterministic seekable signed shards partitioned by access class
  (bootstrap, engines, packages, fonts, tools);
- lazy materialisation with signed manifests, plus a complete offline
  pack;
- SBOM/licence/provenance emitted per release.

BasicTeX remains exclusively on the comparator side of qualification.

## Footprint budgets (initial, plan §8)

| Component | Compressed budget |
|---|---|
| CLI + supervisor + metadata | <= 8 MiB |
| shared AOT engine code | <= 35 MiB |
| always-present bootstrap | <= 20 MiB |
| typical first-project active set | <= 50 MiB |
| complete offline pack | <= 120 MiB |

Budgets change only through a recorded architecture decision.

## Consequences

- `TECTDIST_RUNTIME_ROOT` supersedes `TECTDIST_BASICTEX_ROOT` in
  production code (removal tracked in
  `docs/BASICTEX_REFERENCE_CATALOGUE.md`).
- Repository hygiene (O100-004): no expanded installer payloads, engine
  binaries, or generated formats in Git; CI/release storage holds
  artefacts.
- The installer must function on hosts with no TeX installation of any
  kind; CI proves operation with all system TeX hidden (PACK-009).
- Missing-shard cold failures are explicit errors, never silent network
  fetches in offline mode.

## Maintenance owner

Pack tooling owner (M2). Shard layout and budgets re-examined at each
release qualification.
