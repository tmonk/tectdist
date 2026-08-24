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
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::io::{BufRead, BufReader, Write};
use std::os::unix::fs::PermissionsExt;
use std::os::unix::net::{UnixListener, UnixStream};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};

const PROTOCOL_VERSION: u32 = 1;

#[derive(Debug, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
enum Request {
    Ping { request_id: Option<u64> },
    Status { request_id: Option<u64> },
    Shutdown { request_id: Option<u64> },
    Compile {
        request_id: Option<u64>,
        profile: String,
        argv: Vec<String>,
        cwd: PathBuf,
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
        active_locks: Vec<String>,
    },
    CompileAccepted {
        exit_status: i32,
        duration_ms: u64,
    },
}

struct SupervisorState {
    started: std::time::Instant,
    compiles_started: AtomicU64,
    compiles_succeeded: AtomicU64,
    compiles_failed: AtomicU64,
    /// Project locks keyed by canonicalised project path.
    project_locks: Mutex<HashMap<PathBuf, u64>>,
}

impl SupervisorState {
    fn new() -> Self {
        Self {
            started: std::time::Instant::now(),
            compiles_started: AtomicU64::new(0),
            compiles_succeeded: AtomicU64::new(0),
            compiles_failed: AtomicU64::new(0),
            project_locks: Mutex::new(HashMap::new()),
        }
    }

    fn status(&self) -> Payload {
        Payload::Status {
            protocol_version: PROTOCOL_VERSION,
            pid: std::process::id(),
            uptime_ms: self.started.elapsed().as_millis() as u64,
            compiles_started: self.compiles_started.load(Ordering::Relaxed),
            compiles_succeeded: self.compiles_succeeded.load(Ordering::Relaxed),
            compiles_failed: self.compiles_failed.load(Ordering::Relaxed),
            active_locks: self.project_locks.lock().map(|locks| {
                locks.keys().map(|path| path.display().to_string()).collect()
            }).unwrap_or_default(),
        }
    }

    /// Acquire a per-project lock; refuses concurrent compiles of one project
    /// while isolating distinct projects from each other.
    fn acquire_lock(&self, project: &Path) -> Result<(), String> {
        let mut locks = self.project_locks.lock().map_err(|_| "lock poisoned")?;
        let key = project.canonicalize().unwrap_or_else(|_| project.to_path_buf());
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
            let key = project.canonicalize().unwrap_or_else(|_| project.to_path_buf());
            locks.remove(&key);
        }
    }
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
            payload: Payload::Pong { protocol_version: PROTOCOL_VERSION },
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
        Request::Compile { request_id, profile, argv, cwd } => {
            state.compiles_started.fetch_add(1, Ordering::Relaxed);
            if let Err(error) = state.acquire_lock(&cwd) {
                state.compiles_failed.fetch_add(1, Ordering::Relaxed);
                return Response {
                    ok: false,
                    request_id,
                    error: Some(error),
                    payload: Payload::Empty,
                };
            }
            // Milestone X2 replaces this with snapshot-based workers; the
            // scaffold executes the exact profile engine directly so BT100
            // semantics hold from day one.
            let outcome = run_profile_compile(&profile, &argv, &cwd);
            state.release_lock(&cwd);
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
                        payload: Payload::CompileAccepted { exit_status, duration_ms },
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
fn run_profile_compile(profile: &str, argv: &[String], cwd: &Path) -> Result<(i32, u64), String> {
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
    let start = std::time::Instant::now();
    let status = std::process::Command::new(binary)
        .args(&argv[1..])
        .current_dir(cwd)
        .env("TEXMFROOT", &root_path)
        .status()
        .map_err(|error| format!("spawn failed: {error}"))?;
    Ok((status.code().unwrap_or(128), start.elapsed().as_millis() as u64))
}

/// Alias so the handler signature reads clearly without importing another
/// type name into scope twice.
type AtomicBoolAlias = std::sync::atomic::AtomicBool;

fn socket_path() -> PathBuf {
    if let Ok(explicit) = std::env::var("TECTDIST_SUPERVISOR_SOCKET") {
        return PathBuf::from(explicit);
    }
    let tmp = std::env::var("TMPDIR").unwrap_or_else(|_| "/tmp".to_string());
    let dir = PathBuf::from(tmp)
        .join(format!(".tectdist-{}", unsafe { libc_getuid() }));
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

    let state = Arc::new(SupervisorState::new());
    let running = Arc::new(std::sync::atomic::AtomicBool::new(true));
    for stream in listener.incoming() {
        if !running.load(Ordering::SeqCst) {
            break;
        }
        let Ok(stream) = stream else { continue };
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
                        respond(&mut writer, &Response {
                            ok: false,
                            request_id: None,
                            error: Some(format!("bad request: {error}")),
                            payload: Payload::Empty,
                        });
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
    let mut stream = UnixStream::connect(socket_path())
        .map_err(|_| "supervisor not running".to_string())?;
    let mut line = serde_json::to_string(request).expect("serialise");
    line.push('\n');
    stream.write_all(line.as_bytes()).map_err(|e| e.to_string())?;
    let mut reader = BufReader::new(stream);
    let mut response_line = String::new();
    reader.read_line(&mut response_line).map_err(|e| e.to_string())?;
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
        Some("ping") => {
            match client_send(&serde_json::json!({"type": "ping"})) {
                Ok(response) => println!("{response}"),
                Err(error) => {
                    eprintln!("supervisor: {error}");
                    std::process::exit(1);
                }
            }
        }
        Some("status") => {
            match client_send(&serde_json::json!({"type": "status"})) {
                Ok(response) => println!("{response}"),
                Err(error) => {
                    eprintln!("supervisor: {error}");
                    std::process::exit(1);
                }
            }
        }
        Some("shutdown") => {
            match client_send(&serde_json::json!({"type": "shutdown"})) {
                Ok(_) => {}
                Err(error) => {
                    eprintln!("supervisor: {error}");
                    std::process::exit(1);
                }
            }
        }
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
