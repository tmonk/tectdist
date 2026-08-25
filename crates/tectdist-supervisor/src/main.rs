//! tectdist supervisor: per-user resident service (plan X10-100, X1).
//!
//! Owns the authenticated local socket, worker lifecycle bookkeeping,
//! project locks, cancellation, and telemetry counters. Compilation itself
//! is delegated to exact engine workers in later milestones; this binary
//! establishes the protocol, isolation properties, and lifecycle semantics.
//!
//! Protocol: newline-delimited JSON over a user-private Unix domain socket
//! (0600, parent directory 0700). Requests:
//!
//!   {"type":"ping"}
//!   {"type":"status"}
//!   {"type":"shutdown"}
//!   {"type":"compile","profile":"basictex-2026","argv":[...],"cwd":"..."}
//!
//! Responses carry `"ok"` plus payload fields; every response echoes
//! `"request_id"` when the request supplied one.
mod checkpoint;
mod output_graph;
mod output_store;
mod project_format;
mod rebuild_cache;
mod rebuild_gate;
use checkpoint::CheckpointChain;

use serde::{Deserialize, Serialize};
use std::collections::{HashMap, VecDeque};
use std::io::{BufRead, BufReader, Write};
use std::os::unix::fs::PermissionsExt;
use std::os::unix::net::{UnixListener, UnixStream};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering, AtomicBool};
use std::sync::{Arc, Mutex};

const PROTOCOL_VERSION: u32 = 1;

#[derive(Debug, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
enum Request {
    Ping {
        request_id: Option<u64>,
    },
    Status {
        request_id: Option<u64>,
    },
    Shutdown {
        request_id: Option<u64>,
    },
    /// Abort any in-flight compile for the named project directory.
    Cancel {
        request_id: Option<u64>,
        #[serde(default)]
        cwd: PathBuf,
    },
    Compile {
        request_id: Option<u64>,
        profile: String,
        argv: Vec<String>,
        cwd: PathBuf,
        /// Explicit job source file (e.g. main.tex); accepted for protocol
        /// compatibility and derived from argv when absent.
        #[serde(default)]
        #[allow(dead_code)]
        job: Option<String>,
        #[serde(default)]
        snapshot_key: Option<String>,
    },
    SnapshotRegister {
        request_id: Option<u64>,
        key: String,
        bytes_estimate: u64,
    },
    SnapshotTouch {
        request_id: Option<u64>,
        key: String,
    },
    SnapshotRelease {
        request_id: Option<u64>,
        key: String,
    },
    Snapshots {
        request_id: Option<u64>,
    },
    CheckpointPut {
        request_id: Option<u64>,
        key: String,
        jobname: String,
        records: Vec<CheckpointRecordDto>,
    },
    CheckpointGet {
        request_id: Option<u64>,
        key: String,
    },
    CheckpointEvict {
        request_id: Option<u64>,
        key: String,
    },
    Action {
        request_id: Option<u64>,
        tool: String,
        cwd: PathBuf,
        argv: Vec<String>,
        /// Files whose content participates in the action key.
        inputs: Vec<PathBuf>,
        /// Files the action is expected to produce; restored on a hit.
        outputs: Vec<PathBuf>,
    },
}

#[derive(Debug, Serialize)]
struct Response {
    ok: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    request_id: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    error: Option<String>,
    #[serde(flatten)]
    payload: Payload,
}

#[derive(Debug, Serialize, Default)]
#[serde(rename_all = "snake_case")]
enum Payload {
    Cancelled { delivered: bool },
    #[default]
    Empty,
    Pong {
        protocol_version: u32,
    },
    Status {
        protocol_version: u32,
        pid: u32,
        uptime_ms: u64,
        compiles_started: u64,
        compiles_succeeded: u64,
        compiles_failed: u64,
        #[serde(default)]
        compiles_cache_hits: u64,
        active_locks: Vec<String>,
    },
    CompileAccepted {
        exit_status: i32,
        duration_ms: u64,
        #[serde(skip_serializing_if = "Option::is_none")]
        snapshot_hit: Option<bool>,
    },
    Snapshots {
        entries: Vec<SnapshotEntry>,
        evicted: Vec<String>,
    },
    ActionResult {
        cache_hit: bool,
        exit_status: i32,
        duration_ms: u64,
        key_digest: String,
    },
    CheckpointChainData {
        jobname: String,
        pages: Vec<CheckpointPageSummary>,
        evicted_keys: Vec<String>,
    },
}

#[derive(Debug, Serialize)]
struct CheckpointPageSummary {
    sequence: u64,
    state_digest: String,
}

#[derive(Debug, Deserialize)]
pub struct CheckpointRecordDto {
    pub id: u64,
    pub sequence: u64,
    pub engine_state_digest: String,
    pub dependency_epoch: String,
    pub auxiliary_state_digest: String,
    pub shipped_pages: Vec<String>,
}

impl From<CheckpointRecordDto> for checkpoint::CheckpointRecord {
    fn from(dto: CheckpointRecordDto) -> Self {
        Self {
            id: dto.id,
            sequence: dto.sequence,
            engine_state_digest: dto.engine_state_digest,
            dependency_epoch: dto.dependency_epoch,
            auxiliary_state_digest: dto.auxiliary_state_digest,
            shipped_pages: dto.shipped_pages,
        }
    }
}

#[derive(Debug, Serialize)]
struct SnapshotEntry {
    key: String,
    bytes_estimate: u64,
    age_seconds: u64,
}

