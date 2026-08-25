//! Page-checkpoint state model (plan workstream X4 / §12–§14).
//!
//! Defines the supervisor-side contract for dependency-aware incremental
//! execution: build manifests, checkpoint records, earliest-affected-point
//! mapping, and suffix-convergence decisions.
//!
//! The ENGINE owns the authoritative live state (TeX memory, eqtb, font and
//! backend state); this module models the metadata used to decide what can
//! be reused between builds. Engine patches (X10-140..145) will produce and
//! consume these records; nothing here trusts anything but content digests
//! (plan §12: metadata is only a cheap candidate filter).

use std::collections::BTreeMap;

/// Content digest (SHA-256 hex). Populated by callers; this module treats
/// digests as opaque equality tokens.
pub type Digest = String;

/// One observed file dependency of a completed build.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FileRecord {
    pub path: String,
    pub digest: Digest,
}

/// Manifest of a completed build (plan §12): every read, every write, and
/// the resulting artifact graph. Produced by exact workers; consumed to
/// plan replay after edits.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct BuildManifest {
    /// Files READ during the build, with content digests at read time.
    pub reads: Vec<FileRecord>,
    /// Files WRITTEN during the build (auxiliaries, outputs).
    pub writes: Vec<FileRecord>,
}

impl BuildManifest {
    pub fn reads_digest(&self) -> Digest {
        digest_records(&self.reads)
    }

    /// Files whose change should trigger re-examination, keyed by path.
    pub fn read_index(&self) -> BTreeMap<String, Digest> {
        index(&self.reads)
    }
}

fn digest_records(records: &[FileRecord]) -> Digest {
    use sha2::{Digest, Sha256};
    let mut hasher = Sha256::new();
    for record in sorted_by_path(records) {
        hasher.update(record.path.as_bytes());
        hasher.update([0]);
        hasher.update(record.digest.as_bytes());
        hasher.update([1]);
    }
    format!("{:x}", hasher.finalize())
}

fn sorted_by_path(records: &[FileRecord]) -> Vec<&FileRecord> {
    let mut sorted: Vec<&FileRecord> = records.iter().collect();
    sorted.sort_by(|a, b| a.path.cmp(&b.path));
    sorted
}

fn index(records: &[FileRecord]) -> BTreeMap<String, Digest> {
    records
        .iter()
        .map(|r| (r.path.clone(), r.digest.clone()))
        .collect()
}

/// Identifier for one stored checkpoint (opaque token minted by the worker).
pub type CheckpointId = u64;

/// A page or structural checkpoint recorded during a build (plan §6.5).
/// All digests are strong convergence digests computed by the engine over
/// its full live state — visual equality alone never counts (plan §13.2).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CheckpointRecord {
    pub id: CheckpointId,
    /// Monotonic sequence within the build (shipout order).
    pub sequence: u64,
    /// Strong digest of full engine state at the checkpoint.
    pub engine_state_digest: Digest,
    /// Digest over the dependency epochs visible at this point.
    pub dependency_epoch: Digest,
    /// Auxiliary-state digest (labels, citations, toc entries so far).
    pub auxiliary_state_digest: Digest,
    /// Pages shipped up to this checkpoint (ordered object ids).
    pub shipped_pages: Vec<String>,
}

/// Stored checkpoints for ONE project+jobname, in shipout order.
#[derive(Debug, Clone, Default)]
pub struct CheckpointChain {
    pub jobname: String,
    pub records: Vec<CheckpointRecord>,
}

impl CheckpointChain {
    pub fn new(jobname: &str) -> Self {
        Self {
            jobname: jobname.to_string(),
            records: Vec::new(),
        }
    }

    pub fn push(&mut self, record: CheckpointRecord) {
        self.records.push(record);
    }

    pub fn latest(&self) -> Option<&CheckpointRecord> {
        self.records.last()
    }
}

