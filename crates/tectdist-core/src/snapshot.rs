//! Snapshot runtime abstraction (plan §0.3, §13; VM-001).
//!
//! All snapshot-based acceleration must flow through this trait. Planned
//! implementations: `WasmAotRuntime` (primary), `NativeForkRuntime`
//! (transitional pdfTeX path/benchmark control), `ArenaRuntime` (fallback).
//!
//! This module defines the API surface plus a [`FakeSnapshotRuntime`] used
//! by tests to exercise the capture/restore contract before any real engine
//! runtime lands (M3 decides which production implementation is adopted).

use std::collections::BTreeMap;

/// Stable digest type for state identity comparisons.
pub type Digest = String;

/// An engine image: compiled code plus its static assets for one engine
/// (plan L0). Content-addressed.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EngineImage {
    pub engine: String,
    pub content_digest: Digest,
}

/// A prepared (initialised but not instantiated) engine.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PreparedEngine {
    pub image: EngineImage,
}

/// A live engine instance with opaque runtime state identified only by its
/// digest. Real runtimes own the actual state bytes; the abstraction exposes
/// just enough identity for correctness checks.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EngineInstance {
    pub prepared: PreparedEngine,
    pub state_digest: Digest,
}

/// Why a snapshot was captured (plan §16.4 telemetry).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SnapshotReason {
    FormatLoaded,
    PackagePrefix,
    BeginDocument,
    Shipout(u64),
}

impl SnapshotReason {
    pub fn as_str(&self) -> &'static str {
        match self {
            SnapshotReason::FormatLoaded => "format_loaded",
            SnapshotReason::PackagePrefix => "package_prefix",
            SnapshotReason::BeginDocument => "begin_document",
            SnapshotReason::Shipout(_) => "shipout",
        }
    }
}

/// Where to pause execution next.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum StopCondition {
    NextCheckpointOrFinish,
    Finish,
}

/// Result of one bounded execution slice.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RunOutcome {
    /// A checkpoint boundary was reached at the given sequence number.
    Checkpoint(u64),
    /// The job finished with an exit status.
    Finished(i32),
    /// The runtime reports the current state is unsafe to continue from;
    /// callers must escalate to the exact lane.
    Unsafe(String),
}

/// Observable host-side state accompanying an engine snapshot (VFS handles,
/// output buffers, action results, …). The fake runtime models it as an
/// opaque key/value map; real implementations replace this.
pub type HostState = BTreeMap<String, String>;

/// An immutable captured snapshot.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Snapshot {
    pub engine_identity: EngineImage,
    pub state_digest: Digest,
    pub host: HostState,
    pub reason: SnapshotReason,
}

/// The pluggable runtime boundary (plan §13).
pub trait SnapshotRuntime {
    fn prepare(&self, image: &EngineImage) -> Result<PreparedEngine, String>;
    fn instantiate(&self, prepared: &PreparedEngine) -> Result<EngineInstance, String>;
    fn run_until(
        &self,
        instance: &mut EngineInstance,
        stop: StopCondition,
    ) -> Result<RunOutcome, String>;
    fn capture(
        &self,
        instance: &EngineInstance,
        host: &HostState,
        reason: SnapshotReason,
    ) -> Result<Snapshot, String>;
    fn clone_snapshot(&self, snapshot: &Snapshot) -> Result<EngineInstance, String>;
    fn restore_host(&self, snapshot: &Snapshot) -> Result<HostState, String>;
}

/// Test double implementing the documented invariants deterministically.
///
/// State model: each instance carries a monotonically increasing step count
/// mixed into its digest; `run_until(Finish)` advances to completion,
/// `run_until(NextCheckpointOrFinish)` advances one step and emits a
/// checkpoint every other step.
pub struct FakeSnapshotRuntime;

impl SnapshotRuntime for FakeSnapshotRuntime {
    fn prepare(&self, image: &EngineImage) -> Result<PreparedEngine, String> {
        if image.content_digest.is_empty() {
            return Err("engine image has no content digest".to_string());
        }
        Ok(PreparedEngine {
            image: image.clone(),
        })
    }

    fn instantiate(&self, prepared: &PreparedEngine) -> Result<EngineInstance, String> {
        Ok(EngineInstance {
            prepared: prepared.clone(),
            state_digest: format!("{}#step0", prepared.image.content_digest),
        })
    }