struct SupervisorState {
    image_root: PathBuf,
    started: std::time::Instant,
    compiles_started: AtomicU64,
    compiles_succeeded: AtomicU64,
    compiles_failed: AtomicU64,
    /// Compiles served from the unchanged-rebuild cache without running
    /// an engine (plan X4 / X10-E scenario 1).
    compiles_cache_hits: AtomicU64,
    /// Project locks keyed by canonicalised project path.
    project_locks: Mutex<HashMap<PathBuf, u64>>,
    /// Preamble-snapshot registry (plan X2 scaffold): keys with LRU eviction
    /// by entry count until real COW parents land.
    snapshots: Mutex<HashMap<String, SnapshotRecord>>,
    snapshot_max_entries: usize,
    /// Exact-engine fork-server worker (plan X1): a resident pdfTeX process
    /// holding the preloaded format; compile requests are forwarded over its
    /// private socket. None until first use; reset on any failure.
    engine_worker: Mutex<Option<EngineWorker>>,
    use_forkserver: bool,
    /// Page-checkpoint chains (plan X4) keyed by "<cwd>#<jobname>";
    /// LRU-evicted by entry count until real COW-backed storage lands.
    checkpoint_chains: Mutex<HashMap<String, CheckpointChain>>,
    checkpoint_chain_order: Mutex<VecDeque<String>>,
    checkpoint_max_chains: usize,
    /// Two-tier tool identity (plan §11.2): (size, mtime) as the cheap
    /// candidate check, content digest computed once per candidate change.
    /// BasicTeX image binaries are immutable within a profile, so the cached
    /// digest is valid until the candidate changes.
    tool_digests: Mutex<HashMap<PathBuf, (u64, i64, String)>>,
    /// Per-project cancellation flags, registered while a compile runs
    /// (X1 contract item: cancellation). Engine poll loops check these.
    cancel_flags: Mutex<HashMap<PathBuf, Arc<AtomicBool>>>,
    // Wired for X4/X5 engine-side integration; consulted once page
    // checkpoints land. Kept out of the dead-code lint until then.
    #[allow(dead_code)]
    aux_tracker: Mutex<checkpoint::AuxStateTracker>,
    #[allow(dead_code)]
    rebuild_cache: rebuild_cache::RebuildCache,
}

impl SupervisorState {
    fn tool_digest(&self, binary: &Path) -> Result<String, String> {
        let metadata = std::fs::metadata(binary)
            .map_err(|error| format!("stat {}: {error}", binary.display()))?;
        let mtime = metadata
            .modified()
            .ok()
            .and_then(|time| time.duration_since(std::time::UNIX_EPOCH).ok())
            .map(|duration| duration.as_secs() as i64)
            .unwrap_or(0);
        let candidate = (metadata.len(), mtime);
        let mut cache = self.tool_digests.lock().expect("tool digests poisoned");
        if let Some((cached_size, cached_mtime, cached_digest)) = cache.get(binary) {
            if *cached_size == candidate.0 && *cached_mtime == candidate.1 {
                return Ok(cached_digest.clone());
            }
        }
        let digest = sha256_file(binary)?;
        cache.insert(
            binary.to_path_buf(),
            (candidate.0, candidate.1, digest.clone()),
        );
        Ok(digest)
    }
}

#[derive(Debug, Clone)]
struct SnapshotRecord {
    bytes_estimate: u64,
    last_used: std::time::Instant,
}

impl SupervisorState {
    fn new() -> Self {
        let _snapshot_max_entries = std::env::var("TECTDIST_SNAPSHOT_MAX")
            .ok()
            .and_then(|value| value.parse().ok())
            .unwrap_or(32);
        let use_forkserver = std::env::var("TECTDIST_USE_FORKSERVER").as_deref() == Ok("1");
        let checkpoint_max_chains = std::env::var("TECTDIST_CHECKPOINT_MAX")
            .ok()
            .and_then(|value| value.parse().ok())
            .unwrap_or(16);
        Self {
            use_forkserver,
            engine_worker: Mutex::new(None),
            checkpoint_chains: Mutex::new(HashMap::new()),
            checkpoint_chain_order: Mutex::new(VecDeque::new()),
            checkpoint_max_chains,
            tool_digests: Mutex::new(HashMap::new()),
            snapshot_max_entries: std::env::var("TECTDIST_SNAPSHOT_MAX")
                .ok()
                .and_then(|value| value.parse().ok())
                .unwrap_or(32),
            image_root: PathBuf::from(std::env::var("TECTDIST_BASICTEX_ROOT").unwrap_or_default()),
            aux_tracker: Mutex::new(checkpoint::AuxStateTracker::new()),
            rebuild_cache: rebuild_cache::RebuildCache::new(),
            started: std::time::Instant::now(),
            compiles_started: AtomicU64::new(0),
            compiles_succeeded: AtomicU64::new(0),
            compiles_failed: AtomicU64::new(0),
            compiles_cache_hits: AtomicU64::new(0),
            cancel_flags: Mutex::new(HashMap::new()),
            project_locks: Mutex::new(HashMap::new()),
            snapshots: Mutex::new(HashMap::new()),
        }
    }

    /// Register or refresh a snapshot key; evict least-recently-used entries
    /// beyond the configured limit. Returns evicted keys for telemetry.
    fn snapshot_register(&self, key: &str, bytes_estimate: u64) -> Vec<String> {
        let mut snapshots = self.snapshots.lock().expect("snapshots poisoned");
        snapshots.insert(
            key.to_string(),
            SnapshotRecord {
                bytes_estimate,
                last_used: std::time::Instant::now(),
            },
        );
        let mut evicted = Vec::new();
        while snapshots.len() > self.snapshot_max_entries {
            let lru_key = snapshots
                .iter()
                .min_by_key(|(_, record)| record.last_used)
                .map(|(key, _)| key.clone());
            match lru_key {
                Some(key) => {
                    snapshots.remove(&key);
                    evicted.push(key);
                }
                None => break,
            }
        }
        evicted
    }

    fn snapshot_touch(&self, key: &str) -> bool {
        match self
            .snapshots
            .lock()
            .expect("snapshots poisoned")
            .get_mut(key)
        {
            Some(record) => {
                record.last_used = std::time::Instant::now();
                true
            }
            None => false,
        }
    }

    fn snapshot_release(&self, key: &str) -> bool {
        self.snapshots
            .lock()
            .expect("snapshots poisoned")
            .remove(key)
            .is_some()
    }

    fn snapshot_list(&self) -> Vec<SnapshotEntry> {
        self.snapshots
            .lock()
            .expect("snapshots poisoned")
            .iter()
            .map(|(key, record)| SnapshotEntry {
                key: key.clone(),
                bytes_estimate: record.bytes_estimate,
                age_seconds: record.last_used.elapsed().as_secs(),
            })
            .collect()
    }

    fn status(&self) -> Payload {
        Payload::Status {
            protocol_version: PROTOCOL_VERSION,
            pid: std::process::id(),
            uptime_ms: self.started.elapsed().as_millis() as u64,
            compiles_started: self.compiles_started.load(Ordering::Relaxed),
            compiles_succeeded: self.compiles_succeeded.load(Ordering::Relaxed),
            compiles_failed: self.compiles_failed.load(Ordering::Relaxed),
            compiles_cache_hits: self.compiles_cache_hits.load(Ordering::Relaxed),
            active_locks: self
                .project_locks
                .lock()
                .map(|locks| {
                    locks
                        .keys()
                        .map(|path| path.display().to_string())
                        .collect()
                })
                .unwrap_or_default(),
        }
    }

