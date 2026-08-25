//! Project-format preamble snapshots (plan X2 / §6.4).
//!
//! Builds a per-project dump of the document preamble (`\documentclass` +
//! `\usepackage` state) and compiles the paired body against it. Validated
//! empirically: identical page output at ~2x speed on preamble-heavy
//! documents (287 ms -> 137 ms, babel+amsmath+hyperref).
//!
//! Contract (mirrors mylatexformat.sty's dump-at-begin-document):
//! - `<fmt>.tex` = preamble + `\dump`, built once per preamble digest via
//!   `pdftex -ini "&pdflatex"` with TEXMFROOT set, TEXFORMATS including the
//!   stock fmt dir, and NO TEXMFCNF override (pointing it at the image root
//!   hides texmf.cnf; the engine then loads with compiled-in bounds and
//!   aborts with "! Must increase the hyph_size").
//! - `<fmt>-body.tex` = source starting AT `^\begin{document}`; compiling it
//!   with `&<fmt>` reproduces the full document exactly.
//!
//! Formats live under `<project>/.tectdist/`; kpathsea resolves `&name`
//! from there because TEXFORMATS lists that directory first.

use sha2::{Digest, Sha256};
use std::path::Path;
use std::process::Command;
use std::time::Instant;

const FORMAT_DIR: &str = ".tectdist";
const META_SUFFIX: &str = ".meta";
/// Engines eligible for the preamble-snapshot fast path.
const ELIGIBLE_ENGINES: &[&str] = &["pdflatex", "latex", "pdftex"];

fn digest_hex(bytes: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    format!("{:x}", hasher.finalize())
}

struct Split<'a> {
    /// Preamble text (before ^\begin{document}) plus trailing \dump.
    preamble: String,
    /// Body: source starting at the \begin{document} line.
    body: &'a str,
}

fn split_source(source_text: &str) -> Option<Split<'_>> {
    let needle = "\\begin{document}";
    let mut offsets: Vec<usize> = Vec::new();
    for (index, _) in source_text.match_indices(needle) {
        // Require start-of-line like the validated scripts.
        if index == 0 || source_text.as_bytes()[index - 1] == b'\n' {
            offsets.push(index);
        }
    }
    // Exactly one line-start occurrence must exist. Zero means there is
    // nothing to snapshot; more than one risks splitting inside a
    // verbatim/comment context we cannot parse — fall back to the exact
    // one-shot path instead of gambling on a wrong preamble boundary.
    if offsets.len() != 1 {
        return None;
    }
    let at = offsets[0];
    Some(Split {
        preamble: format!("{}\n\\dump\n", &source_text[..at]),
        body: &source_text[at..],
    })
}

pub struct FastCompile {
    pub exit_status: i32,
    pub duration_ms: u64,
}

