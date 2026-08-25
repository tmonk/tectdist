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