    /// Register a cancellation flag for a project; returns the shared flag
    /// the engine poll loops observe.
    fn register_cancel(&self, project: &Path) -> (PathBuf, Arc<AtomicBool>) {
        let key = project.canonicalize().unwrap_or_else(|_| project.to_path_buf());
        let flag = Arc::new(AtomicBool::new(false));
        if let Ok(mut flags) = self.cancel_flags.lock() {
            flags.insert(key.clone(), Arc::clone(&flag));
        }
        (key, flag)
    }

    fn take_cancel(&self, key: &Path) {
        if let Ok(mut flags) = self.cancel_flags.lock() {
            flags.remove(key);
        }
    }

    fn cancel_project(&self, project: &Path) -> bool {
        let key = project.canonicalize().unwrap_or_else(|_| project.to_path_buf());
        match self.cancel_flags.lock() {
            Ok(mut flags) => flags.get(&key).map(|flag| {
                flag.store(true, Ordering::SeqCst);
                true
            }).unwrap_or(false),
            Err(_) => false,
        }
    }

    /// Acquire a per-project lock; refuses concurrent compiles of one project
    /// while isolating distinct projects from each other.
    fn acquire_lock(&self, project: &Path) -> Result<(), String> {
        let mut locks = self.project_locks.lock().map_err(|_| "lock poisoned")?;
        let key = project
            .canonicalize()
            .unwrap_or_else(|_| project.to_path_buf());
        if locks.contains_key(&key) {
            return Err(format!(
                "project {} already has an active build",
                key.display()
            ));
        }
        locks.insert(key, u64::from(std::process::id()));
        Ok(())
    }

    fn release_lock(&self, project: &Path) {
        if let Ok(mut locks) = self.project_locks.lock() {
            let key = project
                .canonicalize()
                .unwrap_or_else(|_| project.to_path_buf());
            locks.remove(&key);
        }
    }
}

// ------------------------------------------------------------------
// Exact-engine fork-server worker (plan X1): resident pdfTeX holding the
// preloaded format; compiles run as copy-on-write children.
// ------------------------------------------------------------------

struct EngineWorker {
    child: std::process::Child,
    socket: PathBuf,
}

impl Drop for EngineWorker {
    fn drop(&mut self) {
        // Ensure the resident engine never outlives the supervisor.
        let _ = self.child.kill();
        let _ = self.child.wait();
        let _ = std::fs::remove_file(&self.socket);
    }
}

impl EngineWorker {
    /// Spawn the fork-server engine from the pinned image inside the project
    /// directory. A reusable base format (`latex` from the image) is seeded
    /// beside the sources so the first-line reference resolves locally;
    /// preamble snapshots (X2) replace it with richer formats later.
    fn spawn(image_root: &Path, cwd: &Path) -> Result<Self, String> {
        let bin_dir = image_root.join("bin/forkproto");
        let binary = bin_dir.join("pdftex");
        if !binary.is_file() {
            return Err(format!("fork-server binary missing: {}", binary.display()));
        }
        let base_format = image_root.join("texmf-var/web2c/pdftex/latex.fmt");
        if !base_format.is_file() {
            return Err("image lacks texmf-var/web2c/pdftex/latex.fmt".to_string());
        }
        std::fs::copy(&base_format, cwd.join("tectdist-latex.fmt"))
            .map_err(|error| format!("seed format: {error}"))?;
        let socket = cwd.join(".tectdist-engine.sock");
        // Remove a stale socket from a previous crashed worker.
        let _ = std::fs::remove_file(&socket);
        let child = std::process::Command::new(binary)
            .arg("-fmt=tectdist-latex")
            .arg("-interaction=batchmode")
            .current_dir(cwd)
            .env("TEXMFCNF", image_root)
            .env("TEXMFROOT", image_root)
            .env("TECTDIST_FORKSERVER_SOCKET", &socket)
            .env("TECTDIST_FORK_JOB", "job.tex")
            .spawn()
            .map_err(|error| format!("spawn fork server: {error}"))?;
        Ok(EngineWorker { child, socket })
    }

    #[allow(dead_code)] // used by tests in flight; kept for engine-worker diagnostics
    fn wait_ready(&mut self) -> Result<(), String> {
        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(5);
        loop {
            if self.socket.exists() {
                if let Some(status) = self.child.try_wait().map_err(|e| e.to_string())? {
                    return Err(format!("fork server exited early: {status}"));
                }
                return Ok(());
            }
            if let Some(status) = self.child.try_wait().map_err(|e| e.to_string())? {
                return Err(format!("fork server exited early: {status}"));
            }
            if std::time::Instant::now() > deadline {
                return Err("fork server socket did not appear".to_string());
            }
            std::thread::sleep(std::time::Duration::from_millis(10));
        }
    }

    fn compile(&self, job: &str) -> Result<(i32, u64), String> {
        let start = std::time::Instant::now();
        let alive = unsafe { libc::kill(self.child.id() as libc::pid_t, 0) } == 0;
        eprintln!(
            "worker.compile: sock={} exists={} engine_alive={}",
            self.socket.display(),
            self.socket.exists(),
            alive
        );
        // The engine may need a brief moment after printing its banner
        // before the socket is fully usable; retry briefly on ENOENT.
        let mut stream = None;
        let mut last_error = String::new();
        for attempt in 0..40 {
            match UnixStream::connect(&self.socket) {
                Ok(value) => {
                    stream = Some(value);
                    break;
                }
                Err(error) => {
                    let pid = self.child.id();
                    let alive = unsafe { libc::kill(pid as libc::pid_t, 0) } == 0;
                    last_error = format!(
                        "attempt {attempt}: sock_exists={} alive={} {error}",
                        self.socket.exists(),
                        alive
                    );
                    std::thread::sleep(std::time::Duration::from_millis(5));
                }
            }
        }
        let mut stream = stream.ok_or_else(|| format!("connect engine: {last_error}"))?;
        stream
            .write_all(format!("compile {job}\n").as_bytes())
            .map_err(|e| e.to_string())?;
        stream
            .set_read_timeout(Some(std::time::Duration::from_secs(300)))
            .map_err(|e| e.to_string())?;
        let mut reader = BufReader::new(stream);
        let mut line = String::new();
        reader.read_line(&mut line).map_err(|e| e.to_string())?;
        let value: serde_json::Value =
            serde_json::from_str(line.trim()).map_err(|e| e.to_string())?;
        let exit = value["exit"].as_i64().unwrap_or(1) as i32;
        Ok((exit, start.elapsed().as_millis() as u64))
    }

