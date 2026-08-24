#!/usr/bin/env bash
# Profile-guided optimisation build across Rust + native engine code
# (plan X9.1): instrument -> train on a balanced corpus -> merge -> rebuild
# with profile use -> validate against held-out documents.
#
# Requirements:
#   - llvm-profdata and llvm-cov tools matching the rustc LLVM version.
#     Homebrew: brew install llvm  (then ensure its bin/ is first in PATH)
#   - a stable performance host for the training runs.
#
# Usage:
#   scripts/pgo_build.sh [--train-docs "tiny paper biblatex index"] \
#                        [--holdout-docs "thesis references"]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

TRAIN_DOCS=${TRAIN_DOCS:-"tiny paper biblatex index"}
HOLDOUT_DOCS=${HOLDOUT_DOCS:-"thesis references"}
PROF_DIR="$ROOT/target/pgo-data"
OUT_DIR="$ROOT/benchmark-results"
mkdir -p "$PROF_DIR" "$OUT_DIR"

if ! command -v llvm-profdata >/dev/null 2>&1; then
    echo "pgo: llvm-profdata not found; install LLVM toolchain matching rustc" >&2
    echo "pgo: e.g. brew install llvm && export PATH=\"\$(brew --prefix llvm)/bin:\$PATH\"" >&2
    exit 1
fi

echo "pgo: phase 1 - instrumented build"
export RUSTFLAGS="-Cprofile-generate=$PROF_DATA"
PROF_DATA="$PROF_DIR/default.profraw"
export RUSTFLAGS="-Cprofile-generate=$PROF_DIR"
cargo build --release --locked -p tectdist-cli
BIN="$ROOT/target/release/tectdist"

echo "pgo: phase 2 - training on: $TRAIN_DOCS"
for doc in $TRAIN_DOCS; do
    work="$(mktemp -d "/tmp/tectdist-pgo-$doc.XXXXXX")"
    cp "benchmarks/corpus/$doc/main.tex" "$work/" 2>/dev/null || {
        echo "pgo: no corpus document '$doc'; skipping" >&2
        continue
    }
    # Two runs exercise cold format load plus warm rerun paths.
    "$BIN" "$work/main.tex" >/dev/null 2>&1 || true
    "$BIN" "$work/main.tex" >/dev/null 2>&1 || true
    rm -rf "$work"
done

echo "pgo: phase 3 - merging profiles"
llvm-profdata merge -output="$PROF_DIR/merged.profdata" "$PROF_DIR"/*.profraw

echo "pgo: phase 4 - optimised rebuild"
unset RUSTFLAGS
RUSTFLAGS="-Cprofile-use=$PROF_DIR/merged.profdata" \
    cargo build --release --locked -p tectdist-cli
cp target/release/tectdist "/tmp/tectdist-pgo-optimized"

echo "pgo: phase 5 - validation on held-out docs: $HOLDOUT_DOCS"
for doc in $HOLDOUT_DOCS; do
    work="$(mktemp -d "/tmp/tectdist-pgo-hold-$doc.XXXXXX")"
    cp "benchmarks/corpus/$doc/main.tex" "$work/" 2>/dev/null || continue
    "$BIN" "$work/main.tex" >/dev/null 2>&1
    rm -rf "$work"
done

echo "pgo: benchmark the optimised binary and compare with:"
echo "  python -m benchmarks.runner.cli --candidate /tmp/tectdist-pgo-optimized \\"
echo "      --scenario warm-clean --trials 15 --warmups 3 \\"
echo "      --output $OUT_DIR/pgo-optimised.json"
