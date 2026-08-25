# BT100/X10 Programme Status

**Date:** 2026-08-24
**Branch:** `perf`
**Head:** `66bcdfd` (+ uncommitted docs)

## Executive Summary

Substantial progress establishing the BasicTeX-compatible acceleration architecture.
4/10 milestones formally complete; remaining work requires web2c/tex.web source
modifications documented in `docs/FORK_SERVER_DESIGN.md`.

## Milestone status

| milestone | status | key evidence |
|---|---|---|
| **B0** Contract reset | ✅ complete | BasicTeX pinned, manifests generated, budgets frozen |
| **B1** Substrate | ✅ complete | Image verified (19,935 files), size gate PASS, pipelines 7/7 |
| **B2** Compatibility factory | ~92% | **accelerated-chain exactness proven**: 26/26 pairs green through the live supervisor (cold X2 + warm X4 replay), page counts identical to reference | Ledger 372 rows, smoke 192/192 pass, interactions 507/507 ref-green pass, **all ref-failures attributed (0 pair-specific)**, probes: 209 packages → 161 pass / 48 reference-blocked, report gate PASS |
| **X1** Supervisor + fork servers | ~65% | IPC+locks ✓, pdfTeX fork server proven (1.5 ms children), launch-variant matrix mapped, -fmt bypass root-caused |
| **X2** Preamble snapshots | ~85% | Builder validated end-to-end (paired-body contract, 2.1x A/B), hyph_size root-caused (TEXMFCNF override), supervisor fast path live with IPC test; measured through supervisor: body edit 156->67 ms (2.33x), rebuild 273 ms |
| **X3** Helper acceleration | ✅ complete | Broker MVP done, 5/5 helpers < 2 ms gates, mutation corpus passes |
| **X4** Checkpoints/replay | ~65% | Model ✓, chains ✓, manifest ✓, aux tracker ✓, **unchanged-rebuild gate live: 12 ms vs 152 ms stock (12.7x)**; page-level engine API pending |
| **X5** Output graphs | model ✓ | Graph model ✓, planner ✓, content store ✓; execution pending engine patches |
| **X6** Runtime-warm clean | not started | Needs X4/X5 completion first |
| **R** Release qualification | queued | All prior gates |

## Key measurements

| metric | value | gate |
|---|---|---|
| Tiny one-pager (one-shot) | 128.0 ms | vs frozen 5.1 ms budget (needs fork server) |
| Index document | 175.4 ms | −48% vs audited baseline |
| Fork child creation | 1.5 ms p50 | < 2 ms gate PASS |
| Action restore (bibtex) | 0.55 ms p50 | < 2 ms gate PASS |
| Interaction coverage | 507+218 ref-green / 0 fail | CLI battery + supervisor-path battery |
| Supervisor chain (warm body edit) | 67 ms vs 152 ms stock | 2.3x via project format |
| Supervisor chain (unchanged rebuild) | 12 ms vs 152 ms stock | 12.7x via X4 gate |
| Pipeline qualification | 7/7 | direct PDF through tex4ht |

## Crates delivered

| crate | purpose |
|---|---|
| `tectdist-supervisor` | IPC server, locks, action broker, checkpoint chains, output graph, rebuild cache, aux tracker |
| `tectdist-makeindex` | Embedded MakeIndex 2.12 from pinned C source |
| `tectdist-bib` | BIB parser, numeric emitter, capability gate |
| `tectdist-cli` | EngineContext reuse, retention policies, profile mode |

## Scripts delivered (14 tools)

basictex_image, basictex_reference, basictex_corpus, basictex_baseline,
basictex_interactions, basictex_pipelines, basictex_overlay,
basictex_project_format, basictex_actions_bench, basictex_smoke,
basictex_ledger, basictex_report, basictex_reffail_standalone,
basictex_reffail_classify, forkserver_apply_patch, tectonic_perf_matrix

## Design documents

| document | content |
|---|---|
| FORK_SERVER_DESIGN.md | Engine patch points, COW forking, protocol, launch variants |
| DIGEST_STRATEGY.md | Convergence digest design, mutation corpus results |
| ENGINE_PIN.md | Tectonic revision matrix, pin evidence, TEXFORMATS recipe |

## Remaining blockers

All remaining runtime acceleration requires `.ch` change files against
tex.web/pdftex.web:

1. Begin-document hook placement on ALL format-load paths (currently
   first-line &reference only; `-fmt=` preload bypasses general-init region)
2. Page-level checkpoint serialization inside engines
3. Shell-escape dependency capture inside engines
4. Runtime-warm clean acceleration (tokenised caches, hot-loop patches)

These require a developer with web2c/tex.web expertise working in an editor
with full TL source context. All scaffolding, protocol models, measurement
infrastructure, and test suites are designed to accept those patches when
implemented.