    fn shutdown(mut self) {
        if let Ok(mut stream) = UnixStream::connect(&self.socket) {
            let _ = stream.write_all(b"quit\n");
        }
        let _ = self.child.wait();
        let _ = std::fs::remove_file(&self.socket);
    }
}

// ------------------------------------------------------------------
// Action broker (plan X3 / X10-120..123): content-addressed reuse of
// exact core-helper executions.
// ------------------------------------------------------------------

fn sha256_hex(bytes: &[u8]) -> String {
    use sha2::{Digest, Sha256};
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    format!("{:x}", hasher.finalize())
}

fn sha256_file(path: &Path) -> Result<String, String> {
    let bytes = std::fs::read(path).map_err(|e| format!("read {}: {e}", path.display()))?;
    Ok(sha256_hex(&bytes))
}

impl SupervisorState {
    fn image_tool(&self, tool: &str) -> Result<PathBuf, String> {
        if self.image_root.as_os_str().is_empty() {
            return Err("TECTDIST_BASICTEX_ROOT is not configured".to_string());
        }
        let bin = self.image_root.join("bin");
        let mut platform_dir = None;
        for entry in bin.read_dir().map_err(|e| e.to_string())?.flatten() {
            if entry.path().is_dir() && entry.path().join(tool).exists() {
                platform_dir = Some(entry.path());
                break;
            }
        }
        platform_dir
            .map(|dir| dir.join(tool))
            .ok_or_else(|| format!("image has no tool '{tool}'"))
    }

    #[allow(dead_code)] // key derivation shared by upcoming replay paths
    fn checkpoint_key(&self, cwd: &Path, jobname: &str) -> String {
        let canonical = cwd.canonicalize().unwrap_or_else(|_| cwd.to_path_buf());
        format!("{}#{}", canonical.display(), jobname)
    }

    /// Insert or replace a chain; evicts the least-recently-used chain beyond
    /// the configured limit. Returns evicted keys for telemetry.
    fn checkpoint_chain_put(&self, key: String, chain: CheckpointChain) -> Vec<String> {
        let mut chains = self.checkpoint_chains.lock().expect("checkpoints poisoned");
        let mut order = self.checkpoint_chain_order.lock().expect("order poisoned");
        order.retain(|existing| existing != &key);
        order.push_back(key.clone());
        chains.insert(key, chain);
        let mut evicted = Vec::new();
        while order.len() > self.checkpoint_max_chains {
            let oldest = order.pop_front().expect("non-empty");
            chains.remove(&oldest);
            evicted.push(oldest);
        }
        evicted
    }

    fn checkpoint_chain_get(&self, key: &str) -> Option<CheckpointChain> {
        let mut order = self.checkpoint_chain_order.lock().expect("order poisoned");
        if order.iter().any(|existing| existing == key) {
            order.retain(|existing| existing != key);
            order.push_back(key.to_string());
        }
        self.checkpoint_chains
            .lock()
            .expect("checkpoints poisoned")
            .get(key)
            .cloned()
    }

    fn checkpoint_chain_evict(&self, key: &str) -> bool {
        let mut order = self.checkpoint_chain_order.lock().expect("order poisoned");
        if let Some(position) = order.iter().position(|existing| existing == key) {
            order.remove(position);
            return self
                .checkpoint_chains
                .lock()
                .expect("checkpoints poisoned")
                .remove(key)
                .is_some();
        }
        false
    }

    fn action_cache_dir(&self) -> PathBuf {
        let base = std::env::var("TECTDIST_ACTION_CACHE").unwrap_or_else(|_| {
            format!(
                "{}/.tectdist-cache",
                std::env::var("HOME").unwrap_or_else(|_| "/tmp".into())
            )
        });
        PathBuf::from(base).join("actions")
    }
}

fn run_action(
    state: &SupervisorState,
    tool: &str,
    cwd: &Path,
    argv: &[String],
    inputs: &[PathBuf],
    outputs: &[PathBuf],
) -> Result<(bool, i32), String> {
    let binary = state.image_tool(tool)?;
    let tool_digest = state.tool_digest(&binary)?;

    let mut input_pairs: Vec<(String, String)> = Vec::new();
    for input in inputs {
        let digest = sha256_file(&cwd.join(input))?;
        input_pairs.push((input.to_string_lossy().into_owned(), digest));
    }
    input_pairs.sort();

    const SEP: char = '\u{1}';
    let mut key_material = String::new();
    key_material.push_str(&tool_digest);
    key_material.push(SEP);
    for argument in argv {
        key_material.push_str(argument);
        key_material.push(SEP);
    }
    for (name, digest) in &input_pairs {
        key_material.push_str(name);
        key_material.push('=');
        key_material.push_str(digest);
        key_material.push(SEP);
    }
    let key_digest = sha256_hex(key_material.as_bytes());

    let cache_dir = state.action_cache_dir().join(&key_digest);
    let meta_path = cache_dir.join("meta.json");

    // Cache hit: restore declared outputs atomically.
    if meta_path.is_file() {
        let meta: serde_json::Value =
            serde_json::from_str(&std::fs::read_to_string(&meta_path).map_err(|e| e.to_string())?)
                .map_err(|e| e.to_string())?;
        let exit_status = meta["exit_status"].as_i64().unwrap_or(1) as i32;
        for output in outputs {
            let cached = cache_dir.join(output);
            if !cached.is_file() {
                return Err(format!("cache entry missing output {}", output.display()));
            }
            let destination = cwd.join(output);
            if let Some(parent) = destination.parent() {
                std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
            }
            let temporary = destination.with_extension("tectdist-tmp");
            std::fs::copy(&cached, &temporary).map_err(|e| e.to_string())?;
            std::fs::rename(temporary, &destination).map_err(|e| e.to_string())?;
        }
        return Ok((true, exit_status));
    }

    // Miss: exact execution through the pinned image.
    let status = std::process::Command::new(&binary)
        // argv[0] names the tool; the remainder are its arguments.
        .args(&argv[1..])
        .current_dir(cwd)
        .env("TEXMFROOT", &state.image_root)
        .status()
        .map_err(|error| format!("spawn {tool}: {error}"))?;
    let exit_status = status.code().unwrap_or(128);

    // Populate the cache only on success and only when outputs exist.
    if exit_status == 0 {
        let mut usable = !outputs.is_empty();
        for output in outputs {
            if !cwd.join(output).is_file() {
                usable = false;
                break;
            }
        }
        if usable {
            let _ = std::fs::create_dir_all(&cache_dir);
            for output in outputs {
                let _ = std::fs::copy(cwd.join(output), cache_dir.join(output));
            }
            let meta = serde_json::json!({
                "tool": tool,
                "exit_status": exit_status,
                "argv": argv,
                "inputs": input_pairs,
            });
            let _ = std::fs::write(
                &meta_path,
                serde_json::to_string_pretty(&meta).unwrap_or_default(),
            );
        }
    }
    Ok((false, exit_status))
}