/// Attempt the project-format fast path for one compile request.
///
/// Returns Err(reason) when not applicable or on any build/dispatch
/// failure; the caller escalates to the exact one-shot path, preserving
/// BT100 semantics (plan §6.1 item 7).
pub fn fast_compile(image_root: &Path, cwd: &Path, argv: &[String]) -> Result<FastCompile, String> {
    let program = argv.first().ok_or("empty argv")?;
    if !ELIGIBLE_ENGINES.contains(&program.as_str()) {
        return Err(format!("engine '{program}' not eligible"));
    }
    // Requests that move the output or pick their own format escape every
    // assumption this fast path makes:
    // - -output-directory sends the PDF elsewhere while the rebuild gate
    //   only knows about <cwd>/<stem>.pdf;
    // - an explicit -fmt=... or first-line &<name> selects the format,
    //   which our preamble snapshot must not override.
    // All three escalate to the exact one-shot path.
    for arg in argv.iter().skip(1) {
        let text = arg.as_str();
        if text.starts_with("-output-directory")
            || text.starts_with("-fmt=")
            || text.starts_with('&')
        {
            return Err(format!("request uses '{text}'; needs exact execution"));
        }
    }
    // Primary source = last .tex argument (same rule as derive_job_name).
    let source_arg = argv
        .iter()
        .rev()
        .find(|arg| arg.ends_with(".tex") && !arg.contains('='))
        .ok_or("no .tex source in argv")?;
    let source_path = cwd.join(source_arg);
    let source_text = std::fs::read_to_string(&source_path)
        .map_err(|error| format!("cannot read {source_path:?}: {error}"))?;
    let split = split_source(&source_text).ok_or("no \\begin{document} found")?;

    let job_stem = Path::new(source_arg)
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("main")
        .to_owned();

    // Forward every user flag EXCEPT the engine name, the source, and
    // jobname controls (we pin the jobname to keep output paths stable).
    // Dropping flags like -shell-escape or -output-directory would make
    // the fast path diverge from reference semantics (BT100 violation).
    let passthrough: Vec<&String> = argv
        .iter()
        .skip(1)
        .filter(|arg| *arg != source_arg)
        .filter(|arg| {
            let text = arg.as_str();
            !(text == "-jobname"
                || text.starts_with("-jobname=")
                || text.starts_with("-jobname "))
        })
        .collect();
    // Capability flags also shape the ini/dump run.
    let capability_flags: Vec<&String> = passthrough
        .iter()
        .filter(|arg| {
            let text = arg.as_str();
            text.starts_with("-shell") || text.contains("write18")
        })
        .copied()
        .collect();

    let fmt_name = format!("{job_stem}-pre");
    // The cache key includes capability flags so a shell-escape build is
    // never served to a restricted run or vice versa.
    let mut digest_input = split.preamble.clone();
    for flag in &capability_flags {
        digest_input.push('\n');
        digest_input.push_str(flag);
    }
    ensure_format(
        image_root,
        cwd,
        &fmt_name,
        &split.preamble,
        &digest_hex(digest_input.as_bytes()),
        &capability_flags,
    )?;

    // Body file: written next to the format every time (cheap, keeps in
    // sync with source edits).
    let format_dir = cwd.join(FORMAT_DIR);
    let body_file = format_dir.join(format!("{fmt_name}-body.tex"));
    std::fs::write(&body_file, split.body)
        .map_err(|error| format!("cannot write body file: {error}"))?;

    let started = Instant::now();
    let output = Command::new(engine_binary(image_root)?)
        // User flags first, then our pinned controls; duplicates of
        // -interaction are harmless and the LAST occurrence wins, which
        // keeps batchmode/halt-on-error authoritative.
        .args(&passthrough)
        .args([
            "-interaction=batchmode",
            "-halt-on-error",
            "-jobname",
            &job_stem,
            &format!("&{fmt_name}"),
        ])
        // Body lives in <cwd>/.tectdist; reference it relative to cwd.
        .arg(format!(
            "{FORMAT_DIR}/{}",
            body_file.file_name().unwrap().to_string_lossy()
        ))
        .current_dir(cwd)
        .env("TEXMFROOT", image_root)
        .env(
            "TEXFORMATS",
            format!(
                ".:{}:{}:{}:{}",
                format_dir.display(),
                image_root.join("texmf-var/web2c/pdftex").display(),
                image_root.join("texmf-dist/web2c").display(),
                image_root.join("texmf/web2c").display()
            ),
        )
        .env(
            "PATH",
            format!(
                "{}:{}",
                engine_binary(image_root)?
                    .parent()
                    .map(|p| p.display().to_string())
                    .unwrap_or_default(),
                std::env::var("PATH").unwrap_or_default()
            ),
        )
        .output()
        .map_err(|error| format!("engine dispatch failed: {error}"))?;
    let duration_ms = started.elapsed().as_millis() as u64;
    Ok(FastCompile {
        exit_status: output.status.code().unwrap_or(-1),
        duration_ms,
    })
}

