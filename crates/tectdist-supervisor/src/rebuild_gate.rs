//! Unchanged-rebuild gate (plan X4, X10-E scenario 1).
//!
//! When every project input file has the same content digest as the last
//! successful build AND the output PDF is still present, skip the engine
//! entirely and replay the cached success. Content hashes only — never
//! mtime (plan §12). Exact engines are deterministic, so identical inputs
//! reproduce identical outputs; BT100 semantics are preserved because a
//! fresh engine run would produce the same result.
//!
//! The comparison set is the checkpoint chain recorded by the Compile
//! handler after every successful build ("<cwd>#<jobname>").

use std::collections::BTreeMap;
use std::path::Path;
use std::time::Instant;

use crate::checkpoint::CheckpointChain;
use crate::SupervisorState;

// NOTE on scope: the gate deliberately compares EVERY file in the project
// tree, not an extension whitelist. Anything readable by the engine can be
// an input — \input accepts arbitrary extensions, shell-escape scripts may
// generate data files, and bibtex rewrites .bbl between engine runs. A
// whitelist would produce false cache hits for exactly those cases.
// Including artifacts is safe: they only change during a real compile,
// which immediately re-records the chain; a cache-hit replay touches
// nothing, so equality persists.

/// Attempt to serve this compile from the unchanged-rebuild cache.
///
/// Returns Some((exit_status, duration_ms)) on a cache hit; None means
/// proceed with the normal compile chain (no cache or any mismatch).
pub fn try_cached(state: &SupervisorState, cwd: &Path, argv: &[String]) -> Option<(i32, u64)> {
    let started = Instant::now();
    let jobname = crate::derive_job_name(argv, cwd);
    let key = format!("{}#{}", cwd.display(), jobname);
    let chain: CheckpointChain = state.checkpoint_chain_get(&key)?;

    // Current input snapshot filtered to source files; outputs and logs
    // must not influence the decision. The snapshot is recursive and keyed
    // by relative path so \input'ed subdirectory files invalidate too;
    // None (tree unprovable) means a real compile.
    let files = crate::snapshot_project_tree(cwd)?;
    let current: BTreeMap<String, String> = files.into_iter().collect();
    if current.is_empty() {
        return None;
    }

    // Recorded inputs from the last successful build.
    let mut recorded: BTreeMap<String, String> = BTreeMap::new();
    for record in &chain.records {
        if let Some(name) = record.shipped_pages.first() {
            recorded.insert(name.clone(), record.dependency_epoch.clone());
        }
    }
    if recorded.is_empty() || current != recorded {
        return None;
    }

    // The output must still exist; otherwise the cache is stale.
    let pdf_stem = Path::new(&jobname)
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("main");
    if !cwd.join(format!("{pdf_stem}.pdf")).is_file() {
        return None;
    }

    Some((0, started.elapsed().as_millis() as u64))
}