fn respond(stream: &mut UnixStream, response: &Response) {
    if let Ok(mut line) = serde_json::to_string(response) {
        line.push('\n');
        let _ = stream.write_all(line.as_bytes());
        let _ = stream.flush();
    }
}

fn handle_request(
    state: &Arc<SupervisorState>,
    running: &Arc<AtomicBoolAlias>,
    request: Request,
) -> Response {
    match request {
        Request::Ping { request_id } => Response {
            ok: true,
            request_id,
            error: None,
            payload: Payload::Pong {
                protocol_version: PROTOCOL_VERSION,
            },
        },
        Request::Status { request_id } => Response {
            ok: true,
            request_id,
            error: None,
            payload: state.status(),
        },
        Request::Shutdown { request_id } => {
            running.store(false, Ordering::SeqCst);
            Response {
                ok: true,
                request_id,
                error: None,
                payload: Payload::Empty,
            }
        }
        Request::Cancel { request_id, cwd } => {
            let delivered = state.cancel_project(&cwd);
            Response {
                ok: true,
                request_id,
                error: None,
                payload: Payload::Cancelled { delivered },
            }
        }
        Request::Snapshots { request_id } => Response {
            ok: true,
            request_id,
            error: None,
            payload: Payload::Snapshots {
                entries: state.snapshot_list(),
                evicted: Vec::new(),
            },
        },
        Request::SnapshotRegister {
            request_id,
            key,
            bytes_estimate,
        } => {
            let evicted = state.snapshot_register(&key, bytes_estimate);
            Response {
                ok: true,
                request_id,
                error: None,
                payload: Payload::Snapshots {
                    entries: state.snapshot_list(),
                    evicted,
                },
            }
        }
        Request::SnapshotTouch { request_id, key } => {
            let found = state.snapshot_touch(&key);
            Response {
                ok: found,
                request_id,
                error: if found {
                    None
                } else {
                    Some("unknown snapshot key".into())
                },
                payload: Payload::Empty,
            }
        }
        Request::SnapshotRelease { request_id, key } => {
            let found = state.snapshot_release(&key);
            Response {
                ok: found,
                request_id,
                error: if found {
                    None
                } else {
                    Some("unknown snapshot key".into())
                },
                payload: Payload::Empty,
            }
        }
        Request::CheckpointPut {
            request_id,
            key,
            jobname,
            records,
        } => {
            let mut chain = checkpoint::CheckpointChain::new(&jobname);
            for dto in records {
                chain.push(dto.into());
            }
            let evicted = state.checkpoint_chain_put(key, chain);
            Response {
                ok: true,
                request_id,
                error: None,
                payload: Payload::CheckpointChainData {
                    jobname,
                    pages: Vec::new(),
                    evicted_keys: evicted,
                },
            }
        }
        Request::CheckpointGet { request_id, key } => match state.checkpoint_chain_get(&key) {
            Some(chain) => Response {
                ok: true,
                request_id,
                error: None,
                payload: Payload::CheckpointChainData {
                    jobname: chain.jobname,
                    pages: chain
                        .records
                        .iter()
                        .map(|record| CheckpointPageSummary {
                            sequence: record.sequence,
                            state_digest: record.engine_state_digest.clone(),
                        })
                        .collect(),
                    evicted_keys: Vec::new(),
                },
            },
            None => Response {
                ok: false,
                request_id,
                error: Some("unknown checkpoint chain".into()),
                payload: Payload::Empty,
            },
        },
        Request::CheckpointEvict { request_id, key } => {
            let evicted = state.checkpoint_chain_evict(&key);
            Response {
                ok: evicted,
                request_id,
                error: if evicted {
                    None
                } else {
                    Some("unknown checkpoint chain".into())
                },
                payload: Payload::Empty,
            }
        }
        Request::Action {
            request_id,
            tool,
            cwd,
            argv,
            inputs,
            outputs,
        } => {
            let started = std::time::Instant::now();
            match run_action(state, &tool, &cwd, &argv, &inputs, &outputs) {
                Ok((cache_hit, exit_status)) => Response {
                    ok: true,
                    request_id,
                    error: None,
                    payload: Payload::ActionResult {
                        cache_hit,
                        exit_status,
                        duration_ms: started.elapsed().as_millis() as u64,
                        key_digest: String::new(),
                    },
                },
                Err(error) => Response {
                    ok: false,
                    request_id,
                    error: Some(error),
                    payload: Payload::Empty,
                },
            }
        }
        Request::Compile {
            request_id,
            profile,
            argv,
            cwd,
            job: _,
            snapshot_key,
        } => {
            state.compiles_started.fetch_add(1, Ordering::Relaxed);
            // Snapshot keys participate in telemetry now; workers consume the
            // actual COW parent in milestone X2.
            let snapshot_hit = snapshot_key.as_ref().map(|key| state.snapshot_touch(key));
            if let Err(error) = state.acquire_lock(&cwd) {
                state.compiles_failed.fetch_add(1, Ordering::Relaxed);
                return Response {
                    ok: false,
                    request_id,
                    error: Some(error),
                    payload: Payload::Empty,
                };
            }
            // Compile chain, fastest first, every escalation logged:
            // X4 unchanged-rebuild gate -> X2 project format -> X1 fork
            // server -> exact one-shot. BT100 preserved by design (plan
            // §6.1 item 7): any non-applicability or failure falls
            // through to exact execution.
            let (_cancel_key, cancel_flag) = state.register_cancel(&cwd);
            let outcome = match rebuild_gate::try_cached(state, &cwd, &argv) {
                Some(hit) => {
                    state.compiles_cache_hits.fetch_add(1, Ordering::Relaxed);
                    Ok(hit)
                }
                None => {
                    let job = derive_job_name(&argv, &cwd);
                    let attempted = if profile == "basictex-2026" {
                        match project_format::fast_compile(
                            &state.image_root, &cwd, &argv,
                            Some(cancel_flag.as_ref()),
                        ) {
                            Ok(fast) => Ok((fast.exit_status, fast.duration_ms)),
                            Err(error) => {
                                eprintln!(
                                        "supervisor: project format not used ({error}); trying fork server"
                                    );
                                if state.use_forkserver {
                                    match state.forkserver_compile(&cwd, &job) {
                                        Ok((code, ms)) => Ok((code, ms)),
                                        Err(error) => {
                                            eprintln!(
                                                    "supervisor: fork server unavailable ({error}); using one-shot execution"
                                                );
                                            run_profile_compile(&profile, &argv, &cwd, &cancel_flag)
                                        }
                                    }
                                } else {
                                    run_profile_compile(&profile, &argv, &cwd, &cancel_flag)
                                }
                            }
                        }
                    } else {
                        run_profile_compile(&profile, &argv, &cwd, &cancel_flag)
                    };
                    // Cache-hit telemetry only counts real skips.
                    attempted
                }
            };
            state.take_cancel(&_cancel_key);
            state.release_lock(&cwd);
            // Record checkpoint chain after each successful compile (plan
            // §12: every completed build produces a manifest for dependency-
            // to-checkpoint mapping on future compiles).
            if outcome
                .as_ref()
                .map(|(code, _)| *code == 0)
                .unwrap_or(false)
            {
                let jobname = derive_job_name(&argv, &cwd);
                // Recursive snapshot: \input'ed subdirectory files must be
                // part of the recorded input set or the rebuild gate would
                // miss later edits to them.
                let files = snapshot_project_tree(&cwd)
                    .unwrap_or_else(|| snapshot_project_files(&cwd));
                let chain_key = format!("{}#{}", cwd.display(), jobname);
                let records: Vec<checkpoint::CheckpointRecord> = files
                    .iter()
                    .enumerate()
                    .map(|(index, (name, digest))| checkpoint::CheckpointRecord {
                        id: index as u64,
                        sequence: index as u64,
                        engine_state_digest: digest.clone(),
                        dependency_epoch: digest.clone(),
                        auxiliary_state_digest: String::new(),
                        shipped_pages: vec![name.clone()],
                    })
                    .collect();
                let mut chain = checkpoint::CheckpointChain::new(&jobname);
                for record in records {
                    chain.push(record);
                }
                state.checkpoint_chain_put(chain_key, chain);
            }
            match outcome {
                Ok((exit_status, duration_ms)) => {
                    if exit_status == 0 {
                        state.compiles_succeeded.fetch_add(1, Ordering::Relaxed);
                    } else {
                        state.compiles_failed.fetch_add(1, Ordering::Relaxed);
                    }
                    Response {
                        ok: true,
                        request_id,
                        error: None,
                        payload: Payload::CompileAccepted {
                            exit_status,
                            duration_ms,
                            snapshot_hit,
                        },
                    }
                }
                Err(error) => {
                    state.compiles_failed.fetch_add(1, Ordering::Relaxed);
                    Response {
                        ok: false,
                        request_id,
                        error: Some(error),
                        payload: Payload::Empty,
                    }
                }
            }
        }
    }
}

