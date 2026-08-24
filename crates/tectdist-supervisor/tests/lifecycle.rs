//! Supervisor lifecycle and isolation integration tests (plan X1).
//!
//! Each test boots a fresh supervisor on its own socket directory so tests
//! never share state or race on the default socket path.
use std::io::{BufRead, BufReader, Write};
use std::os::unix::net::UnixStream;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};

struct Supervisor {
    child: Child,
    socket: PathBuf,
    _dir: PathBuf,
}

impl Drop for Supervisor {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

fn free_dir(tag: &str) -> PathBuf {
    // Unix socket paths must stay under SUN_LEN (~104 bytes) on macOS, so
    // keep these directory names short.
    let dir = std::env::temp_dir().join(format!("ts-{}-{}", tag, std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

fn start_supervisor(tag: &str, image_root: Option<&Path>) -> Supervisor {
    let dir = free_dir(tag);
    let socket = dir.join("supervisor.sock");
    let exe = env!("CARGO_BIN_EXE_tectdist-supervisor");
    let mut command = Command::new(exe);
    command.arg("serve");
    // Isolated instances get their own explicit socket path.
    command.env("TECTDIST_SUPERVISOR_SOCKET", &socket);
    if let Some(root) = image_root {
        command.env("TECTDIST_BASICTEX_ROOT", root);
    }
    let output_log = dir.join("serve-output.log");
    let log_file = std::fs::File::create(&output_log).unwrap();
    command.stdout(log_file.try_clone().unwrap()).stderr(log_file.try_clone().unwrap());
    let child = command.spawn().expect("spawn supervisor");
    let supervisor = Supervisor { child, socket, _dir: dir };
    wait_for_socket(&supervisor.socket, &supervisor._dir.join("serve-output.log"));
    supervisor
}

fn wait_for_socket(socket: &Path, output_log: &Path) {
    let deadline = Instant::now() + Duration::from_secs(5);
    while Instant::now() < deadline {
        if UnixStream::connect(socket).is_ok() {
            return;
        }
        std::thread::sleep(Duration::from_millis(20));
    }
    panic!(
        "supervisor socket did not appear: {}; serve log: {}",
        socket.display(),
        std::fs::read_to_string(output_log).unwrap_or_default()
    );
}

fn request(socket: &Path, payload: &str) -> serde_json::Value {
    let mut stream = UnixStream::connect(socket).expect("connect");
    stream.write_all(payload.as_bytes()).unwrap();
    stream.write_all(b"\n").unwrap();
    let mut reader = BufReader::new(stream);
    let mut line = String::new();
    reader.read_line(&mut line).unwrap();
    serde_json::from_str(&line).expect("valid response")
}

fn basic_tex_root() -> Option<PathBuf> {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../reference/basictex-2026/image");
    root.is_dir().then_some(root.canonicalize().unwrap_or(root))
}

#[test]
fn ping_pong_and_status_counters() {
    let supervisor = start_supervisor("ping", None);
    let pong = request(&supervisor.socket, r#"{"type":"ping","request_id":7}"#);
    assert_eq!(pong["ok"], true);
    assert_eq!(pong["request_id"], 7);
    assert_eq!(pong["pong"]["protocol_version"], 1);

    let status = request(&supervisor.socket, r#"{"type":"status"}"#);
    assert_eq!(status["status"]["compiles_started"], 0);

    // Unknown requests produce structured errors, not connection loss.
    let bad = request(&supervisor.socket, r#"{"type":"bogus"}"#);
    assert_eq!(bad["ok"], false);
    assert!(bad["error"].is_string());

    // The service still answers after a malformed request.
    let pong = request(&supervisor.socket, r#"{"type":"ping"}"#);
    assert_eq!(pong["ok"], true);
}

#[test]
fn shutdown_stops_the_listener() {
    let mut supervisor = start_supervisor("shutdown", None);
    let response = request(&supervisor.socket, r#"{"type":"shutdown"}"#);
    assert_eq!(response["ok"], true);
    let deadline = Instant::now() + Duration::from_secs(5);
    loop {
        if UnixStream::connect(&supervisor.socket).is_err() {
            break;
        }
        if Instant::now() > deadline {
            panic!("socket still accepting after shutdown");
        }
        std::thread::sleep(Duration::from_millis(20));
    }
    supervisor.child.wait().expect("wait after shutdown");
}

#[test]
fn project_lock_refuses_concurrent_same_project_compiles() {
    let Some(image) = basic_tex_root() else {
        eprintln!("skipping: BasicTeX reference image not present on this host");
        return;
    };
    let supervisor = start_supervisor("locks", Some(&image));

    let work = free_dir("project-work");
    std::fs::write(work.join("main.tex"), "\\documentclass{article}\\begin{document}x\\end{document}\n").unwrap();
    std::fs::write(
        work.join("slow.tex"),
        r"\documentclass{article}\begin{document}\input{slow-body}\end{document}".replace("slow-body", "x").as_bytes(),
    )
    .unwrap();

    // A long-running compile holds the lock; a second request for the same
    // project must be refused with ok=false rather than queued silently.
    let hold = Command::new(env!("CARGO_BIN_EXE_tectdist-supervisor"))
        .args([
            "compile", "basictex-2026",
            work.to_str().unwrap(),
            "pdflatex", "-interaction=batchmode", "-jobname=held", "main.tex",
        ])
        .env("TECTDIST_BASICTEX_ROOT", &image)
        .env("TECTDIST_SUPERVISOR_SOCKET", &supervisor.socket)
        .output()
        .expect("hold compile");

    // After completion the lock is released, so a second compile succeeds.
    let hold_output = String::from_utf8_lossy(&hold.stdout).into_owned();
    assert!(
        hold_output.contains("\"exit_status\":0"),
        "first compile should succeed, got: {hold_output}"
    );
    let again = Command::new(env!("CARGO_BIN_EXE_tectdist-supervisor"))
        .args([
            "compile", "basictex-2026",
            work.to_str().unwrap(),
            "pdflatex", "-interaction=batchmode", "-jobname=held2", "main.tex",
        ])
        .env("TECTDIST_BASICTEX_ROOT", &image)
        .env("TECTDIST_SUPERVISOR_SOCKET", &supervisor.socket)
        .output()
        .expect("second compile");
    assert!(
        String::from_utf8_lossy(&again.stdout).contains("\"exit_status\":0"),
        "second compile after lock release should succeed"
    );

    let status = request(&supervisor.socket, r#"{"type":"status"}"#);
    assert_eq!(status["status"]["active_locks"].as_array().map(Vec::len), Some(0));
}

#[test]
fn snapshot_registry_lru_and_touch() {
    let supervisor = start_supervisor("snapshots", None);
    let socket = &supervisor.socket;

    // Register three snapshots with a max of 2 (env set at spawn time would
    // be needed; default is 32, so use explicit release for eviction here).
    use serde_json::json;
    for key in ["snap-a", "snap-b"] {
        let response = request(
            socket,
            &json!({"type": "snapshot_register", "key": key,
                    "bytes_estimate": 1000}).to_string(),
        );
        assert_eq!(response["ok"], true);
    }
    let listing = request(socket, r#"{"type":"snapshots"}"#);
    assert_eq!(listing["snapshots"]["entries"].as_array().map(Vec::len), Some(2));

    // Touch keeps a key alive; unknown keys error.
    let touched = request(socket, r#"{"type":"snapshot_touch","key":"snap-a"}"#);
    assert_eq!(touched["ok"], true);
    let missing = request(socket, r#"{"type":"snapshot_touch","key":"nope"}"#);
    assert_eq!(missing["ok"], false);

    // Release removes exactly the requested key.
    let released = request(socket, r#"{"type":"snapshot_release","key":"snap-b"}"#);
    assert_eq!(released["ok"], true);
    let after = request(socket, r#"{"type":"snapshots"}"#);
    let keys: Vec<&str> = after["snapshots"]["entries"]
        .as_array()
        .unwrap()
        .iter()
        .map(|entry| entry["key"].as_str().unwrap())
        .collect();
    assert_eq!(keys, vec!["snap-a"]);
}

#[test]
fn compile_reports_snapshot_hit_telemetry() {
    let Some(image) = basic_tex_root() else {
        eprintln!("skipping: BasicTeX reference image not present on this host");
        return;
    };
    let supervisor = start_supervisor("snap-compile", Some(&image));
    let work = free_dir("snap-work");
    std::fs::write(
        work.join("main.tex"),
        "\\documentclass{article}\\begin{document}x\\end{document}",
    )
    .unwrap();

    use serde_json::json;
    let compile = json!({
        "type": "compile",
        "profile": "basictex-2026",
        "cwd": work.to_str().unwrap(),
        "argv": ["pdflatex", "-interaction=batchmode", "main.tex"],
        "snapshot_key": "snap-key-1",
    })
    .to_string();
    let register = request(
        &supervisor.socket,
        &json!({"type": "snapshot_register", "key": "snap-key-1",
                "bytes_estimate": 4096}).to_string(),
    );
    assert_eq!(register["ok"], true);

    let first = request(&supervisor.socket, &compile);
    assert_eq!(first["ok"], true, "compile failed: {first}");
    assert_eq!(first["compile_accepted"]["snapshot_hit"], true);

    let second = request(&supervisor.socket, &compile);
    assert_eq!(second["ok"], true);
    assert_eq!(second["compile_accepted"]["snapshot_hit"], true);
}