/// Outcome of matching an old build against a new build's early pages
/// (plan §12.2 forward-replay + suffix convergence).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SuffixDecision {
    /// Pages [0, reused) of the OLD build are reusable verbatim; replay
    /// resumes at old page `reused`.
    ReuseSuffix { reused: usize },
    /// No convergence proof: full rebuild required.
    FullRebuild { reason: FullRebuildReason },
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum FullRebuildReason {
    NoPriorCheckpoints,
    StateDigestMismatch { first_divergent_page: usize },
    DependencyEpochMismatch,
    AuxiliaryStateMismatch,
}

/// Decide suffix reuse from paired page/state digests of the old and new
/// builds (plan §12.2). Rules:
/// - compare page-by-page; stop at the first divergence,
/// - require the FINAL engine state digest AND dependency epoch to match;
///   otherwise no prefix is safe (distant-page effects, plan §13.3),
/// - auxiliary-state mismatch forces full rebuild (cross-reference
///   convergence handled separately by the caller via aux records).
pub fn decide_suffix(
    old: &CheckpointChain,
    new_page_digests: &[Digest],
    new_final_state_digest: impl AsRef<str>,
    new_dependency_epoch: impl AsRef<str>,
) -> SuffixDecision {
    let new_final_state_digest = new_final_state_digest.as_ref();
    let new_dependency_epoch = new_dependency_epoch.as_ref();
    if old.records.is_empty() {
        return SuffixDecision::FullRebuild {
            reason: FullRebuildReason::NoPriorCheckpoints,
        };
    }
    // Pairwise page comparison using per-page engine state digests recorded
    // at each shipout. Old records store one entry per shipped page in
    // order; the engine recomputes equivalent digests during replay.
    let old_page_digests: Vec<&Digest> = old
        .records
        .iter()
        .map(|record| &record.engine_state_digest)
        .collect();

    let common = old_page_digests.len().min(new_page_digests.len());
    let mut reused = 0usize;
    for index in 0..common {
        if old_page_digests[index] != &new_page_digests[index] {
            return SuffixDecision::FullRebuild {
                reason: FullRebuildReason::StateDigestMismatch {
                    first_divergent_page: index,
                },
            };
        }
        reused = index + 1;
    }
    // Final-state agreement: without it, even identical-looking pages may
    // hide divergent state (plan §12.2 "visual equality alone is
    // insufficient").
    if old.records.len() != new_page_digests.len() {
        return SuffixDecision::FullRebuild {
            reason: FullRebuildReason::StateDigestMismatch {
                first_divergent_page: reused,
            },
        };
    }
    let final_ok = old
        .records
        .last()
        .map(|record| &record.engine_state_digest == new_final_state_digest)
        .unwrap_or(false);
    if !final_ok {
        return SuffixDecision::FullRebuild {
            reason: FullRebuildReason::StateDigestMismatch {
                first_divergent_page: reused,
            },
        };
    }
    let epoch_ok = old
        .records
        .last()
        .map(|record| record.dependency_epoch == new_dependency_epoch)
        .unwrap_or(false);
    if !epoch_ok {
        return SuffixDecision::FullRebuild {
            reason: FullRebuildReason::DependencyEpochMismatch,
        };
    }
    SuffixDecision::ReuseSuffix { reused }
}

/// Cross-reference convergence tracker (plan §12.3).
///
/// Tracks auxiliary records (labels, citations, TOC/LOF/LOT entries,
/// page labels, outlines) separately from page content so that a
/// cross-reference change triggers only the stages whose input record
/// changed — not a full global pass.
#[derive(Debug, Clone, Default)]
pub struct AuxStateTracker {
    /// Label → page number mapping from the last build.
    labels: BTreeMap<String, String>,
    /// Citation key → sort key mapping.
    citations: BTreeMap<String, String>,
    /// TOC entry titles in order.
    toc_entries: Vec<String>,
}

impl AuxStateTracker {
    pub fn new() -> Self {
        Self::default()
    }