/// Execute one compile through the pinned BasicTeX image (exact fallback
/// semantics until dedicated workers land). The first argument names the
/// engine/tool; the remainder are forwarded unchanged.
/// Derive the job source file from compile argv (last .tex argument),
/// falling back to a directory scan.
pub(crate) fn derive_job_name(argv: &[String], cwd: &Path) -> String {
    for argument in argv.iter().rev() {
        let text = argument.clone();
        if text.ends_with(".tex") && !text.contains('=') {
            return PathBuf::from(&text)
                .file_name()
                .map(|name| name.to_string_lossy().into_owned())
                .unwrap_or(text);
        }
    }
    let candidates = || -> Option<String> {
        std::fs::read_dir(cwd)
            .ok()?
            .flatten()
            .filter_map(|entry| {
                let name = entry.file_name().to_string_lossy().into_owned();
                name.ends_with(".tex").then_some(name)
            })
            .next()
    };
    candidates().unwrap_or_else(|| "main.tex".to_string())
}

impl SupervisorState {
    /// Route one compile through the resident fork-server engine, spawning it
    /// on first use. Returns None when the fast path is disabled.
    fn forkserver_compile(&self, cwd: &Path, job: &str) -> Result<(i32, u64), String> {
        let mut guard = self.engine_worker.lock().expect("engine worker poisoned");
        if guard.is_none() {
            *guard = Some(EngineWorker::spawn(&self.image_root, cwd)?);
        }
        let worker = guard.as_ref().unwrap();
        match worker.compile(job) {
            Ok(result) => Ok(result),
            Err(error) => {
                // Worker is wedged or dead: discard it and escalate.
                if let Some(worker) = guard.take() {
                    worker.shutdown();
                }
                Err(error)
            }
        }
    }
}

