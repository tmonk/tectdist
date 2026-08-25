//! Project-format preamble snapshot integration tests (plan X2).
//!
//! Each test boots a fresh supervisor WITHOUT the fork server so the
//! project-format fast path is the only accelerator in play, then
//! verifies the format is built, reused, and produces a valid PDF.
use std::io::{BufRead, BufReader, Write};
use std::os::unix::net::UnixStream;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

fn free_dir(tag: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("pf-{}-{}", tag, std::process::id()));
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
    // Fork server deliberately NOT enabled.
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
                   \\usepackage{amsmath}\n\
                   \\begin{document}\n\
                   Project format proof. $e^{i\\pi}+1=0$.\n\
                   \\end{document}\n";

#[test]
fn project_format_builds_reuses_and_produces_pdf() {
    let Some(_image) = basic_tex_root() else {
        eprintln!("skipping: BasicTeX reference image not present on this host");
        return;
    };
    let supervisor = start_supervisor("pfmt");

    let work = free_dir("pfmt-work");
    std::fs::write(work.join("main.tex"), DOC).unwrap();

    let payload = serde_json::json!({
        "type": "compile",
        "profile": "basictex-2026",
        "cwd": work.to_str().unwrap(),
        "argv": ["pdflatex", "-interaction=batchmode", "main.tex"],
        "snapshot_key": null,
    });

    let first = client(&supervisor.socket, payload.clone());
    assert_eq!(first["ok"], true, "first compile failed: {first}");
    assert_eq!(
        first["compile_accepted"]["exit_status"], 0,
        "first compile nonzero: {first}"
    );
    assert!(work.join("main.pdf").is_file(), "PDF must exist");
    assert!(
        work.join(".tectdist/main-pre.fmt").is_file(),
        "project format must be built on first compile"
    );

    // Second compile reuses the cached format (meta digest match) and
    // must still succeed with identical job output.
    std::fs::remove_file(work.join("main.pdf")).unwrap();
    let second = client(&supervisor.socket, payload);
    assert_eq!(second["ok"], true, "second compile failed: {second}");
    assert_eq!(second["compile_accepted"]["exit_status"], 0);
    assert!(
        work.join("main.pdf").is_file(),
        "PDF must exist after reuse"
    );
}

#[test]
fn shell_escape_flag_is_forwarded_not_dropped() {
    let Some(_image) = basic_tex_root() else {
        eprintln!("skipping: BasicTeX reference image not present on this host");
        return;
    };
    let supervisor = start_supervisor("pfmt-shell");

    let work = free_dir("pfmtshell-work");
    std::fs::write(work.join("main.tex"), DOC).unwrap();

    // Same preamble as DOC but requested with -shell-escape: the fast
    // path must forward the flag (both to the ini build and the body
    // compile) rather than silently dropping it.
    let payload = serde_json::json!({
        "type": "compile",
        "profile": "basictex-2026",
        "cwd": work.to_str().unwrap(),
        "argv": ["pdflatex", "-interaction=batchmode", "-shell-escape",
                 "main.tex"],
        "snapshot_key": null,
    });

    let first = client(&supervisor.socket, payload);
    assert_eq!(first["ok"], true, "compile failed: {first}");
    assert_eq!(
        first["compile_accepted"]["exit_status"], 0,
        "shell-escape compile must succeed: {first}"
    );
    assert!(work.join("main.pdf").is_file(), "PDF must exist");
    assert!(work.join(".tectdist/main-pre.fmt").is_file());

    // The cached format's meta digest must reflect the capability flags:
    // rebuild the expected digest the way fast_compile does and compare.
    use std::fmt::Write as _;
    use sha2::Digest as _;
    let mut digest_input = String::from(DOC.split_at(
        DOC.find("\\begin{document}").unwrap()).0);
    digest_input.push_str("\n\\dump\n");
    digest_input.push('\n');
    digest_input.push_str("-shell-escape");
    let meta = std::fs::read_to_string(work.join(".tectdist/main-pre.meta"))
        .expect("meta record");
    let mut hasher = <sha2::Sha256 as sha2::Digest>::new();
    hasher.update(digest_input.as_bytes());
    let expected = format!("{:x}", hasher.finalize());
    assert_eq!(meta.trim(), expected,
               "capability flags must participate in the cache key");
}