/// Build the format unless a meta record proves it is current.
fn ensure_format(
    image_root: &Path,
    cwd: &Path,
    fmt_name: &str,
    preamble: &str,
    cache_digest: &str,
    capability_flags: &[&String],
) -> Result<(), String> {
    let format_dir = cwd.join(FORMAT_DIR);
    std::fs::create_dir_all(&format_dir)
        .map_err(|error| format!("cannot create {FORMAT_DIR}: {error}"))?;
    let fmt_file = format_dir.join(format!("{fmt_name}.fmt"));
    let meta_file = format_dir.join(format!("{fmt_name}{META_SUFFIX}"));

    if fmt_file.is_file() {
        if let Ok(meta) = std::fs::read_to_string(&meta_file) {
            if meta.trim() == cache_digest {
                return Ok(()); // current format, reuse
            }
        }
        // Stale: rebuild over it.
    }

    let pre_file = format_dir.join(format!("{fmt_name}.tex"));
    std::fs::write(&pre_file, preamble)
        .map_err(|error| format!("cannot write preamble: {error}"))?;

    let binary = engine_binary(image_root)?;
    let status = Command::new(&binary)
        .args(["-ini"])
        // Capability flags (e.g. -shell-escape) shape what the preamble
        // may do during the dump; forward them so the snapshot matches
        // the semantics of the request that triggered the build.
        .args(capability_flags.iter().map(|f| f.as_str()))
        .args([
            "-interaction=batchmode",
            "-halt-on-error",
            "&pdflatex",
        ])
        .arg(pre_file.file_name().unwrap().to_string_lossy().as_ref())
        .current_dir(&format_dir)
        .env("TEXMFROOT", image_root)
        .env(
            "TEXFORMATS",
            format!(
                ".:{}:{}:{}",
                format_dir.display(),
                image_root.join("texmf-var/web2c/pdftex").display(),
                image_root.join("texmf-dist/web2c").display()
            ),
        )
        .env(
            "PATH",
            format!(
                "{}:{}",
                binary
                    .parent()
                    .map(|p| p.display().to_string())
                    .unwrap_or_default(),
                std::env::var("PATH").unwrap_or_default()
            ),
        )
        // Deliberately NO TEXMFCNF override — see module docs.
        .output()
        .map_err(|error| format!("format build dispatch failed: {error}"))?;

    if !status.status.success() || !fmt_file.is_file() {
        let tail = String::from_utf8_lossy(&status.stderr);
        let log = std::fs::read_to_string(format_dir.join(format!("{fmt_name}.log")))
            .map(|log| {
                log.lines()
                    .filter(|line| line.starts_with('!'))
                    .collect::<Vec<_>>()
                    .join("; ")
            })
            .unwrap_or_default();
        return Err(format!(
            "format build failed (exit {:?}) {log} {}",
            status.status.code(),
            tail.lines().last().unwrap_or("")
        ));
    }
    std::fs::write(&meta_file, cache_digest)
        .map_err(|error| format!("cannot write meta: {error}"))?;
    Ok(())
}

fn engine_binary(image_root: &Path) -> Result<std::path::PathBuf, String> {
    let mut candidates: Vec<std::path::PathBuf> = image_root
        .join("bin")
        .read_dir()
        .map_err(|error| format!("cannot read bin/: {error}"))?
        .flatten()
        .map(|entry| entry.path())
        .filter(|path| path.is_dir())
        .collect();
    // Deterministic preference: stock platform builds first; instrumented
    // fork-server prototypes ("forkproto") last because their -ini hook
    // changes dump semantics.
    candidates.sort_by_key(|path| {
        (
            path.file_name().and_then(|n| n.to_str()).unwrap_or("") == "universal-darwin",
            path.file_name().and_then(|n| n.to_str()).unwrap_or("") == "forkproto",
        )
    });
    candidates
        .iter()
        .map(|dir| dir.join("pdftex"))
        .find(|binary| binary.is_file())
        .ok_or_else(|| "no pdftex under bin/".to_string())
}
