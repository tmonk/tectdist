//! Adversarial mutation fuzzing of the accelerated chain (plan X2/X4
//! contract: "zero stale-output failures under mutation/fuzz testing").
//!
//! Each iteration mutates the document while PRESERVING byte length and
//! mtime — defeating every cheap invalidation signal — then requires the
//! supervisor to produce output reflecting the NEW content:
//! - body mutation  -> X4 gate must miss; X2 body recompile reflects it
//! - preamble mutation -> X2 format key must change (format rebuild)
//!
//! Seeded RNG keeps failures reproducible.
use std::io::{BufRead, BufReader, Write};
use std::os::unix::net::UnixStream;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

fn free_dir(tag: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("mf-{}-{}", tag, std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

fn basic_tex_root() -> Option<PathBuf> {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../reference/basictex-2026/image");
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

fn start_supervisor(tag: &str, image: &Path) -> Supervisor {
    let dir = free_dir(tag);
    let socket = dir.join("s.sock");
    let exe = env!("CARGO_BIN_EXE_tectdist-supervisor");
    let mut command = Command::new(exe);
    command.arg("serve");
    command.env("TECTDIST_SUPERVISOR_SOCKET", &socket);
    command.env("TECTDIST_ACTION_CACHE", dir.join("cache"));
    command.env("TECTDIST_BASICTEX_ROOT", image);
    command.env("TECTDIST_COMPILE_TIMEOUT_SECS", "120");
    let log = std::fs::File::create(dir.join("serve.log")).unwrap();
    command.stdout(log.try_clone().unwrap()).stderr(log);
    let child = command.spawn().expect("spawn supervisor");
    let supervisor = Supervisor { child, socket, _dir: dir };
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

/// Deterministic xorshift PRNG so failures are reproducible.
struct Rng(u64);

impl Rng {
    fn next(&mut self) -> u64 {
        let mut x = self.0;
        x ^= x << 13;
        x ^= x >> 7;
        x ^= x << 17;
        self.0 = x;
        x
    }

    fn below(&mut self, n: usize) -> usize {
        (self.next() % n as u64) as usize
    }
}

const LETTERS: &[u8] = b"abcdefghijklmnopqrstuvwxyz";

/// Replace one letter occurrence with another, preserving byte length.
/// Returns None when no replaceable letter exists.
fn mutate_same_length(text: &str, rng: &mut Rng) -> Option<String> {
    let bytes = text.as_bytes();
    let positions: Vec<usize> = bytes
        .iter()
        .enumerate()
        .filter(|(_, b)| LETTERS.contains(b))
        .map(|(i, _)| i)
        .collect();
    let pos = *positions.get(rng.below(positions.len()))?;
    let mut new = text.as_bytes().to_vec();
    loop {
        let replacement = LETTERS[rng.below(LETTERS.len())];
        if replacement != new[pos] {
            new[pos] = replacement;
            break;
        }
    }
    Some(String::from_utf8(new).expect("utf8 preserved"))
}

/// Restore `target`'s mtime from `reference` via touch -r.
fn clone_mtime(reference: &Path, target: &Path) {
    Command::new("touch")
        .args(["-r"])
        .arg(reference)
        .arg(target)
        .status()
        .expect("touch -r");
}

#[test]
fn adversarial_mutations_never_serve_stale_output() {
    let Some(image) = basic_tex_root() else {
        eprintln!("skipping: BasicTeX reference image not present on this host");
        return;
    };
    let supervisor = start_supervisor("mfuzz", &image);

    let work = free_dir("mfuzz-work");
    let doc_path = work.join("main.tex");
    // The comment gives the fuzzer a preamble-side byte region that is
    // free to change without breaking LaTeX.
    let base = "\\documentclass{article}\n\
                % preamblemarker qwerty\n\
                \\begin{document}\n\
                Mutation probe seedword.\n\
                \\end{document}\n";
    std::fs::write(&doc_path, base).unwrap();

    let payload = serde_json::json!({
        "type": "compile",
        "profile": "basictex-2026",
        "cwd": work.to_str().unwrap(),
        "argv": ["pdflatex", "-interaction=batchmode", "main.tex"],
        "snapshot_key": null,
    });

    // Warm every cache layer with the pristine document.
    let first = client(&supervisor.socket, payload.clone());
    assert_eq!(first["compile_accepted"]["exit_status"], 0,
               "warm-up compile failed: {first}");

    // pdftotext extraction helper.
    let extract = |pdf: &Path| -> String {
        String::from_utf8_lossy(
            &Command::new("pdftotext")
                .arg(pdf)
                .arg("-")
                .output()
                .expect("pdftotext")
                .stdout,
        )
        .into_owned()
    };

    let mut rng = Rng(0x9E37_79B9_7F4A_7C15);
    let mut last_meta: Option<String> = None;
    let iterations = 8;
    for iteration in 0..iterations {
        let current = std::fs::read_to_string(&doc_path).unwrap();

        // Snapshot mtime reference BEFORE mutating.
        let mtime_ref = work.join(".mtime-ref");
        std::fs::copy(&doc_path, &mtime_ref).unwrap();

        // Alternate between body and preamble mutations, restricted to
        // regions where arbitrary letter changes cannot corrupt LaTeX.
        let mutated = if iteration % 3 == 2 {
            // Preamble-side: mutate only inside the marker comment line.
            let marker = "preamblemarker ";
            let start = current.find(marker).expect("marker present")
                + marker.len();
            let end = current[start..].find('\n').map(|n| start + n)
                .unwrap_or(current.len());
            let region = &current[start..end];
            let region = mutate_same_length(region, &mut rng)
                .expect("comment has letters");
            format!("{}{}{}", &current[..start], region, &current[end..])
        } else {
            // Body-side: mutate only inside the prose sentence.
            let prose = "Mutation probe ";
            let start = current.find(prose).expect("prose present")
                + prose.len();
            let end = current[start..].find('\n').map(|n| start + n)
                .unwrap_or(current.len());
            let region = &current[start..end];
            let region = mutate_same_length(region, &mut rng)
                .expect("prose has letters");
            format!("{}{}{}", &current[..start], region, &current[end..])
        };
        assert_eq!(mutated.len(), current.len(), "length must be preserved");
        assert_ne!(mutated, current, "mutation must change content");

        std::fs::write(&doc_path, &mutated).unwrap();
        clone_mtime(&mtime_ref, &doc_path);
        std::fs::remove_file(&mtime_ref).ok();

        let response = client(&supervisor.socket, payload.clone());
        assert_eq!(
            response["compile_accepted"]["exit_status"], 0,
            "iteration {iteration}: compile failed: {response}"
        );

        let pdf = work.join("main.pdf");
        assert!(pdf.is_file(), "iteration {iteration}: PDF missing");

        let text = extract(&pdf);
        // The strongest check: output must match the CURRENT source's
        // distinctive content. Extract the mutated line from the source
        // and require it verbatim in the PDF text (whitespace-collapsed).
        let collapse = |s: &str| -> String {
            s.split_whitespace().collect::<Vec<_>>().join(" ")
        };
        if iteration % 3 == 2 {
            // Preamble mutation: prove the snapshot key moved by checking
            // the recorded meta digest changed versus the previous round.
            let meta = std::fs::read_to_string(
                work.join(".tectdist/main-pre.meta"),
            )
            .unwrap_or_default();
            if let Some(previous) = last_meta.as_deref() {
                assert_ne!(
                    previous, meta,
                    "iteration {iteration}: STALE FORMAT — preamble \
                     dependency digest did not move"
                );
            }
            last_meta = Some(meta);
        } else {
            let source_line = mutated
                .lines()
                .find(|line| line.contains("Mutation probe"))
                .unwrap_or("");
            if !source_line.is_empty() {
                let needle = collapse(source_line);
                assert!(
                    collapse(&text).contains(&needle),
                    "iteration {iteration}: STALE OUTPUT — PDF text does \
                     not reflect the mutated source.\nexpected line: \
                     {needle:?}\npdf text: {:?}",
                    collapse(&text)
                );
            }
        }
    }
}
