//! Runtime pack and exact-lane abstraction (plan M1, Part XI steps 3–4).
//!
//! `docs/BASICTEX_X10_PLAN.md` requires a split between:
//!
//! * the **exact lane** — tectdist-owned tools resolving from a tectdist
//!   runtime pack (`TECTDIST_RUNTIME_ROOT`), always the internal correctness
//!   authority and escalation target; and
//! * **oracle tooling** — BasicTeX execution used only for comparison in
//!   build/test/qualification infrastructure (`OracleRunner`, never linked
//!   into production routing).
//!
//! During the M1 transition this module centralises the single remaining
//! production read of the legacy `TECTDIST_BASICTEX_ROOT` variable
//! (see `docs/BASICTEX_REFERENCE_CATALOGUE.md`). New code must resolve
//! runtime roots through [`resolve_runtime_pack`] only.

use std::path::{Path, PathBuf};

/// A tectdist-resolvable set of exact-lane tools and assets.
///
/// Implementations own layout details; callers only request logical tool
/// names (for example `"pdftex"`, `"bibtex"`, `"xdvipdfmx"`).
pub trait RuntimePack: Send + Sync {
    /// Stable identity recorded in manifests, telemetry, and benchmarks.
    fn identity(&self) -> String;
    /// Filesystem root of the pack.
    fn root(&self) -> &Path;
    /// Resolve a logical tool name to an executable path.
    fn resolve_tool(&self, tool: &str) -> Result<PathBuf, String>;
}

/// Runtime pack backed by an image-style directory layout:
/// `<root>/bin/<platform-dir>/<tool>` with a flat `<root>/bin/<tool>`
/// fallback. This is the transitional adapter for the pinned oracle image;
/// it must never appear in production routing after PACK-008/009.
pub struct ImageRuntimePack {
    root: PathBuf,
}

impl ImageRuntimePack {
    pub fn new(root: impl Into<PathBuf>) -> Self {
        Self { root: root.into() }
    }
}

impl RuntimePack for ImageRuntimePack {
    fn identity(&self) -> String {
        format!("image:{}", self.root.display())
    }

    fn root(&self) -> &Path {
        &self.root
    }

    fn resolve_tool(&self, tool: &str) -> Result<PathBuf, String> {
        if self.root.as_os_str().is_empty() {
            return Err("runtime root is not configured".to_string());
        }
        let bin = self.root.join("bin");
        if let Ok(entries) = bin.read_dir() {
            for entry in entries.flatten() {
                if entry.path().is_dir() && entry.path().join(tool).exists() {
                    return Ok(entry.path().join(tool));
                }
            }
        }
        let flat = bin.join(tool);
        if flat.exists() {
            return Ok(flat);
        }
        Err(format!("runtime pack has no tool '{tool}'"))
    }
}

/// The resolved production runtime source.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RuntimePackSource {
    /// Tectdist-owned pack selected via `TECTDIST_RUNTIME_ROOT`
    /// (the production variable per plan M1).
    TectdistRoot(PathBuf),
    /// Legacy oracle-image root selected via `TECTDIST_BASICTEX_ROOT`.
    ///
    /// TRANSITIONAL ONLY: accepted so existing test/qualification flows keep
    /// working until PACK-008/PACK-009 land. Tracked in the reference
    /// catalogue for removal.
    LegacyImageRoot(PathBuf),
}

/// Resolve the active runtime pack root.
///
/// Precedence: `TECTDIST_RUNTIME_ROOT`, then legacy
/// `TECTDIST_BASICTEX_ROOT`. Returns `None` when neither is configured.
pub fn detect_runtime_pack_source() -> Option<RuntimePackSource> {
    if let Ok(root) = std::env::var("TECTDIST_RUNTIME_ROOT") {
        if !root.is_empty() {
            return Some(RuntimePackSource::TectdistRoot(root.into()));
        }
    }
    if let Ok(root) = std::env::var("TECTDIST_BASICTEX_ROOT") {
        if !root.is_empty() {
            return Some(RuntimePackSource::LegacyImageRoot(root.into()));
        }
    }
    None
}

/// Convenience: construct the default [`RuntimePack`] for the detected
/// source. Errors when no root is configured.
pub fn resolve_runtime_pack() -> Result<(Box<dyn RuntimePack>, RuntimePackSource), String>
{
    match detect_runtime_pack_source() {
        Some(source) => {
            let root = match &source {
                RuntimePackSource::TectdistRoot(path)
                | RuntimePackSource::LegacyImageRoot(path) => path.clone(),
            };
            // Both layouts are currently image-style; the tectdist shard
            // pack reader arrives with PACK-003/004.
            Ok((Box::new(ImageRuntimePack::new(root)), source))
        }
        None => Err(
            "no runtime pack configured: set TECTDIST_RUNTIME_ROOT \
             (or legacy TECTDIST_BASICTEX_ROOT during the M1 transition)"
                .to_string(),
        ),
    }
}

/// One exact-lane compile request. Deliberately minimal: richer request
/// models (`BuildSpec`, plan §11) supersede this as milestones land, but
/// every exact execution must already flow through a lane object rather
/// than ad-hoc environment lookups.
#[derive(Debug, Clone)]
pub struct ExactRequest {
    pub tool: String,
    pub argv: Vec<String>,
    pub cwd: PathBuf,
}