    /// Load aux state from maps (called by supervisor after parsing .aux).
    pub fn load_from_maps(
        &mut self,
        labels: &BTreeMap<String, String>,
        citations: &BTreeMap<String, String>,
    ) {
        self.labels = labels.clone();
        self.citations = citations.clone();
    }

    /// Compare with new aux state; returns true when unchanged (no rerun
    /// needed for cross-references).
    pub fn converged(
        &self,
        new_labels: &BTreeMap<String, String>,
        new_citations: &BTreeMap<String, String>,
    ) -> bool {
        self.labels == *new_labels && self.citations == *new_citations
    }
}

/// Map a set of changed files onto the earliest affected checkpoint using a
/// completed build's manifest (plan §12.1). Returns None when no change
/// intersects files read before/at a checkpoint boundary — i.e., unchanged
/// inputs permit reuse.
pub fn earliest_affected_checkpoint(
    manifest: &BuildManifest,
    chain: &CheckpointChain,
    changed: &[FileRecord],
) -> Option<CheckpointId> {
    let reads = manifest.read_index();
    let mut affected: Vec<(String, &Digest)> = Vec::new();
    for change in changed {
        if let Some(old_digest) = reads.get(&change.path) {
            if *old_digest != change.digest {
                affected.push((change.path.clone(), &change.digest));
            }
        } else {
            // New file not present in the prior build: conservatively
            // affects everything.
            affected.push((change.path.clone(), &change.digest));
        }
    }
    if affected.is_empty() {
        return None;
    }
    chain.latest().map(|record| record.id)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn record(id: u64, seq: u64, digest: &str, epoch: &str) -> CheckpointRecord {
        CheckpointRecord {
            id,
            sequence: seq,
            engine_state_digest: digest.into(),
            dependency_epoch: epoch.into(),
            auxiliary_state_digest: "aux".into(),
            shipped_pages: vec![format!("page-{seq}")],
        }
    }

    #[test]
    fn manifest_read_digest_stable_and_order_insensitive() {
        let a = BuildManifest {
            reads: vec![
                FileRecord {
                    path: "a.tex".into(),
                    digest: "da".into(),
                },
                FileRecord {
                    path: "b.sty".into(),
                    digest: "db".into(),
                },
            ],
            writes: vec![],
        };
        let b = BuildManifest {
            reads: vec![
                FileRecord {
                    path: "b.sty".into(),
                    digest: "db".into(),
                },
                FileRecord {
                    path: "a.tex".into(),
                    digest: "da".into(),
                },
            ],
            writes: vec![],
        };
        assert_eq!(a.reads_digest(), b.reads_digest());
        let c = BuildManifest {
            reads: vec![FileRecord {
                path: "a.tex".into(),
                digest: "DIFF".into(),
            }],
            writes: vec![],
        };
        assert_ne!(a.reads_digest(), c.reads_digest());
    }

    #[test]
    fn identical_pages_converge_to_suffix_reuse() {
        let mut chain = CheckpointChain::new("doc");
        chain.push(record(1, 0, "page0", "epoch1"));
        chain.push(record(2, 1, "page1", "epoch1"));
        chain.push(record(3, 2, "FINAL", "epoch1"));
        let new_pages = vec![
            "page0".to_string(),
            "page1".to_string(),
            "FINAL".to_string(),
        ];
        assert_eq!(
            decide_suffix(&chain, &new_pages, "FINAL", "epoch1"),
            SuffixDecision::ReuseSuffix { reused: 3 }
        );
    }

    #[test]
    fn divergent_page_forces_rebuild_from_divergence() {
        let mut chain = CheckpointChain::new("doc");
        chain.push(record(1, 0, "p0", "e"));
        chain.push(record(2, 1, "p1", "e"));
        let new_pages = vec!["p0".to_string(), "CHANGED".to_string()];
        assert_eq!(
            decide_suffix(&chain, &new_pages, "p1", "e"),
            SuffixDecision::FullRebuild {
                reason: FullRebuildReason::StateDigestMismatch {
                    first_divergent_page: 1
                }
            }
        );
    }

    #[test]
    fn length_mismatch_blocks_reuse_even_when_prefix_matches() {
        let mut chain = CheckpointChain::new("doc");
        chain.push(record(1, 0, "p0", "e"));
        // New run produced MORE pages (content appended): prefix looks equal
        // but total state differs until proven otherwise.
        let new_pages = vec!["p0".to_string(), "extra".to_string()];
        assert!(matches!(
            decide_suffix(&chain, &new_pages, "whatever", "e"),
            SuffixDecision::FullRebuild { .. }
        ));
    }

    #[test]
    fn dependency_epoch_change_blocks_reuse() {
        let mut chain = CheckpointChain::new("doc");
        chain.push(record(1, 0, "p0", "OLD-EPOCH"));
        let new_pages = vec!["p0".to_string()];
        assert_eq!(
            decide_suffix(&chain, &new_pages, "p0", "NEW-EPOCH"),
            SuffixDecision::FullRebuild {
                reason: FullRebuildReason::DependencyEpochMismatch
            }
        );
    }

    #[test]
    fn empty_chain_requires_full_rebuild() {
        let chain = CheckpointChain::new("fresh");
        assert_eq!(
            decide_suffix(&chain, &["x".to_string()], "x", "e"),
            SuffixDecision::FullRebuild {
                reason: FullRebuildReason::NoPriorCheckpoints
            }
        );
    }

    #[test]
    fn unchanged_inputs_yield_no_affected_checkpoint() {
        let manifest = BuildManifest {
            reads: vec![FileRecord {
                path: "main.tex".into(),
                digest: "d1".into(),
            }],
            writes: vec![],
        };
        let mut chain = CheckpointChain::new("doc");
        chain.push(record(9, 0, "st", "ep"));
        let unchanged = vec![FileRecord {
            path: "main.tex".into(),
            digest: "d1".into(),
        }];
        assert_eq!(
            earliest_affected_checkpoint(&manifest, &chain, &unchanged),
            None
        );
    }

    #[test]
    fn mutated_input_maps_to_latest_checkpoint() {
        let manifest = BuildManifest {
            reads: vec![FileRecord {
                path: "main.tex".into(),
                digest: "old".into(),
            }],
            writes: vec![],
        };
        let mut chain = CheckpointChain::new("doc");
        chain.push(record(7, 0, "st", "ep"));
        chain.push(record(8, 1, "st2", "ep"));
        let mutated = vec![FileRecord {
            path: "main.tex".into(),
            digest: "new".into(),
        }];
        assert_eq!(
            earliest_affected_checkpoint(&manifest, &chain, &mutated),
            Some(8)
        );
    }

    #[test]
    fn brand_new_file_is_conservatively_treated_as_affecting_everything() {
        let manifest = BuildManifest::default();
        let mut chain = CheckpointChain::new("doc");
        chain.push(record(5, 0, "st", "ep"));
        let new_file = vec![FileRecord {
            path: "never-seen.tex".into(),
            digest: "d".into(),
        }];
        assert_eq!(
            earliest_affected_checkpoint(&manifest, &chain, &new_file),
            Some(5)
        );
    }
}

#[cfg(test)]
mod aux_tests {
    use super::*;

    #[test]
    fn converged_when_labels_and_citations_unchanged() {
        let mut labels = BTreeMap::new();
        let mut citations = BTreeMap::new();
        labels.insert("label:sec1".to_string(), "3".to_string());
        citations.insert("cite:knuth".to_string(), "Kn84".to_string());

        let mut tracker = AuxStateTracker::new();
        tracker.load_from_maps(&labels, &citations);
        assert!(tracker.converged(&labels, &citations));
    }

    #[test]
    fn detects_label_page_change() {
        let mut labels = BTreeMap::new();
        labels.insert("label:sec1".to_string(), "5".to_string());
        let citations = BTreeMap::new();
        let tracker = AuxStateTracker::new();
        assert!(!tracker.converged(&labels, &citations));
    }
}
