//! Fork-server edge-path coverage (plan X1).
//!
//! Since X2 (project format) supersedes the resident worker for standard
//! LaTeX documents, the fork server's own path needs dedicated coverage:
//! documents X2 must DECLINE — here a plain-TeX source without any
//! \begin{document} — must still compile through the resident engine
//! when TECTDIST_USE_FORKSERVER is enabled.

use std::io::{BufRead, BufReader, Write};
use std::os::unix::net::UnixStream;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

fn free_dir(tag: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("fs-{}-{}", tag, std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

fn basic_tex_root() -> Option<PathBuf> {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../reference/basictex-2026/image");
    root.is_dir().then_some(root.canonicalize().unwrap_or(root))
}

fn client(socket: &Path, payload: serde_json::Value) -> serde_json::Value {
    let mut stream = UnixStream::connect(socket).expect("connect");
    stream.write_all(payload.to_string().as_bytes()).unwrap();
    stream.write_all(b"\n").unwrap();
    let mut reader = BufReader::new(stream);
    let mut line = String::new();
    reader.read_line(&mut line).unwrap();
    serde_json::from_str(&line).expect("valid response")
}

#[test]
fn plain_tex_source_compiles_through_fork_server_edge_path() {
    let Some(image) = basic_tex_root() else {
        eprintln!("skipping: BasicTeX reference image not present on this host");
        return;
    };
    let dir = free_dir("fsedge");
    let socket = dir.join("s.sock");
    let exe = env!("CARGO_BIN_EXE_tectdist-supervisor");
    let mut command = Command::new(exe);
    command.arg("serve");
    command.env("TECTDIST_SUPERVISOR_SOCKET", &socket);
    command.env("TECTDIST_ACTION_CACHE", dir.join("cache"));
    command.env("TECTDIST_BASICTEX_ROOT", &image);
    command.env("TECTDIST_USE_FORKSERVER", "1");
    let log = std::fs::File::create(dir.join("serve.log")).unwrap();
    command.stdout(log.try_clone().unwrap()).stderr(log);
    let mut child = command.spawn().expect("spawn supervisor");
    let deadline = Instant::now() + Duration::from_secs(5);
    while Instant::now() < deadline {
        if UnixStream::connect(&socket).is_ok() {
            break;
        }
        std::thread::sleep(Duration::from_millis(20));
    }

    let work = free_dir("fsedge-work");
    // Plain TeX: no \begin{document} anywhere -> X2 declines by design.
    std::fs::write(
        work.join("plain.tex"),
        "Plain TeX fork-server probe.\\vfill\\eject\\end\n",
    )
    .unwrap();

    let payload = serde_json::json!({
        "type": "compile",
        "profile": "basictex-2026",
        "cwd": work.to_str().unwrap(),
        "argv": ["pdftex", "-interaction=batchmode", "plain.tex"],
        "snapshot_key": null,
    });

    let first = client(&socket, payload.clone());
    assert_eq!(first["ok"], true, "plain-TeX compile failed: {first}");
    assert_eq!(
        first["compile_accepted"]["exit_status"], 0,
        "exit nonzero: {first}"
    );
    assert!(work.join("plain.pdf").is_file(), "PDF must exist");

    // Second request: worker reuse path must also succeed.
    let second = client(&socket, payload);
    assert_eq!(second["compile_accepted"]["exit_status"], 0);

    let _ = child.kill();
    let _ = child.wait();
}

#[test]
fn wedged_worker_recovers_via_restart_or_escalation() {
    let Some(image) = basic_tex_root() else {
        eprintln!("skipping: BasicTeX reference image not present on this host");
        return;
    };
    let dir = free_dir("fswedge");
    let socket = dir.join("s.sock");
    let exe = env!("CARGO_BIN_EXE_tectdist-supervisor");
    let mut command = Command::new(exe);
    command.arg("serve");
    command.env("TECTDIST_SUPERVISOR_SOCKET", &socket);
    command.env("TECTDIST_ACTION_CACHE", dir.join("cache"));
    command.env("TECTDIST_BASICTEX_ROOT", &image);
    command.env("TECTDIST_USE_FORKSERVER", "1");
    let log = std::fs::File::create(dir.join("serve.log")).unwrap();
    command.stdout(log.try_clone().unwrap()).stderr(log);
    let mut child = command.spawn().expect("spawn supervisor");
    let deadline = Instant::now() + Duration::from_secs(5);
    while Instant::now() < deadline {
        if UnixStream::connect(&socket).is_ok() {
            break;
        }
        std::thread::sleep(Duration::from_millis(20));
    }

    let work = free_dir("fswedge-work");
    // Plain-TeX source: X2 declines, so the resident worker serves it.
    std::fs::write(
        work.join("plain.tex"),
        "Plain TeX wedge probe.\\vfill\\eject\\end\n",
    )
    .unwrap();

    let payload = serde_json::json!({
        "type": "compile",
        "profile": "basictex-2026",
        "cwd": work.to_str().unwrap(),
        "argv": ["pdftex", "-interaction=batchmode", "plain.tex"],
        "snapshot_key": null,
    });

    // 1. Warm the worker.
    let first = client(&socket, payload.clone());
    assert_eq!(first["compile_accepted"]["exit_status"], 0,
               "warm-up compile failed: {first}");

    // 2. Simulate a wedged transport: destroy the engine socket. The
    //    supervisor must detect the failure, discard the worker, and
    //    still complete this compile (restart or one-shot escalation).
    std::fs::remove_file(work.join(".tectdist-engine.sock")).ok();

    let second = client(&socket, payload.clone());
    assert_eq!(second["ok"], true, "post-wedge compile failed: {second}");
    assert_eq!(
        second["compile_accepted"]["exit_status"], 0,
        "post-wedge exit nonzero: {second}"
    );
    assert!(work.join("plain.pdf").is_file());

    // 3. The next request must also succeed (fresh worker or escalation).
    std::fs::remove_file(work.join("plain.pdf")).ok();
    let third = client(&socket, payload);
    assert_eq!(third["compile_accepted"]["exit_status"], 0);
    assert!(work.join("plain.pdf").is_file());

    let _ = child.kill();
    let _ = child.wait();
}

#[test]
fn cancel_request_aborts_runaway_compile() {
    let Some(image) = basic_tex_root() else {
        eprintln!("skipping: BasicTeX reference image not present on this host");
        return;
    };
    // Long limit so cancellation (not the timeout) does the work.
    let dir = free_dir("fscancel");
    let socket = dir.join("s.sock");
    let exe = env!("CARGO_BIN_EXE_tectdist-supervisor");
    let mut command = Command::new(exe);
    command.arg("serve");
    command.env("TECTDIST_SUPERVISOR_SOCKET", &socket);
    command.env("TECTDIST_ACTION_CACHE", dir.join("cache"));
    command.env("TECTDIST_BASICTEX_ROOT", &image);
    command.env("TECTDIST_COMPILE_TIMEOUT_SECS", "600");
    let log = std::fs::File::create(dir.join("serve.log")).unwrap();
    command.stdout(log.try_clone().unwrap()).stderr(log);
    let mut child = command.spawn().expect("spawn supervisor");
    let deadline = Instant::now() + Duration::from_secs(5);
    while Instant::now() < deadline {
        if UnixStream::connect(&socket).is_ok() {
            break;
        }
        std::thread::sleep(Duration::from_millis(20));
    }

    let work = free_dir("fscancel-work");
    std::fs::write(
        work.join("main.tex"),
        "\\documentclass{article}\n\\begin{document}\n\\loop\\iftrue\\repeat\n\\end{document}\n",
    )
    .unwrap();

    let payload = serde_json::json!({
        "type": "compile",
        "profile": "basictex-2026",
        "cwd": work.to_str().unwrap(),
        "argv": ["pdflatex", "-interaction=batchmode", "main.tex"],
        "snapshot_key": null,
    });

    // Connection A: fire the runaway compile on its own thread.
    let compile_socket = socket.clone();
    let compile_thread = std::thread::spawn(move || {
        let mut stream = UnixStream::connect(&compile_socket).unwrap();
        stream.set_read_timeout(Some(Duration::from_secs(120))).unwrap();
        stream.write_all(payload.to_string().as_bytes()).unwrap();
        stream.write_all(b"\n").unwrap();
        let mut reader = BufReader::new(stream);
        let mut line = String::new();
        reader.read_line(&mut line).unwrap();
        serde_json::from_str::<serde_json::Value>(line.trim()).unwrap()
    });

    // Give the engine a moment to spin up, then cancel from connection B.
    std::thread::sleep(Duration::from_millis(2500));
    let cancel_response = client(&socket, serde_json::json!({
        "type": "cancel",
        "cwd": work.to_str().unwrap(),
    }));
    assert_eq!(cancel_response["ok"], true, "cancel failed: {cancel_response}");
    assert_eq!(
        cancel_response["cancelled"]["delivered"], true,
        "cancel must find the in-flight compile: {cancel_response}"
    );

    // The blocked compile must return promptly as a failure.
    let started = Instant::now();
    let response = compile_thread.join().unwrap();
    let elapsed = started.elapsed();
    assert!(
        elapsed < Duration::from_secs(30),
        "compile must return soon after cancel, took {elapsed:?}"
    );
    assert_eq!(response["ok"], false, "cancelled compile must fail: {response}");

    // Supervisor still healthy.
    let status = client(&socket, serde_json::json!({"type":"status"}));
    assert_eq!(status["ok"], true);

    let _ = child.kill();
    let _ = child.wait();
}

#[test]
fn composed_fork_server_preloads_project_format() {
    let Some(image) = basic_tex_root() else {
        eprintln!("skipping: BasicTeX reference image not present on this host");
        return;
    };
    let dir = free_dir("fscompose");
    let socket = dir.join("s.sock");
    let exe = env!("CARGO_BIN_EXE_tectdist-supervisor");
    let mut command = Command::new(exe);
    command.arg("serve");
    command.env("TECTDIST_SUPERVISOR_SOCKET", &socket);
    command.env("TECTDIST_ACTION_CACHE", dir.join("cache"));
    command.env("TECTDIST_BASICTEX_ROOT", &image);
    command.env("TECTDIST_USE_FORKSERVER", "1");
    command.env("TECTDIST_FORKSERVER_PREFER", "1");
    let log = std::fs::File::create(dir.join("serve.log")).unwrap();
    command.stdout(log.try_clone().unwrap()).stderr(log);
    let mut child = command.spawn().expect("spawn supervisor");
    let deadline = Instant::now() + Duration::from_secs(5);
    while Instant::now() < deadline {
        if UnixStream::connect(&socket).is_ok() {
            break;
        }
        std::thread::sleep(Duration::from_millis(20));
    }

    let work = free_dir("fscompose-work");
    std::fs::write(
        work.join("main.tex"),
        "\\documentclass{article}\n\\begin{document}\nComposed probe one.\n\\end{document}\n",
    )
    .unwrap();

    let payload = serde_json::json!({
        "type": "compile",
        "profile": "basictex-2026",
        "cwd": work.to_str().unwrap(),
        "argv": ["pdflatex", "-interaction=batchmode", "main.tex"],
        "snapshot_key": null,
    });

    // 1. First compile builds the X2 project format (X4 miss -> X2 hit;
    //    the prefer flag only engages when a format is already valid).
    let first = client(&socket, payload.clone());
    assert_eq!(first["compile_accepted"]["exit_status"], 0,
               "first compile failed: {first}");
    assert!(work.join(".tectdist/main-pre.fmt").is_file(),
            "project format must exist after first compile");

    // 2. Second compile takes the COMPOSED fork-server path: resident
    //    worker preloads main-pre.fmt and compiles the paired body.
    std::fs::write(work.join("main.pdf"), b"stale").ok();
    let second = client(&socket, payload.clone());
    assert_eq!(second["compile_accepted"]["exit_status"], 0,
               "composed compile failed: {second}");
    let pdf = work.join("main.pdf");
    assert!(pdf.is_file(), "PDF must be renamed into place");
    assert!(
        pdf.metadata().unwrap().len() > 1000,
        "renamed PDF must be real output, not a stale placeholder"
    );

    // 3. Body edit: format stays valid (preamble unchanged), worker still
    //    serves the NEW content through the composed path.
    std::fs::write(
        work.join("main.tex"),
        "\\documentclass{article}\n\\begin{document}\nComposed probe two.\n\\end{document}\n",
    )
    .unwrap();
    let third = client(&socket, payload);
    assert_eq!(third["compile_accepted"]["exit_status"], 0);

    let _ = child.kill();
    let _ = child.wait();
}
