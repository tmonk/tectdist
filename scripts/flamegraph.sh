#!/usr/bin/env bash
# Automated per-document flamegraphs for the native candidate (plan X1.3).
#
# Produces collapsed stacks and a flamegraph SVG (or an Instruments trace on
# macOS when cargo-flamegraph/dtrace are unavailable) for mandatory profile
# documents. Profiles are stored beside benchmark artifacts.
#
# Usage:
#   scripts/flamegraph.sh [DOCUMENT ...]     # default: tiny paper biblatex index
#
# Requirements (best effort, graceful degradation):
#   - cargo-flamegraph (Linux: perf; macOS: dtrace, often needs sudo)
#   - macOS fallback: /usr/bin/sample (always available)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/benchmark-results/profiles"
mkdir -p "$OUT"

DOCUMENTS=("$@")
[ ${#DOCUMENTS[@]} -eq 0 ] && DOCUMENTS=(tiny paper biblatex index)

cd "$ROOT"
cargo build --release --locked
BIN="$ROOT/target/release/tectdist"

for doc in "${DOCUMENTS[@]}"; do
    src="$ROOT/benchmarks/corpus/$doc/main.tex"
    if [ ! -f "$src" ]; then
        echo "flamegraph: no corpus document '$doc'; skipping" >&2
        continue
    fi
    work="$(mktemp -d "/tmp/tectdist-profile-$doc.XXXXXX")"
    cp "$src" "$work/"
    echo "flamegraph: profiling $doc in $work"
    if command -v flamegraph >/dev/null 2>&1; then
        flamegraph -o "$OUT/$doc.svg" -- "$BIN" "$work/main.tex" \
            && echo "flamegraph: wrote $OUT/$doc.svg"
    else
        # macOS 'sample' produces a collapsible call-tree text profile.
        "$BIN" "$work/main.tex" >/dev/null 2>&1 || true
        pidfile="$work/.pid"
        "$BIN" "$work/main.tex" >/dev/null 2>&1 &
        pid=$!
        sample "$pid" 10 -file "$OUT/$doc.calltree.txt" 2>/dev/null || true
        wait "$pid" || true
        [ -f "$OUT/$doc.calltree.txt" ] \
            && echo "flamegraph: wrote $OUT/$doc.calltree.txt (install cargo-flamegraph for SVGs)"
    fi
    rm -rf "$work"
done

echo "flamegraph: profiles stored under $OUT"
