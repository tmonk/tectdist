# Convergence digest and I/O strategy (plan workstream X4)

## What is already in place

- **Negative-open cache** (`tectdist-engine` `EngineContext`): an immutable
  bundle answers NotAvailable for a given name for the whole process
  lifetime. Rerun passes re-probe many of these names; the shared context now
  serves repeat misses from one hash lookup instead of full bundle
  resolution. Hit/miss/error counts remain visible through the
  `engine.io.bundle_reads` event so profiles keep attributing I/O time.
- **Bundle-read observability**: every context-bundle open is timed and
  counted (plan X1.2/X4.4 counters), giving the profile evidence required
  before any further I/O optimisation lands.
- **Adversarial mutation corpus** (`tests/mutation_corpus.py`): verifies at
  product level that rerun decisions stay correct under same-size/same-mtime
  edits, included-file edits, and bibliography edits — all pass. (`tests/mutation_corpus.py`): verifies at
  product level that rerun decisions stay correct under same-size/same-mtime
  edits, included-file edits, and bibliography edits — the failure modes a
  fast-digest design must never introduce. Run:
  `python3 tests/mutation_corpus.py --native <binary>`.

## Digest redesign (X4.1/X4.2) — requires the engine patch series

In-session rerun equality digests are computed inside Tectonic's driver and
I/O bridge (`dep_support`, `io_base`, bridge state). Swapping SHA-256 for
BLAKE3/XXH3-128 plus length-tagged records therefore belongs to the
upstreamable patch series tracked by plan item X10-045 rather than a wrapper
change. Design constraints already fixed here:

1. Bundle/package integrity hashes stay cryptographic; only *in-session
   circular-file equality* (`.aux`, `.toc`, `.out`, `.bcf`) may use the fast
   digest.
2. Every equality record includes file length; small files optionally fall
   back to byte comparison.
3. Only circular and stage-dependency files carry convergence digests;
   immutable bundle resources are exempt.
4. Acceptance = the mutation corpus above passes unchanged, plus identical
   rerun decisions across the differential battery.

The vendored-engine fork needed for this patch is deliberately deferred
until Milestone 6's bibliography work forces the same decision (see
docs/ENGINE_PIN.md).
