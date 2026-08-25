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
use std::collections::BTreeMap;
use std::path::Path;
use std::process::Command;
use std::time::Instant;

pub const FORMAT_DIR: &str = ".tectdist";
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


const INPUT_CONTROL_WORDS: [&str; 2] = ["\\input", "\\include"];
const MAX_DEP_FILES: usize = 64;

/// Result of scanning text for \input/\include occurrences.
struct DepScan {
    /// Literal braced targets (whitespace before '{' allowed, as TeX does).
    targets: Vec<String>,
    /// True when a brace-less (macro-valued) argument was seen — such
    /// dependencies cannot be resolved without TeX expansion.
    macro_form: bool,
}

/// Scan `text` for \input/\include control words. After the control word
/// TeX skips whitespace; a following '{' introduces a literal target,
/// while a letter or backslash indicates a macro argument.
fn scan_inputs(text: &str) -> DepScan {
    let mut targets = Vec::new();
    let mut macro_form = false;
    for word in INPUT_CONTROL_WORDS {
        let mut from = 0;
        while let Some(rel) = text[from..].find(word) {
            let mut rest = &text[from + rel + word.len()..];
            // Skip whitespace exactly as TeX does after a control word.
            let trimmed = rest.trim_start_matches([' ', '\t', '\n', '\r']);
            let skipped = rest.len() - trimmed.len();
            rest = trimmed;
            match rest.chars().next() {
                Some('{') => {
                    if let Some(end_rel) = rest[1..].find('}') {
                        let target = rest[1..1 + end_rel].trim();
                        if !target.is_empty() && !target.contains('$') {
                            targets.push(target.to_owned());
                        }
                        from += rel + word.len() + skipped + 1 + end_rel + 1;
                        continue;
                    }
                    break; // unbalanced brace: stop scanning this word
                }
                Some(c) if c.is_alphabetic() || c == '\\' => {
                    macro_form = true;
                }
                _ => {}
            }
            from += rel + word.len() + skipped;
            if skipped == 0 && rel + word.len() >= text[from - word.len()..].len() {
                break;
            }
        }
    }
    DepScan { targets, macro_form }
}

fn read_project_tex(
    cwd: &Path,
    target: &str,
) -> Option<(std::path::PathBuf, Vec<u8>)> {
    for candidate in [cwd.join(format!("{target}.tex")), cwd.join(target)] {
        if let Ok(bytes) = std::fs::read(&candidate) {
            return Some((candidate, bytes));
        }
    }
    None
}

/// Digest every file reachable from the initial targets through
/// \input{...}/\include{...}, resolved relative to the project directory
/// and followed RECURSIVELY: a dependency's own inputs are part of the
/// snapshot too. Files that cannot be read are skipped; the engine
/// surfaces them at compile time exactly as a stock run would.
fn dependency_digests_from(
    cwd: &Path,
    initial_targets: &[String],
) -> Vec<(String, String)> {
    let mut out: BTreeMap<String, String> = BTreeMap::new();
    let mut queue: Vec<String> = initial_targets.to_vec();
    while let Some(target) = queue.pop() {
        if out.len() >= MAX_DEP_FILES {
            break; // conservative overflow: rebuild on any change instead
        }
        let Some((path, bytes)) = read_project_tex(cwd, &target) else {
            continue;
        };
        let key = path
            .strip_prefix(cwd)
            .unwrap_or(&path)
            .to_string_lossy()
            .into_owned();
        if out.contains_key(&key) {
            continue; // cycle guard
        }
        out.insert(key.clone(), digest_hex(&bytes));
        // Follow this dependency's own \input/\include edges.
        let text = String::from_utf8_lossy(&bytes).into_owned();
        for nested in scan_inputs(&text).targets {
            if !out.contains_key(&nested) {
                queue.push(nested);
            }
        }
    }
    out.into_iter().collect()
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
pub fn fast_compile(
    image_root: &Path,
    cwd: &Path,
    argv: &[String],
    cancelled: Option<&std::sync::atomic::AtomicBool>,
) -> Result<FastCompile, String> {
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
    // One scanner decides both questions: which literal files the
    // preamble pulls in (tracked, recursively hashed into the cache key)
    // and whether any occurrence uses a macro-valued argument (untrackable
    // without TeX expansion -> decline rather than risk staleness).
    let preamble_scan = scan_inputs(&split.preamble);
    if preamble_scan.macro_form {
        return Err(
            "preamble uses macro-indirected \\input/\\include; needs exact execution"
                .to_string(),
        );
    }

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
    // never served to a restricted run or vice versa, plus the contents of
    // any files the preamble \input's/\includes — editing such a file
    // must rebuild the snapshot even though the preamble text itself is
    // unchanged.
    let mut digest_input = split.preamble.clone();
    for flag in &capability_flags {
        digest_input.push('\n');
        digest_input.push_str(flag);
    }
    for (dep_name, dep_digest) in
        dependency_digests_from(cwd, &preamble_scan.targets)
    {
        digest_input.push('\n');
        digest_input.push_str(&dep_name);
        digest_input.push('=');
        digest_input.push_str(&dep_digest);
    }
    ensure_format(
        image_root,
        cwd,
        &fmt_name,
        &split.preamble,
        &digest_hex(digest_input.as_bytes()),
        &capability_flags,
        cancelled,
    )?;

    // Body file: written next to the format every time (cheap, keeps in
    // sync with source edits).
    let format_dir = cwd.join(FORMAT_DIR);
    let body_file = format_dir.join(format!("{fmt_name}-body.tex"));
    std::fs::write(&body_file, split.body)
        .map_err(|error| format!("cannot write body file: {error}"))?;

    let started = Instant::now();
    let mut body_cmd = Command::new(engine_binary(image_root)?);
    body_cmd
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
        );
    let body_timeout: u64 = std::env::var("TECTDIST_COMPILE_TIMEOUT_SECS")
        .ok()
        .and_then(|value| value.parse().ok())
        .unwrap_or(300);
    let status =
        run_with_timeout(&mut body_cmd, body_timeout, cancelled)?;
    let duration_ms = started.elapsed().as_millis() as u64;
    Ok(FastCompile {
        exit_status: status.code().unwrap_or(-1),
        duration_ms,
    })
}

