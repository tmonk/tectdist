//! Architecture gate: production code must not depend on BasicTeX (O100-003).
//!
//! `docs/BASICTEX_X10_PLAN.md` §7 (runtime independence) and milestone M0
//! require that production tectdist neither discovers, executes, links
//! against, nor falls back to an installed BasicTeX distribution. BasicTeX
//! is an oracle only, referenced solely by test/oracle tooling.
//!
//! This test scans all production source files for forbidden patterns and
//! compares them against an explicit, reviewed baseline. The baseline exists
//! only because the M1 oracle/runtime split (PACK-008/PACK-009) has not
//! landed yet; every entry documents its planned removal. Adding a NEW
//! reference, or growing a baselined one, fails this gate.
//!
//! At M1 closure the baseline must be emptied.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

/// Patterns that indicate a production dependency on the BasicTeX oracle.
const FORBIDDEN: &[&str] = &[
    "TECTDIST_BASICTEX_ROOT",
    "basictex-2026/image",
    "/usr/local/texlive",
];

/// Reviewed baseline of known violations pending the M1 split.
/// (file, pattern, current count). Never grow; only shrink.
///
/// History: M0 baselined scattered reads in tectdist-cli/main.rs (3) and
/// tectdist-supervisor/main.rs (4); the first M1 increment consolidated all
/// resolution into tectdist-core/src/runtime.rs behind the shared resolver,
/// so those two entries dropped to zero and a single centralised entry
/// remains until PACK-008/PACK-009 remove the legacy fallback entirely.
const BASELINE: &[(&str, &str, usize)] = &[
    // Centralised transition resolver (TECTDIST_RUNTIME_ROOT preferred,
    // legacy oracle-image root accepted during M1 only).
    (
        "crates/tectdist-core/src/runtime.rs",
        "TECTDIST_BASICTEX_ROOT",
        7,
    ),
];

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(2)
        .expect("crate two levels below repo root")
        .to_path_buf()
}

fn collect_violations(root: &Path) -> BTreeMap<(String, String), usize> {
    let mut found: BTreeMap<(String, String), usize> = BTreeMap::new();
    let crates_dir = root.join("crates");
    let mut stack = vec![crates_dir];
    while let Some(dir) = stack.pop() {
        for entry in std::fs::read_dir(&dir).expect("read crates dir") {
            let path = entry.expect("dir entry").path();
            let name = path.file_name().and_then(|n| n.to_str());
            if path.is_dir() {
                // tests/ and benches/ are test-oracle territory, allowed.
                if name == Some("tests") || name == Some("benches") {
                    continue;
                }
                stack.push(path);
            } else if path.extension().and_then(|e| e.to_str()) == Some("rs")
            {
                let body =
                    std::fs::read_to_string(&path).unwrap_or_default();
                let rel = path
                    .strip_prefix(root)
                    .expect("under root")
                    .to_string_lossy()
                    .to_string();
                for pattern in FORBIDDEN {
                    let count =
                        body.matches(pattern).count();
                    if count > 0 {
                        *found
                            .entry((rel.clone(), pattern.to_string()))
                            .or_insert(0) += count;
                    }
                }
            }
        }
    }
    found
}

#[test]
fn no_new_production_basictex_dependencies() {
    let root = repo_root();
    let found = collect_violations(&root);

    let mut failures: Vec<String> = Vec::new();

    // 1. Baseline counts may only shrink.
    for (file, pattern, allowed) in BASELINE {
        let actual = found
            .get(&((*file).to_string(), (*pattern).to_string()))
            .copied()
            .unwrap_or(0);
        if actual > *allowed {
            failures.push(format!(
                "{file}: {actual} occurrences of {pattern} exceed \
                 reviewed baseline {allowed}"
            ));
        }
    }

    // 2. Any violation not in the baseline is new and forbidden.
    for ((file, pattern), count) in &found {
        let baselined = BASELINE.iter().any(|(f, p, _)| f == file && p == pattern);
        if !baselined {
            failures.push(format!(
                "NEW production BasicTeX dependency: {file} contains \
                 {count} occurrence(s) of {pattern}. Production code must \
                 not depend on the BasicTeX oracle \
                 (docs/BASICTEX_X10_PLAN.md §7). If this is oracle/test \
                 tooling, place it behind cfg(feature = \"oracle-tools\") \
                 or under tests/."
            ));
        }
    }

    assert!(
        failures.is_empty(),
        "BasicTeX runtime-independence gate failed:\n{}",
        failures.join("\n")
    );
}