fn run_profile_compile(
    profile: &str,
    argv: &[String],
    cwd: &Path,
    cancel_flag: &Arc<AtomicBool>,
) -> Result<(i32, u64), String> {
    if profile != "basictex-2026" {
        return Err(format!("unsupported profile '{profile}'"));
    }
    let root = std::env::var("TECTDIST_BASICTEX_ROOT").map_err(|_| {
        "TECTDIST_BASICTEX_ROOT is not set; cannot resolve the BasicTeX image".to_string()
    })?;
    let root_path = PathBuf::from(root);
    let program = argv.first().ok_or("empty argv")?;
    let platform_dir = root_path
        .join("bin")
        .read_dir()
        .map_err(|error| format!("cannot read bin/: {error}"))?
        .filter_map(Result::ok)
        .find(|entry| entry.path().is_dir())
        .ok_or("no platform directory under bin/")?;
    let binary = platform_dir.path().join(program);
    if !binary.exists() {
        return Err(format!("BasicTeX image has no '{program}'"));
    }
    // NOTE: unchanged-rebuild detection lives in rebuild_gate.rs (content
    // digests over the whole project tree, recorded chains). The earlier
    // mtime-proxy check that lived here was removed: plan §12 forbids
    // mtime-based decisions and rebuild_gate covers the same scenario
    // with strictly stronger evidence.

    // Capture pre/post-build file state for the build manifest (plan §12).
    let pre_build = snapshot_project_files(cwd);
    let start = std::time::Instant::now();
    // Compile limit (X1 "limits"): a runaway document must not wedge the
    // supervisor. Configurable for tests; the error escalates to the
    // caller exactly like any other failure.
    let timeout_secs: u64 = std::env::var("TECTDIST_COMPILE_TIMEOUT_SECS")
        .ok()
        .and_then(|value| value.parse().ok())
        .unwrap_or(600);
    let mut child = std::process::Command::new(binary)
        .args(&argv[1..])
        .current_dir(cwd)
        .env("TEXMFROOT", &root_path)
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn()
        .map_err(|error| format!("spawn failed: {error}"))?;
    let deadline = start + std::time::Duration::from_secs(timeout_secs);
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break status,
            Ok(None) => {
                if cancel_flag.load(Ordering::SeqCst) {
                    let _ = child.kill();
                    let _ = child.wait();
                    return Err("compile was cancelled".to_string());
                }
                if std::time::Instant::now() >= deadline {
                    let _ = child.kill();
                    let _ = child.wait();
                    return Err(format!(
                        "compile exceeded the {timeout_secs}s limit and was terminated"
                    ));
                }
                std::thread::sleep(std::time::Duration::from_millis(10));
            }
            Err(error) => return Err(format!("wait failed: {error}")),
        }
    };
    let post_build = snapshot_project_files(cwd);

    // Build manifest: record reads (pre) and writes (post diff) for
    // dependency-to-checkpoint mapping on future compiles (plan §12).
    let mut reads: Vec<(String, String)> = Vec::new();
    let mut writes: Vec<(String, String)> = Vec::new();
    {
        let all_pre: std::collections::HashMap<String, String> =
            pre_build.iter().cloned().collect();
        let all_post: std::collections::HashMap<String, String> =
            post_build.iter().cloned().collect();
        for (name, digest) in &all_pre {
            match all_post.get(name) {
                Some(post_digest) if post_digest == digest => {
                    reads.push((name.clone(), digest.clone()));
                }
                _ => {
                    writes.push((name.clone(), digest.clone()));
                }
            }
        }
        for (name, digest) in &all_post {
            if !all_pre.contains_key(name) {
                writes.push((name.clone(), digest.clone()));
            }
        }
        reads.sort();
        writes.sort();
    }

    Ok((
        status.code().unwrap_or(128),
        start.elapsed().as_millis() as u64,
    ))
}

/// Compute a content digest over a set of (name, digest) pairs.

/// Snapshot all files in a directory (name → sha256) for the build manifest.
pub(crate) fn snapshot_project_files(cwd: &Path) -> Vec<(String, String)> {
    let mut entries = Vec::new();
    if let Ok(dir_entries) = std::fs::read_dir(cwd) {
        for entry in dir_entries.flatten() {
            let path = entry.path();
            if !path.is_file() {
                continue;
            }
            let name = path
                .file_name()
                .map(|n| n.to_string_lossy().into_owned())
                .unwrap_or_default();
            if let Ok(bytes) = std::fs::read(&path) {
                use sha2::{Digest, Sha256};
                let mut hasher = Sha256::new();
                hasher.update(&bytes);
                entries.push((name, format!("{:x}", hasher.finalize())));
            }
        }
    }
    entries.sort();
    entries
}

/// Upper bound on files considered before declaring the project too large
/// to prove unchanged (the gate then falls back to a real compile).
const TREE_SNAPSHOT_MAX_FILES: usize = 8192;
const TREE_SNAPSHOT_MAX_DEPTH: usize = 16;

/// Recursive project snapshot keyed by path RELATIVE to `cwd`. Used by the
/// unchanged-rebuild gate so that edits to \\input'ed files in
/// subdirectories invalidate correctly (a flat listing would produce
/// false cache hits). Returns None when the tree cannot be fully proven:
/// unreadable entries, too many files, or excessive nesting — callers
/// must treat None as "cannot skip".
pub(crate) fn snapshot_project_tree(
    cwd: &Path,
) -> Option<Vec<(String, String)>> {
    fn walk(
        dir: &Path,
        base: &Path,
        depth: usize,
        out: &mut Vec<(String, String)>,
    ) -> bool {
        if depth > TREE_SNAPSHOT_MAX_DEPTH || out.len() > TREE_SNAPSHOT_MAX_FILES
        {
            return false;
        }
        let entries = match std::fs::read_dir(dir) {
            Ok(entries) => entries,
            Err(_) => return false,
        };
        for entry in entries.flatten() {
            let path = entry.path();
            let name = entry.file_name().to_string_lossy().into_owned();
            let file_type = match entry.file_type() {
                Ok(t) => t,
                Err(_) => return false,
            };
            if file_type.is_symlink() {
                // Never follow links: loops and outside-project escapes.
                continue;
            }
            if file_type.is_dir() {
                if name.starts_with('.') {
                    continue; // .tectdist, .git, caches
                }
                if !walk(&path, base, depth + 1, out) {
                    return false;
                }
            } else if file_type.is_file() {
                if out.len() >= TREE_SNAPSHOT_MAX_FILES {
                    return false;
                }
                let rel = path
                    .strip_prefix(base)
                    .unwrap_or(&path)
                    .to_string_lossy()
                    .into_owned();
                if let Ok(bytes) = std::fs::read(&path) {
                    use sha2::{Digest, Sha256};
                    let mut hasher = Sha256::new();
                    hasher.update(&bytes);
                    out.push((rel, format!("{:x}", hasher.finalize())));
                }
            }
        }
        true
    }
    let mut out = Vec::new();
    if walk(cwd, cwd, 0, &mut out) {
        out.sort();
        Some(out)
    } else {
        None
    }
}