/// Outcome marker for one exact-lane run.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LaneKind {
    Exact,
}

/// The exact internal lane: resolves tools exclusively through its
/// [`RuntimePack`] and executes them one-shot. This is the correctness
/// authority and the escalation target for acceleration misses.
pub trait ExactLane: Send + Sync {
    fn kind(&self) -> LaneKind {
        LaneKind::Exact
    }
    fn pack(&self) -> &dyn RuntimePack;
    /// Execute `request` exactly once in a fresh process.
    fn run(&self, request: &ExactRequest) -> Result<i32, String>;
}

/// Default one-shot exact lane over any [`RuntimePack`].
pub struct OneShotExactLane<P: RuntimePack> {
    pack: P,
}

impl<P: RuntimePack> OneShotExactLane<P> {
    pub fn new(pack: P) -> Self {
        Self { pack }
    }
}

impl<P: RuntimePack> ExactLane for OneShotExactLane<P> {
    fn pack(&self) -> &dyn RuntimePack {
        &self.pack
    }

    fn run(&self, request: &ExactRequest) -> Result<i32, String> {
        use std::process::Command;
        let tool = self.pack.resolve_tool(&request.tool)?;
        let status = Command::new(tool)
            .args(&request.argv)
            .current_dir(&request.cwd)
            .status()
            .map_err(|error| format!("exact lane spawn: {error}"))?;
        Ok(status.code().unwrap_or(128))
    }
}

/// Oracle-side case description for comparator runs (plan §2.3). Oracle
/// execution itself stays behind `oracle-tools` builds / Python oracle
/// scripts; production crates must never call it for routing.
#[cfg(feature = "oracle-tools")]
pub mod oracle {
    use super::*;

    #[derive(Debug, Clone)]
    pub struct OracleCase {
        pub id: String,
        pub tool: String,
        pub argv: Vec<String>,
        pub cwd: PathBuf,
    }

    #[derive(Debug, Clone)]
    pub struct OracleResult {
        pub exit_code: i32,
    }

    /// Executes cases against the pinned BasicTeX oracle image.
    /// Test/qualification infrastructure only.
    pub trait OracleRunner: Send + Sync {
        fn run(&self, case: &OracleCase) -> Result<OracleResult, String>;
    }

    /// Oracle runner over the pinned image using the shared pack layout.
    pub struct ImageOracleRunner {
        pack: ImageRuntimePack,
    }

    impl ImageOracleRunner {
        pub fn new(root: impl Into<PathBuf>) -> Self {
            Self {
                pack: ImageRuntimePack::new(root),
            }
        }
    }

    impl OracleRunner for ImageOracleRunner {
        fn run(&self, case: &OracleCase) -> Result<OracleResult, String> {
            let lane = OneShotExactLane::new(ImageRuntimePack::new(
                self.pack.root().to_path_buf(),
            ));
            lane.run(&ExactRequest {
                tool: case.tool.clone(),
                argv: case.argv.clone(),
                cwd: case.cwd.clone(),
            })
            .map(|exit_code| OracleResult { exit_code })
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    fn temp_root(tag: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!(
            "td-runtime-test-{tag}-{}",
            std::process::id()
        ));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn image_pack_resolves_platform_dir_then_flat() {
        let root = temp_root("layout");
        fs::create_dir_all(root.join("bin/universal-darwin")).unwrap();
        fs::write(root.join("bin/universal-darwin/pdftex"), "#!/bin/sh\n").unwrap();
        fs::create_dir_all(root.join("bin")).unwrap();
        fs::write(root.join("bin/bibtex"), "#!/bin/sh\n").unwrap();

        let pack = ImageRuntimePack::new(&root);
        assert!(pack.resolve_tool("pdftex").is_ok());
        assert!(pack.resolve_tool("bibtex").is_ok());
        assert!(pack.resolve_tool("missing").is_err());
        assert_eq!(
            pack.resolve_tool("missing").unwrap_err(),
            "runtime pack has no tool 'missing'"
        );
    }

    #[test]
    fn empty_root_errors_without_panic() {
        let pack = ImageRuntimePack::new(PathBuf::new());
        assert_eq!(
            pack.resolve_tool("pdftex").unwrap_err(),
            "runtime root is not configured"
        );
    }

    #[test]
    fn detection_prefers_tectdist_runtime_root() {
        // Serialised: env vars are process-global. Guarded by a single
        // thread here; CI runs test binaries per-suite.
        unsafe {
            std::env::set_var("TECTDIST_RUNTIME_ROOT", "/tmp/td-pack");
            std::env::set_var("TECTDIST_BASICTEX_ROOT", "/tmp/td-oracle");
        }
        assert_eq!(
            detect_runtime_pack_source(),
            Some(RuntimePackSource::TectdistRoot("/tmp/td-pack".into()))
        );
        unsafe {
            std::env::remove_var("TECTDIST_RUNTIME_ROOT");
        }
        assert_eq!(
            detect_runtime_pack_source(),
            Some(RuntimePackSource::LegacyImageRoot("/tmp/td-oracle".into()))
        );
        unsafe {
            std::env::remove_var("TECTDIST_BASICTEX_ROOT");
        }
        assert_eq!(detect_runtime_pack_source(), None);
    }
}