/// Build the format unless a meta record proves it is current.
#[allow(clippy::too_many_arguments)]
fn ensure_format(
    image_root: &Path,
    cwd: &Path,
    fmt_name: &str,
    preamble: &str,
    cache_digest: &str,
    capability_flags: &[&String],
    cancelled: Option<&std::sync::atomic::AtomicBool>,
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
    let mut ini_cmd = Command::new(&binary);
    ini_cmd
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
        // The ini run executes \input/\include from the preamble; those
        // files live in the project directory, not .tectdist/. Trailing
        // colon keeps the system texmf tree appended.
        .env("TEXINPUTS", format!("{}:", cwd.display()))
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
        ;
    let ini_status = run_with_timeout(&mut ini_cmd, 300, cancelled)?;

    if !ini_status.success() || !fmt_file.is_file() {

        let log = std::fs::read_to_string(format_dir.join(format!("{fmt_name}.log")))
            .map(|log| {
                log.lines()
                    .filter(|line| line.starts_with('!'))
                    .collect::<Vec<_>>()
                    .join("; ")
            })
            .unwrap_or_default();
        return Err(format!(
            "format build failed (exit {:?}) {log}",
            ini_status.code()
        ));
    }
    std::fs::write(&meta_file, cache_digest)
        .map_err(|error| format!("cannot write meta: {error}"))?;
    Ok(())
}

/// Run `cmd` to completion with a hard kill deadline. Returns the raw
/// ExitStatus; a timeout yields Err (callers escalate to exact paths).
fn run_with_timeout(
    cmd: &mut Command,
    timeout_secs: u64,
    cancelled: Option<&std::sync::atomic::AtomicBool>,
) -> Result<std::process::ExitStatus, String> {
    let mut child = cmd
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .spawn()
        .map_err(|error| format!("dispatch failed: {error}"))?;
    let deadline = Instant::now() + std::time::Duration::from_secs(timeout_secs);
    loop {
        match child.try_wait() {
            Ok(Some(status)) => return Ok(status),
            Ok(None) => {
                if let Some(flag) = cancelled {
                    if flag.load(std::sync::atomic::Ordering::SeqCst) {
                        let _ = child.kill();
                        let _ = child.wait();
                        return Err("compile was cancelled".to_string());
                    }
                }
                if Instant::now() >= deadline {
                    let _ = child.kill();
                    let _ = child.wait();
                    return Err(format!(
                        "engine exceeded the {timeout_secs}s limit"
                    ));
                }
                std::thread::sleep(std::time::Duration::from_millis(10));
            }
            Err(error) => return Err(format!("wait failed: {error}")),
        }
    }
}

/// Return the active project-format name for a job stem when a built
/// format exists AND its meta digest matches the CURRENT source preamble.
/// Used by the fork-server composition: a resident worker can preload
/// this format so body compiles skip both process spawn and format load.
pub fn active_format(cwd: &Path, job_stem: &str) -> Option<String> {
    let fmt_name = format!("{job_stem}-pre");
    let format_dir = cwd.join(FORMAT_DIR);
    if !format_dir.join(format!("{fmt_name}.fmt")).is_file() {
        return None;
    }
    let meta = std::fs::read_to_string(
        format_dir.join(format!("{fmt_name}{META_SUFFIX}")),
    )
    .ok()?;
    // The recorded digest covers the preamble text, capability flags and
    // dependency files. Recompute it from the live source to decide
    // whether the cached format is still current.
    let source_path = cwd.join(format!("{job_stem}.tex"));
    let source_text = std::fs::read_to_string(&source_path).ok()?;
    let split = split_source(&source_text)?;
    let mut digest_input = split.preamble.clone();
    // Dependency digests use the same traversal the builder recorded.
    let scan = scan_inputs(&split.preamble);
    if scan.macro_form {
        return None;
    }
    for (dep_name, dep_digest) in
        dependency_digests_from(cwd, &scan.targets)
    {
        digest_input.push('\n');
        digest_input.push_str(&dep_name);
        digest_input.push('=');
        digest_input.push_str(&dep_digest);
    }
    if meta.trim() == digest_hex(digest_input.as_bytes()) {
        Some(fmt_name)
    } else {
        None
    }
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
