//! Unchanged-rebuild cache (X10-E scenario 1, plan §12).
//!
//! Detects when all project input files are unchanged since the last
//! successful build and a valid output PDF exists. Uses SHA-256 content
//! hashing only — never mtime (plan §12: metadata is only a cheap filter).

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::Mutex;

/// A cached build: output file digest + input file digests.
#[derive(Debug, Clone)]
pub struct CachedBuild {
    pub output_digest: String,
    pub inputs: Vec<(String, String)>,
}

/// Content-addressed unchanged-rebuild cache.
pub struct RebuildCache {
    inner: Mutex<HashMap<String, CachedBuild>>,
}

impl RebuildCache {
    pub fn new() -> Self {
        Self { inner: Mutex::new(HashMap::new()) }
    }

    fn key(cwd: &Path, jobname: &str) -> String {
        let canonical = cwd.canonicalize().unwrap_or_else(|_| cwd.to_path_buf());
        format!("{}#{}", canonical.display(), jobname)
    }

    /// Compute SHA-256 content digest of a file.
    pub fn file_digest(path: &Path) -> Option<String> {
        let bytes = std::fs::read(path).ok()?;
        Some(sha256_hex(&bytes))
    }

    /// Snapshot all TeX-relevant input files in `dir`.
    pub fn snapshot_inputs(dir: &Path) -> Vec<(String, String)> {
        let mut entries = Vec::new();
        if let Ok(readings) = std::fs::read_dir(dir) {
            let mut paths: Vec<_> = readings.flatten()
                .map(|e| e.path())
                .filter(|p| p.is_file())
                .filter(|p| matches!(
                    p.extension().and_then(|e| e.to_str()),
                    Some("tex") | Some("bib") | Some("ist") | Some("cls") | Some("sty")
                ))
                .collect();
            paths.sort();
            for path in paths {
                let name = path.file_name()
                    .map(|n| n.to_string_lossy().into_owned())
                    .unwrap_or_default();
                if let Some(digest) = Self::file_digest(&path) {
                    entries.push((name, digest));
                }
            }
        }
        entries
    }

    /// Check whether the cached PDF is valid for the current input set.
    /// Returns Some(pdf_path) on a verified hit.
    pub fn check_unchanged(
        cache: &Mutex<HashMap<String, CachedBuild>>,
        cwd: &Path,
        jobname: &str,
    ) -> Option<PathBuf> {
        let pdf_path = cwd.join(format!("{jobname}.pdf"));
        let pdf_bytes = std::fs::read(&pdf_path).ok()?;
        let output_digest = sha256_hex(&pdf_bytes);

        let cache = cache.lock().ok()?;
        let entry = cache.get(&Self::key(cwd, jobname))?;

        // Verify output digest.
        if entry.output_digest != output_digest { return None; }

        // Verify all input digests match.
        for (name, old_digest) in &entry.inputs {
            let current = Path::new(cwd).join(name);
            let bytes = std::fs::read(&current).ok()?;
            let current_digest = sha256_hex(&bytes);
            if current_digest != *old_digest { return None; }
        }
        Some(pdf_path)
    }

    /// Record a successful build's input/output digests.
    pub fn record_build(
        cache: &Mutex<HashMap<String, CachedBuild>>,
        cwd: &Path,
        jobname: &str,
    ) {
        let inputs = Self::snapshot_inputs(cwd);
        let pdf_path = cwd.join(format!("{jobname}.pdf"));
        let output_digest = match std::fs::read(&pdf_path) {
            Ok(bytes) => sha256_hex(&bytes),
            Err(_) => return,
        };
        let key = Self::key(cwd, jobname);
        if let Ok(mut cache) = cache.lock() {
            cache.insert(key, CachedBuild { output_digest, inputs });
        }
    }
}

fn sha256_hex(bytes: &[u8]) -> String {
    use sha2::{Digest, Sha256};
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    format!("{:x}", hasher.finalize())
}
