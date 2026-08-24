# Exact-engine fork servers — implementation design (plan X1/X10-102..106)

This note fixes the concrete engineering approach for pdfTeX/XeTeX/LuaTeX
fork servers before any engine patch is written.

## Why fork servers

Paired measurements (see `reference/basictex-2026/baseline-denominators*.json`)
show the exact-engine profile mode runs within ~6–15% of raw BasicTeX today;
the residual is per-invocation process creation, dynamic loading, and format
load. A resident engine process that forks copy-on-write children removes
that residual. Preamble snapshots then remove class/package initialisation
(X2). Neither can be built above the wrapper layer: they require hooks inside
each engine's execution loop.

## Engine acquisition

Patch series against the TeX Live 2026 source tree
(`git://tug.org/texlive/trunk/Build/source`, revision frozen alongside the
BasicTeX image). One patch per concern, upstreamable individually:

1. `forkserver-entry`: a `-fork-server` option for texmfmp-based engines.
   After `main()` finishes engine initialisation (format loaded, Kpathsea
   configured), instead of running `\job`, enter server mode.
2. `begin-document pause` (X2): an engine hook invoked after
   `\AtBeginDocument` hooks and before consuming the first body token,
   exposing "pause here" through a special token/flag settable from the
   server protocol.
3. `checkpoint export/import` (X4): serialise/deserialise the full live
   state listed in plan §6.5 behind one API per engine.

pdfTeX first (simplest backend, no font machinery beyond Type1/OTF loading),
then XeTeX (extra fontconfig/graphite2/harfbuzz state), then LuaHBTeX
(embedded Lua runtime state).

## Fork safety checklist (per engine, from plan §9.2)

- Initialise strictly single-threaded; defer zlib/fontconfig background
  work past the fork point or disable it (`pthread_atfork` prepare handlers
  to drain/lock).
- Record all open file descriptors with offsets in the safety manifest;
  children reopen anything marked reopen-on-fork.
- Children never return to the server loop: on completion (or error) they
  `_exit()` with the job status.
- Server side never touches job-specific memory; crash of a child must not
  corrupt the parent (COW guarantees this if no fd/state aliasing leaks).
- Sanitizer (ASan/UBSan) builds of the server must survive the full BT100
  smoke corpus without reports.

## Protocol additions (supervisor ↔ engine server)

```
EngineServerRequest:
  Compile { argv, cwd, env_overlay, snapshot_key? }
  PauseAtBeginDocument { enable }
  Shutdown
EngineServerResponse:
  Ready { engine_identity, format_digest }
  CompileDone { exit_status, duration_ms, artifacts[], state_digest }
```

Transport: private socketpair inherited across fork; JSON framing identical
to the client↔supervisor protocol.

## Performance gates measured on this host

| gate | target |
|---|---|
| format-loaded fork child, first byte of TeX execution | < 2 ms p50 |
| preamble-snapshot child | < 3 ms p50 |
| tiny edit-to-PDF via server | ≤ 5.1 ms (frozen X10 budget) |

Measurement harness: `scripts/forkserver_bench.py` (lands with the first
server), reporting p50/p95 over ≥100 children with warm caches.

## Status

- [x] Design recorded (this document)
- [x] Supervisor-side registry/LRU scaffold (tectdist-supervisor 0.2.x)
- [x] TeX Live source pinned: texlive-20260301-source.tar.xz
      (sha512 7b244504…bbde, see reference/texlive-source/)
- [x] pdfTeX `forkserver-entry` patch prototype — build-tree variant;
      production `.ch` change file is follow-up
- [x] Child-creation latency measured: **1.5 ms p50 (< 2 ms gate PASS)**;
      end-to-end fork-child one-pager 18.8 ms vs 37.6 ms cold = 2.0×
      (see reference/basictex-2026/forkserver-measurement.json)