    fn run_until(
        &self,
        instance: &mut EngineInstance,
        stop: StopCondition,
    ) -> Result<RunOutcome, String> {
        let step = current_step(&instance.state_digest);
        let next = step + 1;
        instance.state_digest =
            format!("{}#step{next}", instance.prepared.image.content_digest);
        match stop {
            StopCondition::Finish => Ok(RunOutcome::Finished(0)),
            StopCondition::NextCheckpointOrFinish => {
                if next % 2 == 0 {
                    Ok(RunOutcome::Checkpoint(next))
                } else {
                    Ok(RunOutcome::Unsafe("odd steps are unsafe".to_string()))
                }
            }
        }
    }

    fn capture(
        &self,
        instance: &EngineInstance,
        host: &HostState,
        reason: SnapshotReason,
    ) -> Result<Snapshot, String> {
        Ok(Snapshot {
            engine_identity: instance.prepared.image.clone(),
            state_digest: instance.state_digest.clone(),
            host: host.clone(),
            reason,
        })
    }

    fn clone_snapshot(&self, snapshot: &Snapshot) -> Result<EngineInstance, String> {
        Ok(EngineInstance {
            prepared: PreparedEngine {
                image: snapshot.engine_identity.clone(),
            },
            state_digest: snapshot.state_digest.clone(),
        })
    }

    fn restore_host(&self, snapshot: &Snapshot) -> Result<HostState, String> {
        Ok(snapshot.host.clone())
    }
}

fn current_step(state_digest: &str) -> u64 {
    state_digest
        .rsplit("#step")
        .next()
        .and_then(|suffix| suffix.parse().ok())
        .unwrap_or(0)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn image() -> EngineImage {
        EngineImage {
            engine: "pdftex-fake".to_string(),
            content_digest: "img-digest-1".to_string(),
        }
    }

    #[test]
    fn prepare_rejects_undigested_images() {
        let runtime = FakeSnapshotRuntime;
        let bad = EngineImage {
            engine: "x".to_string(),
            content_digest: String::new(),
        };
        assert!(runtime.prepare(&bad).is_err());
        assert!(runtime.prepare(&image()).is_ok());
    }

    #[test]
    fn cloned_snapshot_preserves_state_and_host() {
        let runtime = FakeSnapshotRuntime;
        let prepared = runtime.prepare(&image()).unwrap();
        let mut instance = runtime.instantiate(&prepared).unwrap();

        // Advance: step 1 is unsafe, step 2 reaches a checkpoint boundary.
        let outcome = runtime
            .run_until(&mut instance, StopCondition::NextCheckpointOrFinish)
            .unwrap();
        assert_eq!(outcome, RunOutcome::Unsafe("odd steps are unsafe".to_string()));
        let outcome = runtime
            .run_until(&mut instance, StopCondition::NextCheckpointOrFinish)
            .unwrap();
        assert_eq!(outcome, RunOutcome::Checkpoint(2));

        let mut host = HostState::new();
        host.insert("vfs.handles".to_string(), "3".to_string());
        let snapshot = runtime
            .capture(&instance, &host, SnapshotReason::Shipout(2))
            .unwrap();

        // Cloning twice yields identical instances and never mutates the
        // snapshot (immutability invariant).
        let clone_a = runtime.clone_snapshot(&snapshot).unwrap();
        let clone_b = runtime.clone_snapshot(&snapshot).unwrap();
        assert_eq!(clone_a, clone_b);
        assert_eq!(clone_a.state_digest, snapshot.state_digest);

        // Host restoration fidelity.
        let restored_host = runtime.restore_host(&snapshot).unwrap();
        assert_eq!(restored_host, host);

        // Reason survives round-trip.
        assert_eq!(snapshot.reason.as_str(), "shipout");
    }

    #[test]
    fn finish_advances_to_terminal_state() {
        let runtime = FakeSnapshotRuntime;
        let prepared = runtime.prepare(&image()).unwrap();
        let mut instance = runtime.instantiate(&prepared).unwrap();
        let outcome = runtime.run_until(&mut instance, StopCondition::Finish).unwrap();
        assert_eq!(outcome, RunOutcome::Finished(0));
        // Instance state advanced past step 0.
        assert_ne!(instance.state_digest, format!("img-digest-1#step0"));
    }

    #[test]
    fn unsafe_outcome_signals_escalation() {
        let runtime = FakeSnapshotRuntime;
        let prepared = runtime.prepare(&image()).unwrap();
        let mut instance = runtime.instantiate(&prepared).unwrap();
        // Step 1 is odd => Unsafe under NextCheckpointOrFinish.
        let outcome = runtime
            .run_until(&mut instance, StopCondition::NextCheckpointOrFinish)
            .unwrap();
        assert!(matches!(outcome, RunOutcome::Unsafe(_)));
    }
}
