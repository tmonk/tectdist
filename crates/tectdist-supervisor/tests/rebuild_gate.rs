//! Unchanged-rebuild gate integration tests (plan X4 / X10-E scenario 1).
use std::io::{BufRead, BufReader, Write};
use std::os::unix::net::UnixStream;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

fn free_dir(tag: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("rg-{}-{}", tag, std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

fn basic_tex_root() -> Option<PathBuf> {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../reference/basictex-2026/image");
    root.is_dir().then_some(root.canonicalize().unwrap_or(root))
}

struct Supervisor {
    child: std::process::Child,
    socket: PathBuf,
    _dir: PathBuf,
}

impl Drop for Supervisor {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

fn start_supervisor(tag: &str) -> Supervisor {
    let dir = free_dir(tag);
    let socket = dir.join("s.sock");
    let exe = env!("CARGO_BIN_EXE_tectdist-supervisor");
    let mut command = Command::new(exe);
    command.arg("serve");
    command.env("TECTDIST_SUPERVISOR_SOCKET", &socket);
    command.env("TECTDIST_ACTION_CACHE", dir.join("cache"));
    if let Some(root) = basic_tex_root() {
        command.env("TECTDIST_BASICTEX_ROOT", &root);
    }
    let log = std::fs::File::create(dir.join("serve.log")).unwrap();
    command.stdout(log.try_clone().unwrap()).stderr(log);
    let child = command.spawn().expect("spawn supervisor");
    let supervisor = Supervisor {
        child,
        socket,
        _dir: dir,
    };
    let deadline = Instant::now() + Duration::from_secs(5);
    while Instant::now() < deadline {
        if UnixStream::connect(&supervisor.socket).is_ok() {
            return supervisor;
        }
        std::thread::sleep(Duration::from_millis(20));
    }
    panic!("supervisor socket never appeared");
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

const DOC: &str = "\\documentclass{article}\n\
                   \\begin{document}\n\
                   Rebuild gate proof.\n\
                   \\end{document}\n";

#[test]
fn unchanged_recompile_is_served_from_cache() {
    let Some(_image) = basic_tex_root() else {
        eprintln!("skipping: BasicTeX reference image not present on this host");
        return;
    };
    let supervisor = start_supervisor("gate");

    let work = free_dir("gate-work");
    std::fs::write(work.join("main.tex"), DOC).unwrap();

    let payload = serde_json::json!({
        "type": "compile",
        "profile": "basictex-2026",
        "cwd": work.to_str().unwrap(),
        "argv": ["pdflatex", "-interaction=batchmode", "main.tex"],
        "snapshot_key": null,
    });

    // First compile: cold miss, runs an engine.
    let first = client(&supervisor.socket, payload.clone());
    assert_eq!(first["ok"], true, "first compile failed: {first}");
    assert_eq!(first["compile_accepted"]["exit_status"], 0);

    // Status before: zero cache hits.
    let status0 = client(&supervisor.socket, serde_json::json!({"type":"status"}));
    assert_eq!(
        status0["status"]["compiles_cache_hits"], 0,
        "no hits expected yet: {status0}"
    );

    // Second compile with UNCHANGED inputs must be served from cache.
    let second = client(&supervisor.socket, payload.clone());
    assert_eq!(second["ok"], true, "second compile failed: {second}");
    assert_eq!(second["compile_accepted"]["exit_status"], 0);

    let status1 = client(&supervisor.socket, serde_json::json!({"type":"status"}));
    assert_eq!(
        status1["status"]["compiles_cache_hits"], 1,
        "unchanged recompile should be a cache hit: {status1}"
    );

    // Editing the source invalidates the gate; next compile is a real run.
    std::fs::write(
        work.join("main.tex"),
        DOC.replace("Rebuild gate proof.", "Edited content."),
    )
    .unwrap();
    let third = client(&supervisor.socket, payload);
    assert_eq!(third["ok"], true, "edited compile failed: {third}");
    assert_eq!(third["compile_accepted"]["exit_status"], 0);

    let status2 = client(&supervisor.socket, serde_json::json!({"type":"status"}));
    assert_eq!(
        status2["status"]["compiles_cache_hits"], 1,
        "edited recompile must NOT be a cache hit: {status2}"
    );
}

#[test]
fn subdirectory_input_edit_invalidates_gate() {
    let Some(_image) = basic_tex_root() else {
        eprintln!("skipping: BasicTeX reference image not present on this host");
        return;
    };
    let supervisor = start_supervisor("gate-sub");

    let work = free_dir("gatesub-work");
    std::fs::create_dir_all(work.join("chapters")).unwrap();
    std::fs::write(
        work.join("main.tex"),
        "\\documentclass{article}\n\\begin{document}\n\\input{chapters/ch1}\n\\end{document}\n",
    )
    .unwrap();
    std::fs::write(work.join("chapters/ch1.tex"), "Chapter one.\n").unwrap();

    let payload = serde_json::json!({
        "type": "compile",
        "profile": "basictex-2026",
        "cwd": work.to_str().unwrap(),
        "argv": ["pdflatex", "-interaction=batchmode", "main.tex"],
        "snapshot_key": null,
    });

    // First compile: real run, chain recorded (recursive snapshot).
    let first = client(&supervisor.socket, payload.clone());
    assert_eq!(first["ok"], true, "first compile failed: {first}");
    assert_eq!(first["compile_accepted"]["exit_status"], 0);

    // Unchanged recompile: cache hit.
    let _second = client(&supervisor.socket, payload.clone());
    let status0 = client(&supervisor.socket, serde_json::json!({"type":"status"}));
    assert_eq!(
        status0["status"]["compiles_cache_hits"], 1,
        "unchanged recompile should hit: {status0}"
    );

    // Editing the \input'ed SUBDIRECTORY file must invalidate the gate.
    std::fs::write(work.join("chapters/ch1.tex"), "Chapter one revised.\n")
        .unwrap();
    let third = client(&supervisor.socket, payload);
    assert_eq!(third["ok"], true, "post-edit compile failed: {third}");
    assert_eq!(third["compile_accepted"]["exit_status"], 0);

    let status1 = client(&supervisor.socket, serde_json::json!({"type":"status"}));
    assert_eq!(
        status1["status"]["compiles_cache_hits"], 1,
        "subdir edit must NOT be served from cache: {status1}"
    );
}

#[test]
fn external_artifact_change_invalidates_gate() {
    let Some(_image) = basic_tex_root() else {
        eprintln!("skipping: BasicTeX reference image not present on this host");
        return;
    };
    let supervisor = start_supervisor("gate-art");

    let work = free_dir("gateart-work");
    std::fs::write(work.join("main.tex"), DOC).unwrap();

    let payload = serde_json::json!({
        "type": "compile",
        "profile": "basictex-2026",
        "cwd": work.to_str().unwrap(),
        "argv": ["pdflatex", "-interaction=batchmode", "main.tex"],
        "snapshot_key": null,
    });

    // Build + record; then an unchanged recompile hits.
    let first = client(&supervisor.socket, payload.clone());
    assert_eq!(first["compile_accepted"]["exit_status"], 0);
    let _second = client(&supervisor.socket, payload.clone());
    let status0 = client(&supervisor.socket, serde_json::json!({"type":"status"}));
    assert_eq!(status0["status"]["compiles_cache_hits"], 1);

    // An externally modified artifact (as bibtex rewriting .bbl, or a
    // shell-escape script regenerating data) must invalidate: the gate
    // hashes EVERY project file, no extension whitelist.
    let aux = work.join("main.aux");
    let mut content = std::fs::read_to_string(&aux).unwrap();
    content.push_str("% external touch\n");
    std::fs::write(&aux, content).unwrap();

    let third = client(&supervisor.socket, payload);
    assert_eq!(third["compile_accepted"]["exit_status"], 0);

    let status1 = client(&supervisor.socket, serde_json::json!({"type":"status"}));
    assert_eq!(
        status1["status"]["compiles_cache_hits"], 1,
        "artifact edit must NOT be served from cache: {status1}"
    );
}

#[test]
fn runaway_compile_hits_limit_and_supervisor_survives() {
    let Some(_image) = basic_tex_root() else {
        eprintln!("skipping: BasicTeX reference image not present on this host");
        return;
    };
    // Dedicated supervisor with a 3-second compile limit.
    let dir = free_dir("gate-limit");
    let socket = dir.join("s.sock");
    let exe = env!("CARGO_BIN_EXE_tectdist-supervisor");
    let mut command = Command::new(exe);
    command.arg("serve");
    command.env("TECTDIST_SUPERVISOR_SOCKET", &socket);
    command.env("TECTDIST_ACTION_CACHE", dir.join("cache"));
    if let Some(root) = basic_tex_root() {
        command.env("TECTDIST_BASICTEX_ROOT", &root);
    }
    command.env("TECTDIST_COMPILE_TIMEOUT_SECS", "3");
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

    let work = free_dir("gatelimit-work");
    // Infinite loop document: \loop ... \repeat never terminates.
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

    // X2 fast path declines? No — it has a begin-document; the fast path
    // itself must time out OR the one-shot escalation must. Either way
    // the request returns an error response rather than hanging, and the
    // supervisor stays alive.
    let started = Instant::now();
    let stream_result = UnixStream::connect(&socket);
    assert!(stream_result.is_ok());
    let mut stream = stream_result.unwrap();
    stream
        .set_read_timeout(Some(Duration::from_secs(120)))
        .unwrap();
    stream.write_all(payload.to_string().as_bytes()).unwrap();
    stream.write_all(b"\n").unwrap();
    let mut reader = BufReader::new(stream);
    let mut line = String::new();
    reader.read_line(&mut line).unwrap();
    let elapsed = started.elapsed();

    assert!(
        elapsed < Duration::from_secs(60),
        "request must return after the limit, took {elapsed:?}"
    );
    let response: serde_json::Value =
        serde_json::from_str(line.trim()).unwrap_or(serde_json::json!({}));
    let errored = response["ok"] == false
        || response["error"].is_string()
        || response["compile_accepted"]["exit_status"].as_i64().unwrap_or(0) != 0;
    assert!(errored, "runaway compile must not report success: {response}");

    // Supervisor must still respond afterwards.
    let status = client(&socket, serde_json::json!({"type":"status"}));
    assert_eq!(status["ok"], true, "supervisor dead after timeout: {status}");

    let _ = child.kill();
    let _ = child.wait();
}