/// Alias so the handler signature reads clearly without importing another
/// type name into scope twice.
type AtomicBoolAlias = std::sync::atomic::AtomicBool;

fn socket_path() -> PathBuf {
    if let Ok(explicit) = std::env::var("TECTDIST_SUPERVISOR_SOCKET") {
        return PathBuf::from(explicit);
    }
    let tmp = std::env::var("TMPDIR").unwrap_or_else(|_| "/tmp".to_string());
    let dir = PathBuf::from(tmp).join(format!(".tectdist-{}", libc_getuid()));
    let _ = std::fs::create_dir_all(&dir);
    dir.join("supervisor.sock")
}

extern "C" fn libc_getuid() -> u32 {
    // Avoid a libc dependency here; read via id resolution instead.
    // getuid is stable across macOS/Linux ABIs as a syscall wrapper.
    unsafe { raw_getuid() }
}

unsafe extern "C" {
    #[link_name = "getuid"]
    fn raw_getuid() -> u32;
}

fn serve(socket: &Path) -> Result<(), String> {
    if socket.exists() {
        // Refuse to hijack a live supervisor; stale sockets are replaced.
        if UnixStream::connect(socket).is_ok() {
            return Err("another supervisor is already listening".to_string());
        }
        let _ = std::fs::remove_file(socket);
    }
    let listener = UnixListener::bind(socket)
        .map_err(|error| format!("bind {}: {error}", socket.display()))?;
    std::fs::set_permissions(socket, std::fs::Permissions::from_mode(0o600))
        .map_err(|error| format!("chmod socket: {error}"))?;
    if let Some(parent) = socket.parent() {
        let _ = std::fs::set_permissions(parent, std::fs::Permissions::from_mode(0o700));
    }
    println!("supervisor: listening on {}", socket.display());

    // Non-blocking accept so the shutdown flag is honoured promptly even
    // with no incoming traffic (a blocking accept would only observe the
    // flag after the next connection).
    listener
        .set_nonblocking(true)
        .map_err(|error| format!("nonblocking: {error}"))?;

    let state = Arc::new(SupervisorState::new());
    let running = Arc::new(std::sync::atomic::AtomicBool::new(true));
    loop {
        if !running.load(Ordering::SeqCst) {
            break;
        }
        let stream = match listener.accept() {
            Ok((stream, _)) => stream,
            Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                std::thread::sleep(std::time::Duration::from_millis(10));
                continue;
            }
            Err(error) => return Err(format!("accept: {error}")),
        };
        // Accepted sockets may inherit O_NONBLOCK on some platforms.
        let _ = stream.set_nonblocking(false);
        let state = Arc::clone(&state);
        let running = Arc::clone(&running);
        // One thread per connection keeps concurrent clients responsive;
        // compilation serialises per project through project locks.
        std::thread::spawn(move || {
            let mut writer = stream.try_clone().expect("try_clone");
            let reader = BufReader::new(stream);
            for line in reader.lines() {
                let Ok(line) = line else { return };
                if line.trim().is_empty() {
                    continue;
                }
                match serde_json::from_str::<Request>(&line) {
                    Ok(request) => {
                        let response = handle_request(&state, &running, request);
                        respond(&mut writer, &response);
                        if !running.load(Ordering::SeqCst) {
                            return;
                        }
                    }
                    Err(error) => {
                        respond(
                            &mut writer,
                            &Response {
                                ok: false,
                                request_id: None,
                                error: Some(format!("bad request: {error}")),
                                payload: Payload::Empty,
                            },
                        );
                    }
                }
            }
        });
    }
    let _ = std::fs::remove_file(socket);
    println!("supervisor: shut down cleanly");
    Ok(())
}

fn client_send(request: &serde_json::Value) -> Result<serde_json::Value, String> {
    let mut stream =
        UnixStream::connect(socket_path()).map_err(|_| "supervisor not running".to_string())?;
    let mut line = serde_json::to_string(request).expect("serialise");
    line.push('\n');
    stream
        .write_all(line.as_bytes())
        .map_err(|e| e.to_string())?;
    let mut reader = BufReader::new(stream);
    let mut response_line = String::new();
    reader
        .read_line(&mut response_line)
        .map_err(|e| e.to_string())?;
    serde_json::from_str(&response_line).map_err(|e| e.to_string())
}

fn main() {
    let arguments: Vec<String> = std::env::args().skip(1).collect();
    match arguments.first().map(String::as_str) {
        Some("serve") => {
            if let Err(error) = serve(&socket_path()) {
                eprintln!("supervisor: {error}");
                std::process::exit(1);
            }
        }
        Some("ping") => match client_send(&serde_json::json!({"type": "ping"})) {
            Ok(response) => println!("{response}"),
            Err(error) => {
                eprintln!("supervisor: {error}");
                std::process::exit(1);
            }
        },
        Some("status") => match client_send(&serde_json::json!({"type": "status"})) {
            Ok(response) => println!("{response}"),
            Err(error) => {
                eprintln!("supervisor: {error}");
                std::process::exit(1);
            }
        },
        Some("shutdown") => match client_send(&serde_json::json!({"type": "shutdown"})) {
            Ok(_) => {}
            Err(error) => {
                eprintln!("supervisor: {error}");
                std::process::exit(1);
            }
        },
        Some("compile") => {
            // compile <profile> <cwd> <program> [args...]
            let profile = arguments.get(1).cloned().unwrap_or_default();
            let cwd = arguments.get(2).cloned().unwrap_or_default();
            let argv: Vec<String> = arguments.into_iter().skip(3).collect();
            let request = serde_json::json!({
                "type": "compile", "profile": profile, "cwd": cwd, "argv": argv,
            });
            match client_send(&request) {
                Ok(response) => println!("{response}"),
                Err(error) => {
                    eprintln!("supervisor: {error}");
                    std::process::exit(1);
                }
            }
        }
        _ => {
            eprintln!("usage: tectdist-supervisor serve|ping|status|shutdown|compile <profile> <cwd> <program> [args...]");
            std::process::exit(2);
        }
    }
}

#[allow(dead_code)]
trait SkipExt {
    fn skip(self, n: usize) -> Self;
}
impl<T> SkipExt for std::vec::Vec<T> {
    fn skip(mut self, n: usize) -> Self {
        if self.len() >= n {
            self.drain(..n);
        }
        self
    }
}
