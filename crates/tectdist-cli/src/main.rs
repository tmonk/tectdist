use std::env;
use std::ffi::OsString;
use std::fs;
use std::path::{Path, PathBuf};
use std::io::Write as IoWrite;
use std::os::unix::net::UnixStream;
use std::process::Command;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use tectdist_core::{CompilationPlan, EngineSelection, IndexStrategy, ResolvedExternalEngine};
#[cfg(feature = "embedded")]
use tectdist_engine::EmbeddedTectonicExecutor;
use tectdist_engine::{Executor, ExternalTectonicExecutor};

const TECTONIC_PAIR: &str = "0.17";
const BIBER_PAIR: &str = "2.17";
const PAIRING_TTL_SECS: u64 = 24 * 60 * 60;

fn invoked_name(arg0: &OsString) -> OsString {
    Path::new(arg0).file_name().unwrap_or(arg0).to_os_string()
}
fn engine() -> PathBuf {
    env::var_os("TECTONIC")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("tectonic"))
}

fn version_pair(text: &str) -> Option<String> {
    let mut numbers = text
        .split(|character: char| !character.is_ascii_digit() && character != '.')
        .filter(|part| !part.is_empty());
    let candidate = numbers.next()?;
    let mut components = candidate.split('.');
    Some(format!("{}.{}", components.next()?, components.next()?))
}

fn pairing_cache_path() -> PathBuf {
    std::env::temp_dir().join("tectdist-pairing-v1")
}

fn engine_identity(path: &Path) -> Option<(PathBuf, u128)> {
    let canonical = path.canonicalize().ok()?;
    let modified = canonical
        .metadata()
        .ok()?
        .modified()
        .ok()?
        .duration_since(UNIX_EPOCH)
        .ok()?
        .as_nanos();
    Some((canonical, modified))
}

fn cached_pair(path: &Path, modified: u128) -> Option<String> {
    let metadata = fs::metadata(pairing_cache_path()).ok()?;
    if metadata.modified().ok()?.elapsed().ok()?.as_secs() > PAIRING_TTL_SECS {
        return None;
    }
    let contents = fs::read_to_string(pairing_cache_path()).ok()?;
    let mut fields = contents.lines();
    let cached_path = PathBuf::from(fields.next()?.strip_prefix("path=")?);
    let cached_modified = fields
        .next()?
        .strip_prefix("mtime=")?
        .parse::<u128>()
        .ok()?;
    let pair = fields.next()?.strip_prefix("pair=")?.to_owned();
    (cached_path == path && cached_modified == modified).then_some(pair)
}

fn write_cached_pair(path: &Path, modified: u128, pair: &str) {
    let destination = pairing_cache_path();
    let temporary = destination.with_extension(format!("{}.tmp", std::process::id()));
    let payload = format!("path={}\nmtime={modified}\npair={pair}\n", path.display());
    if fs::write(&temporary, payload).is_ok() {
        let _ = fs::rename(temporary, destination);
    }
}

fn check_external_pairing(path: &Path) -> Result<(), String> {
    if env::var_os("TECTDIST_SKIP_PAIRING").is_some() {
        return Ok(());
    }
    let Some((canonical, modified)) = engine_identity(path) else {
        // Preserve the reference behavior for a missing or fake engine: the
        // eventual direct execution error is more useful than a pairing error.
        return Ok(());
    };
    let pair = if let Some(pair) = cached_pair(&canonical, modified) {
        pair
    } else {
        let output = Command::new(path).arg("--version").output().ok();
        let pair = output
            .filter(|output| output.status.success())
            .and_then(|output| String::from_utf8(output.stdout).ok())
            .and_then(|text| version_pair(&text));
        let Some(pair) = pair else {
            return Ok(());
        };
        write_cached_pair(&canonical, modified, &pair);
        pair
    };
    if pair == TECTONIC_PAIR {
        Ok(())
    } else {
        Err(format!(
            "tectdist 0.2.2 requires Tectonic {TECTONIC_PAIR}.x, but the configured engine is {pair}.x; a mismatched engine can break biblatex/Biber compatibility. Use a matching engine or select a matched tectdist release."
        ))
    }
}

fn command_first_line(command: &Path, argument: &str) -> Option<String> {
    Command::new(command)
        .arg(argument)
        .output()
        .ok()
        .and_then(|output| {
            if output.status.success() {
                String::from_utf8(output.stdout)
                    .ok()
                    .and_then(|text| text.lines().next().map(str::to_owned))
            } else {
                None
            }
        })
}

/// Buffered opt-in JSON-lines timing sink. This deliberately mirrors the
/// Python reference's `TECTDIST_TRACE_FILE` contract without adding a runtime
/// logging dependency to the native fast path.
///
/// Spans are accumulated in memory and written once at process exit (or when
/// the buffer grows large), so tracing never opens the trace file per span.
/// Timestamps are derived from elapsed durations, so buffered records carry
/// the same start/duration values an unbuffered writer would have produced.
mod trace_sink {
    use super::{Duration, SystemTime, UNIX_EPOCH};
    use std::io::Write;
    use std::path::PathBuf;
    use std::sync::{Mutex, OnceLock};

    /// Flush before this many buffered bytes to bound memory on long runs.
    const FLUSH_THRESHOLD_BYTES: usize = 1 << 20;

    struct State {
        resolved: bool,
        path: Option<PathBuf>,
        buffer: String,
    }

    static STATE: OnceLock<Mutex<State>> = OnceLock::new();

    extern "C" fn flush_at_exit() {
        flush();
    }

    fn state() -> &'static Mutex<State> {
        STATE.get_or_init(|| {
            #[cfg(unix)]
            unsafe {
                // std::process::exit skips destructors; atexit still runs.
                libc::atexit(flush_at_exit);
            }
            Mutex::new(State { resolved: false, path: None, buffer: String::new() })
        })
    }

    fn write_buffer(path: &PathBuf, buffer: &mut String) {
        if buffer.is_empty() {
            return;
        }
        if let Ok(mut file) = std::fs::OpenOptions::new().create(true).append(true).open(path) {
            let _ = file.write_all(buffer.as_bytes());
        }
        buffer.clear();
    }

    pub fn flush() {
        if let Ok(mut state) = state().lock() {
            if let Some(path) = state.path.clone() {
                write_buffer(&path, &mut state.buffer);
            }
        }
    }

    pub fn record(name: &str, elapsed: Duration, status: Option<i32>) -> Option<()> {
        let end_ns = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|duration| duration.as_nanos())
            .unwrap_or(0);
        let duration_ns = elapsed.as_nanos();
        let start_ns = end_ns.saturating_sub(duration_ns);
        let status_field = status
            .map(|value| format!(",\"status\":{value}"))
            .unwrap_or_default();
        let line = format!(
            "{{\"schema_version\":1,\"span\":\"{name}\",\"start_ns\":{start_ns},\"duration_ns\":{duration_ns}{status_field}}}\n"
        );
        let mut state = state().lock().ok()?;
        if !state.resolved {
            state.resolved = true;
            state.path = std::env::var_os("TECTDIST_TRACE_FILE").map(PathBuf::from);
        }
        match state.path.clone() {
            None => {}
            Some(path) => {
                state.buffer.push_str(&line);
                if state.buffer.len() >= FLUSH_THRESHOLD_BYTES {
                    write_buffer(&path, &mut state.buffer);
                }
            }
        }
        Some(())
    }
}

fn trace_span(name: &str, elapsed: std::time::Duration, status: Option<i32>) {
    let _ = trace_sink::record(name, elapsed, status);
}

fn doctor(json: bool) -> i32 {
    let embedded = cfg!(feature = "embedded");
    let mode = env::var("TECTDIST_ENGINE_MODE").unwrap_or_else(|_| {
        if embedded {
            "embedded".into()
        } else {
            "external".into()
        }
    });
    if mode != "external" && mode != "embedded" {
        eprintln!("tectdist: unknown engine mode '{mode}'");
        return 2;
    }
    let tectonic = if mode == "external" {
        command_first_line(&engine(), "--version")
    } else {
        Some("tectonic 0.17.0 (embedded)".into())
    };
    let biber = command_first_line(Path::new("biber"), "--version");
    let bundle_source = env::var("TECTDIST_BUNDLE_SOURCE").unwrap_or_else(|_| "default".into());
    let bundle_identity = env::var("TECTDIST_BUNDLE_ID").unwrap_or_else(|_| "default".into());
    let bundle_manifest =
        env::var("TECTDIST_BUNDLE_MANIFEST_SHA256").unwrap_or_else(|_| "unknown".into());
    let format_cache_identity =
        env::var("TECTDIST_FORMAT_CACHE_ID").unwrap_or_else(|_| "runtime-default".into());
    let basictex_profile = env::var("TECTDIST_PROFILE").unwrap_or_else(|_| "default".into());
    let basictex_root = tectdist_core::runtime::detect_runtime_pack_source()
        .map(|source| match source {
            tectdist_core::runtime::RuntimePackSource::TectdistRoot(path)
            | tectdist_core::runtime::RuntimePackSource::LegacyImageRoot(path) => {
                path.to_string_lossy().to_string()
            }
        })
        .unwrap_or_default();
    let image_digest = PathBuf::from(&basictex_root)
        .join("image-manifest.json")
        .read_file_ok()
        .and_then(|text| {
            text.split("\"image_files_sha256\": \"").nth(1)
                .and_then(|rest| rest.split('"').next().map(str::to_string))
        })
        .unwrap_or_default();
    let tectonic_ok = tectonic.as_deref().and_then(version_pair).as_deref() == Some(TECTONIC_PAIR);
    let biber_ok = biber.as_deref().and_then(version_pair).as_deref() == Some(BIBER_PAIR);
    let ok = tectonic_ok && biber_ok;
    if json {
        // These values originate from version banners and contain no user
        // supplied data. Escape the only JSON-sensitive characters anyway.
        let esc = |value: Option<String>| {
            value
                .unwrap_or_default()
                .replace('\\', "\\\\")
                .replace('"', "\\\"")
        };
            println!("{{\"tectdist\":\"0.2.2\",\"executor\":{{\"mode\":\"{}\",\"embedded\":{},\"external_fallback_available\":true}},\"profile\":{{\"name\":\"{}\",\"basictex_root\":\"{}\",\"image_files_sha256\":\"{}\"}},\"declared\":{{\"tectonic\":\"{}\",\"biber\":\"{}\"}},\"bundle\":{{\"source\":\"{}\",\"identity\":\"{}\",\"manifest_sha256\":\"{}\",\"format_cache_identity\":\"{}\"}},\"engine\":\"{}\",\"biber\":\"{}\",\"ok\":{}}}", mode, embedded, esc(Some(basictex_profile)), esc(Some(basictex_root)), esc(Some(image_digest)), TECTONIC_PAIR, BIBER_PAIR, esc(Some(bundle_source)), esc(Some(bundle_identity)), esc(Some(bundle_manifest)), esc(Some(format_cache_identity)), esc(tectonic), esc(biber), ok);
    } else {
        println!("tectdist 0.2.2 doctor\n  executor:   {} (embedded: {}; external fallback: yes)\n  profile:    {} (root: {}; image: {})\n  declared:   tectonic {}.x + biber {}\n  bundle:     {} from {} (manifest: {}; format cache: {})\n  engine:     {}\n  biber:      {}\n  verdict:    {}", mode, embedded, basictex_profile, basictex_root, if image_digest.is_empty() { "not configured" } else { &image_digest }, TECTONIC_PAIR, BIBER_PAIR, bundle_identity, bundle_source, bundle_manifest, format_cache_identity, tectonic.unwrap_or_else(|| "NOT FOUND".into()), biber.unwrap_or_else(|| "NOT FOUND".into()), if ok { "PAIR OK" } else { "MISMATCH" });
    }
    if ok {
        0
    } else {
        1
    }
}

trait ReadFileOk {
    fn read_file_ok(&self) -> Option<String>;
}
impl ReadFileOk for PathBuf {
    fn read_file_ok(&self) -> Option<String> {
        fs::read_to_string(self).ok()
    }
}

fn print_group(label: &str, values: &[&str]) {
    println!("  {label}: {}", values.join(" "));
}

fn tools_text() {
    println!("tectdist-compatible commands:");
    print_group("engines", tectdist_tools::ENGINE_ALIASES);
    let mut helpers = Vec::new();
    helpers.extend_from_slice(tectdist_tools::STUB_BIB);
    helpers.extend_from_slice(tectdist_tools::PROXY_OR_STUB);
    helpers.extend_from_slice(tectdist_tools::STUB_DVI);
    helpers.extend_from_slice(tectdist_tools::SILENT_STUBS);
    helpers.extend_from_slice(tectdist_tools::INFORMATIVE_MAINTENANCE);
    helpers.extend_from_slice(tectdist_tools::FONT_STUBS);
    helpers.extend_from_slice(tectdist_tools::METAFONT_STUBS);
    helpers.extend_from_slice(tectdist_tools::CONTEXT_STUBS);
    helpers.extend_from_slice(tectdist_tools::SPECIAL_STUBS);
    helpers.push("kpsewhich");
    print_group("helpers", &helpers);
    let mut real = Vec::new();
    real.extend_from_slice(tectdist_tools::GS_TOOLS);
    real.extend_from_slice(tectdist_tools::PROXIES);
    print_group("real", &real);
    print_group("driver", &["latexmk"]);
}

fn kpsewhich(arguments: Vec<OsString>) -> i32 {
    let mut variable: Option<String> = None;
    let mut name: Option<OsString> = None;
    let mut format: Option<String> = None;
    let mut pending: Option<&str> = None;
    for argument in arguments {
        let text = argument.to_string_lossy();
        if let Some(kind) = pending.take() {
            match kind {
                "var" => variable = Some(text.into_owned()),
                "format" => format = Some(text.into_owned()),
                _ => {}
            }
            continue;
        }
        if let Some(value) = text.strip_prefix("-var-value=") {
            variable = Some(value.into());
        } else if text == "-var-value" {
            pending = Some("var");
        } else if let Some(value) = text.strip_prefix("-format=") {
            format = Some(value.into());
        } else if text == "-format" {
            pending = Some("format");
        } else if matches!(text.as_ref(), "-version" | "--version" | "-v") {
            println!("kpsewhich (tectdist, Tectonic 0.17.0)");
            return 0;
        } else if matches!(text.as_ref(), "-help" | "--help" | "-h") {
            println!("usage: kpsewhich [options] filename...");
            return 0;
        } else if text.starts_with('-') {
            // Compatible no-op options never expose arbitrary environment.
            if text == "-progname" || text == "-interaction" || text == "-debug" {
                pending = Some("ignored");
            }
        } else if name.is_none() {
            name = Some(argument);
        }
    }
    if let Some(variable) = variable {
        if !tectdist_tools::ENGINE_PATH_VARS.contains(&variable.as_str()) {
            eprintln!("kpsewhich: unknown variable '{variable}'");
            return 1;
        }
        println!("{}", env::var(&variable).unwrap_or_default());
        return 0;
    }
    let Some(name) = name else {
        return 1;
    };
    let direct = PathBuf::from(&name);
    if direct.is_file() {
        println!("{}", direct.display());
        return 0;
    }
    let variables: &[&str] = match format.as_deref().map(str::to_ascii_lowercase).as_deref() {
        Some("tex" | "sty" | "cls") => &["TEXINPUTS"],
        Some("bib") => &["BIBINPUTS"],
        Some("bst") => &["BSTINPUTS"],
        Some("ist") => &["INDEXSTYLE"],
        _ => tectdist_tools::ENGINE_PATH_VARS,
    };
    for variable in variables {
        let Ok(paths) = env::var(variable) else {
            continue;
        };
        for directory in paths.split(':') {
            let directory = if directory.is_empty() { "." } else { directory };
            let candidate = Path::new(directory).join(&name);
            if candidate.is_file() {
                println!("{}", candidate.display());
                return 0;
            }
        }
    }
    1
}

fn run_command(program: &Path, arguments: Vec<OsString>) -> i32 {
    match Command::new(program).args(arguments).status() {
        Ok(status) => status.code().unwrap_or(128),
        Err(error) => {
            eprintln!("tectdist: {}: {error}", program.display());
            127
        }
    }
}

fn external_tool_timeout() -> Duration {
    if let Some(milliseconds) = env::var("TECTDIST_EXTERNAL_TOOL_TIMEOUT_MS")
        .ok()
        .and_then(|value| value.parse::<u64>().ok())
    {
        return Duration::from_millis(milliseconds.max(1));
    }
    let seconds = env::var("TECTDIST_EXTERNAL_TOOL_TIMEOUT_SECS")
        .ok()
        .and_then(|value| value.parse::<u64>().ok())
        .unwrap_or(120);
    Duration::from_secs(seconds.max(1))
}

fn run_external_tool(command: &mut Command) -> std::io::Result<std::process::ExitStatus> {
    let mut child = command.spawn()?;
    let timeout = external_tool_timeout();
    if !cfg!(unix) {
        // Portable fallback: bounded polling on platforms without a direct
        // kill-from-watchdog facility.
        let deadline = Instant::now() + timeout;
        loop {
            if let Some(status) = child.try_wait()? {
                return Ok(status);
            }
            if Instant::now() >= deadline {
                let _ = child.kill();
                let _ = child.wait();
                return Err(std::io::Error::new(
                    std::io::ErrorKind::TimedOut,
                    "external tool exceeded configured timeout",
                ));
            }
            std::thread::sleep(Duration::from_millis(5));
        }
    }
    // Blocking wait with a watchdog that kills on deadline (plan X2.4): the
    // waiting thread never polls, removing quantisation and wakeups.
    use std::sync::atomic::{AtomicBool, Ordering};
    use std::sync::Arc;
    use std::thread;
    let pid = child.id();
    let done = Arc::new(AtomicBool::new(false));
    let killed = Arc::new(AtomicBool::new(false));
    let watchdog_done = done.clone();
    let watchdog_killed = killed.clone();
    let watchdog = thread::spawn(move || {
        let start = Instant::now();
        while start.elapsed() < timeout {
            if watchdog_done.load(Ordering::Relaxed) {
                return;
            }
            thread::sleep(Duration::from_millis(2).min(timeout / 4));
        }
        if !watchdog_done.load(Ordering::Relaxed)
            && !watchdog_killed.swap(true, Ordering::Relaxed)
        {
            // The exited-but-unreaped window is tiny; an ESRCH here is harmless.
            unsafe {
                libc::kill(pid as libc::pid_t, libc::SIGKILL);
            }
        }
    });
    let status = child.wait();
    done.store(true, Ordering::Relaxed);
    let _ = watchdog.join();
    if killed.load(Ordering::Relaxed) {
        return Err(std::io::Error::new(
            std::io::ErrorKind::TimedOut,
            "external tool exceeded configured timeout",
        ));
    }
    status
}

fn ghostscript_tool(name: &str, arguments: &[OsString], self_path: &Path) -> i32 {
    let Some(gs) = find_real_tool("gs", self_path) else {
        eprintln!("tectdist: {name}: ghostscript (gs) is required but not installed.");
        return 1;
    };
    let text: Vec<String> = arguments
        .iter()
        .map(|argument| argument.to_string_lossy().into_owned())
        .collect();
    let mut command = vec![
        OsString::from("-q"),
        OsString::from("-dNOPAUSE"),
        OsString::from("-dBATCH"),
        OsString::from("-dSAFER"),
    ];
    match name {
        "epstopdf" => {
            let mut input = None;
            let mut output = None;
            let mut quiet = false;
            let mut pending_output = false;
            for argument in &text {
                if pending_output {
                    output = Some(argument.clone());
                    pending_output = false;
                } else if argument == "-o" {
                    pending_output = true;
                } else if let Some(value) = argument
                    .strip_prefix("-o=")
                    .or_else(|| argument.strip_prefix("--outfile="))
                {
                    output = Some(value.into());
                } else if matches!(argument.as_str(), "-q" | "--quiet") {
                    quiet = true;
                } else if !argument.starts_with('-') {
                    if input.is_none() {
                        input = Some(argument.clone());
                    } else {
                        output = Some(argument.clone());
                    }
                }
            }
            let Some(input) = input else {
                eprintln!("tectdist: epstopdf: no input file");
                return 1;
            };
            if !Path::new(&input).is_file() {
                eprintln!("tectdist: epstopdf: {input}: No such file");
                return 1;
            }
            let output = output.unwrap_or_else(|| {
                Path::new(&input)
                    .with_extension("pdf")
                    .to_string_lossy()
                    .into_owned()
            });
            command.extend([
                OsString::from("-sDEVICE=pdfwrite"),
                OsString::from("-dEPSCrop"),
            ]);
            if quiet {
                command.push(OsString::from("-dQUIET"));
            }
            command.push(OsString::from(format!("-sOutputFile={output}")));
            command.push(OsString::from(input));
        }
        "eps2eps" => {
            if text.len() < 2 {
                eprintln!("tectdist: eps2eps: usage: eps2eps input.eps output.eps");
                return 1;
            }
            command.extend([
                OsString::from("-sDEVICE=eps2write"),
                OsString::from(format!("-sOutputFile={}", text[1])),
                OsString::from(&text[0]),
            ]);
        }
        "ps2pdf" => {
            let mut input = None;
            let mut output = None;
            let mut options = Vec::new();
            for (index, argument) in text.iter().enumerate() {
                if input.is_none() && (argument.ends_with(".ps") || argument.ends_with(".eps")) {
                    input = Some(argument.clone());
                } else if input.is_some() && index + 1 == text.len() && output.is_none() {
                    output = Some(argument.clone());
                } else {
                    options.push(argument.clone());
                }
            }
            let Some(input) = input else {
                eprintln!("tectdist: ps2pdf: no input file");
                return 1;
            };
            let output = output.unwrap_or_else(|| {
                Path::new(&input)
                    .with_extension("pdf")
                    .to_string_lossy()
                    .into_owned()
            });
            command.extend([
                OsString::from("-sDEVICE=pdfwrite"),
                OsString::from(format!("-sOutputFile={output}")),
            ]);
            command.extend(options.into_iter().map(OsString::from));
            command.push(OsString::from(input));
        }
        "pdfcrop" => {
            let mut input = None;
            let mut output = None;
            let mut margins = "0 0 0 0".to_owned();
            let mut pending_margins = false;
            for argument in &text {
                if pending_margins {
                    margins = argument.clone();
                    pending_margins = false;
                } else if matches!(argument.as_str(), "--margins" | "--margin") {
                    pending_margins = true;
                } else if let Some(value) = argument
                    .strip_prefix("--margins=")
                    .or_else(|| argument.strip_prefix("--margin="))
                {
                    margins = value.into();
                } else if !argument.starts_with('-') {
                    if input.is_none() {
                        input = Some(argument.clone());
                    } else {
                        output = Some(argument.clone());
                    }
                }
            }
            let Some(input) = input else {
                eprintln!("tectdist: pdfcrop: no input file");
                return 1;
            };
            if !Path::new(&input).is_file() {
                eprintln!("tectdist: pdfcrop: {input}: No such file");
                return 1;
            }
            let output = output.unwrap_or_else(|| {
                let input_path = Path::new(&input);
                let stem = input_path.file_stem().unwrap_or_default().to_string_lossy();
                input_path
                    .with_file_name(format!("{stem}-crop.pdf"))
                    .to_string_lossy()
                    .into_owned()
            });
            let bbox = Command::new(&gs)
                .args([
                    "-q",
                    "-dSAFER",
                    "-dNOPAUSE",
                    "-dBATCH",
                    "-sDEVICE=bbox",
                    &input,
                ])
                .output()
                .ok()
                .filter(|result| result.status.success())
                .and_then(|result| {
                    String::from_utf8_lossy(&result.stderr)
                        .lines()
                        .rfind(|line| line.contains("BoundingBox"))
                        .and_then(|line| line.split_once(':').map(|(_, values)| values.to_owned()))
                });
            let Some(bbox) = bbox else {
                eprintln!("tectdist: pdfcrop: could not determine bounding box");
                return 1;
            };
            let values: Option<Vec<f64>> = bbox
                .split_whitespace()
                .map(str::parse::<f64>)
                .collect::<Result<_, _>>()
                .ok();
            let Some(values) = values.filter(|values| values.len() >= 4) else {
                eprintln!("tectdist: pdfcrop: could not determine bounding box");
                return 1;
            };
            let margins: Option<Vec<f64>> = margins
                .split_whitespace()
                .map(str::parse::<f64>)
                .collect::<Result<_, _>>()
                .ok();
            let Some(margins) = margins else {
                eprintln!("tectdist: pdfcrop: invalid --margins value");
                return 1;
            };
            let margin = |index| *margins.get(index).unwrap_or(&0.0);
            let crop = format!(
                "[/CropBox [{} {} {} {}] /PAGES pdfmark",
                values[0] - margin(0),
                values[1] - margin(3),
                values[2] + margin(1),
                values[3] + margin(2)
            );
            command.extend([
                OsString::from("-sDEVICE=pdfwrite"),
                OsString::from("-o"),
                OsString::from(output),
                OsString::from("-c"),
                OsString::from(crop),
                OsString::from("-f"),
                OsString::from(input),
            ]);
        }
        _ => unreachable!("only generated Ghostscript tools reach this branch"),
    }
    run_command(&gs, command)
}

fn help_text() {
    println!(
        "tectdist 0.2.2 — native Tectonic-backed LaTeX compatibility layer\n\nUsage:\n  tectdist FILE.tex [OPTIONS]       compile a document\n  tectdist warm                     populate normal engine caches\n  tectdist doctor [--json]          check the installation\n  tectdist tools                    list compatible TeX commands\n  tectdist --version                show the version"
    );
}

struct Translation {
    args: Vec<OsString>,
    output_dir: PathBuf,
    input: Option<PathBuf>,
    job_name: Option<OsString>,
}

fn find_real_tool(name: &str, self_path: &Path) -> Option<PathBuf> {
    for directory in env::split_paths(&env::var_os("PATH").unwrap_or_default()) {
        let candidate = directory.join(name);
        if candidate.is_file() && candidate.is_executable() {
            let canonical = candidate
                .canonicalize()
                .unwrap_or_else(|_| candidate.clone());
            if canonical != self_path
                && canonical
                    .file_name()
                    .map(|n| n != "tectdist")
                    .unwrap_or(false)
            {
                return Some(candidate);
            }
        }
    }
    None
}

trait Executable {
    fn is_executable(&self) -> bool;
}
impl Executable for Path {
    fn is_executable(&self) -> bool {
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            self.metadata()
                .map(|m| m.permissions().mode() & 0o111 != 0)
                .unwrap_or(false)
        }
        #[cfg(not(unix))]
        {
            self.is_file()
        }
    }
}

/// Translate the compatible web2c subset to the Tectonic CLI without using a
/// shell. This mirrors the Python reference's common engine path and keeps
/// unrecognised Tectonic-native flags intact.
fn translate(arguments: Vec<OsString>) -> Translation {
    let mut extra = Vec::new();
    let mut inputs = Vec::new();
    let mut output = None;
    let mut synctex = false;
    let mut quiet = false;
    let mut shell_escape = false;
    let mut job_name = None;
    let mut pending: Option<String> = None;
    let mut end_options = false;
    for argument in arguments {
        let text = argument.to_string_lossy();
        if let Some(kind) = pending.take() {
            match kind.as_str() {
                "out" => output = Some(PathBuf::from(&argument)),
                "synctex" => synctex = text != "0",
                "interaction" => quiet = text == "batchmode",
                "jobname" => job_name = Some(argument),
                "fmt" => {
                    if text == "latex" {
                        extra.extend([OsString::from("-f"), argument]);
                    } else {
                        eprintln!(
                            "tectdist: format '{text}' unsupported by Tectonic; using latex."
                        );
                    }
                }
                "include" => extra.extend([
                    OsString::from("-Z"),
                    OsString::from(format!("search-path={text}")),
                ]),
                // web2c memory settings are accepted for compatibility, but
                // Tectonic has no equivalent runtime knobs.
                "ignored-value" => {}
                _ => {}
            }
            continue;
        }
        if end_options {
            inputs.push(argument);
            continue;
        }
        if text == "--" {
            end_options = true;
            extra.push(argument);
            continue;
        }
        if text == "-" || !text.starts_with('-') {
            inputs.push(argument);
            continue;
        }
        let name_value = text.trim_start_matches('-');
        let (name, value) = name_value.split_once('=').unwrap_or((name_value, ""));
        let has_value = name_value.contains('=');
        match name {
            "synctex" => {
                if has_value {
                    synctex = value != "0";
                } else {
                    pending = Some("synctex".into());
                }
            }
            "output-directory" | "outdir" | "aux-directory" | "auxdir" => {
                if has_value {
                    output = Some(PathBuf::from(value));
                } else {
                    pending = Some("out".into());
                }
            }
            "o" => {
                if has_value {
                    output = Some(PathBuf::from(value));
                } else {
                    pending = Some("out".into());
                }
            }
            "interaction" => {
                if has_value {
                    quiet = value == "batchmode";
                } else {
                    pending = Some("interaction".into());
                }
            }
            "jobname" => {
                if has_value {
                    job_name = Some(OsString::from(value));
                } else {
                    pending = Some("jobname".into());
                }
            }
            "include-directory" => {
                if has_value {
                    extra.extend([
                        OsString::from("-Z"),
                        OsString::from(format!("search-path={value}")),
                    ]);
                } else {
                    pending = Some("include".into());
                }
            }
            "I" => {
                if has_value {
                    extra.extend([
                        OsString::from("-Z"),
                        OsString::from(format!("search-path={value}")),
                    ]);
                } else {
                    pending = Some("include".into());
                }
            }
            name if name.starts_with('I') && name.len() > 1 => extra.extend([
                OsString::from("-Z"),
                OsString::from(format!("search-path={}", &name[1..])),
            ]),
            "fmt" | "format" => {
                if has_value {
                    if value == "latex" {
                        extra.extend([OsString::from("-f"), OsString::from(value)]);
                    } else {
                        eprintln!(
                            "tectdist: format '{value}' unsupported by Tectonic; using latex."
                        );
                    }
                } else {
                    pending = Some("fmt".into());
                }
            }
            "q" | "quiet" | "silent" => quiet = true,
            "shell-escape" | "enable-write18" | "enable-shell-escape" => shell_escape = true,
            // Keep compatibility data generated from the Python reference.
            // Memory knobs accept a separate value; the rest are valueless
            // switches (or safely drop their inline value).
            name if tectdist_tools::MEMORY_KNOBS.contains(&name) => {
                if !has_value {
                    pending = Some("ignored-value".into());
                }
            }
            name if tectdist_tools::IGNORED_FLAGS.contains(&name) => {}
            _ => extra.push(argument),
        }
    }
    let mut translated = Vec::new();
    if synctex {
        translated.push(OsString::from("--synctex"));
    }
    if shell_escape {
        translated.extend([OsString::from("-Z"), OsString::from("shell-escape")]);
    }
    if quiet {
        translated.extend([OsString::from("--chatter"), OsString::from("minimal")]);
    }
    let output_dir = output.unwrap_or_else(|| PathBuf::from("."));
    if !inputs.is_empty() {
        let _ = fs::create_dir_all(&output_dir);
        translated.extend([OsString::from("-o"), output_dir.as_os_str().to_os_string()]);
    }
    translated.extend(extra);
    // Keep the native path byte-for-byte compatible with the Python
    // reference: environment search paths are appended after explicit
    // command-line paths, including a trailing empty component meaning cwd.
    for variable in tectdist_tools::ENGINE_PATH_VARS {
        let Some(value) = env::var_os(variable) else {
            continue;
        };
        let value = value.to_string_lossy();
        for path in value.split(':') {
            let path = if path.is_empty() { "." } else { path };
            translated.extend([
                OsString::from("-Z"),
                OsString::from(format!("search-path={path}")),
            ]);
        }
    }
    let input = inputs.last().map(PathBuf::from);
    translated.extend(inputs);
    Translation {
        args: translated,
        output_dir,
        input,
        job_name,
    }
}

fn safe_job_name(job_name: &OsString) -> Option<&std::ffi::OsStr> {
    // Keep the historical basename behaviour for a path-y job name, but
    // never let an empty, root, or dot component turn `output_dir.join()`
    // into an absolute destination. This is a security boundary: artifact
    // renaming must stay inside the declared output directory.
    let base = Path::new(job_name).file_name()?;
    if base.is_empty() || base == "." || base == ".." {
        None
    } else {
        Some(base)
    }
}

fn rename_artifacts(output_dir: &Path, input: Option<&Path>, job_name: Option<&OsString>) {
    let Some(job_name) = job_name else {
        return;
    };
    let Some(stem) = input.and_then(|path| path.file_stem()) else {
        return;
    };
    let Some(safe) = safe_job_name(job_name) else {
        eprintln!("tectdist: refusing unsafe -jobname {:?}", job_name);
        return;
    };
    if safe == stem {
        return;
    }
    for extension in ["pdf", "synctex.gz"] {
        let from = output_dir.join(stem).with_extension(extension);
        let to = output_dir.join(safe).with_extension(extension);
        if from.is_file() {
            let _ = fs::rename(from, to);
        }
    }
}

fn index_fingerprint(plan: &CompilationPlan) -> Option<(PathBuf, u64, u128)> {
    let IndexStrategy::ExpectedStem(stem) = &plan.index_strategy else {
        return None;
    };
    let index = plan.output_dir.join(stem).with_extension("idx");
    let metadata = index.metadata().ok()?;
    let modified = metadata
        .modified()
        .ok()?
        .duration_since(UNIX_EPOCH)
        .ok()?
        .as_nanos();
    Some((index, metadata.len(), modified))
}

fn generated_auxiliary(
    plan: &CompilationPlan,
    generated_files: &[PathBuf],
    extension: &str,
) -> Option<PathBuf> {
    let IndexStrategy::ExpectedStem(stem) = &plan.index_strategy else {
        return None;
    };
    generated_files.iter().find_map(|artifact| {
        (artifact
            .extension()
            .is_some_and(|candidate_extension| candidate_extension == extension)
            && artifact
                .file_stem()
                .is_some_and(|candidate| candidate == stem.as_os_str()))
        .then(|| artifact.clone())
    })
}

/// Run the embedded MakeIndex tool inside `directory` with `arguments`
/// (argv[0] excluded). Returns the process-equivalent exit status.
fn run_embedded_makeindex(
    directory: &Path,
    arguments: &[OsString],
) -> std::io::Result<std::process::ExitStatus> {
    let saved_directory = env::current_dir()?;
    let mut full_arguments: Vec<std::ffi::CString> = Vec::with_capacity(arguments.len() + 1);
    full_arguments.push(std::ffi::CString::new("makeindex").unwrap());
    for value in arguments {
        full_arguments.push(std::ffi::CString::new(value.as_encoded_bytes())
            .map_err(|_| std::io::Error::other("argument contains interior NUL"))?);
    }
    env::set_current_dir(directory)?;
    let outcome = tectdist_makeindex::run(&full_arguments);
    // Restore the caller's directory before surfacing the outcome.
    env::set_current_dir(saved_directory)?;
    let code =
        outcome.map_err(|message| std::io::Error::other(format!("embedded makeindex: {message}")))?;
    #[cfg(unix)]
    {
        use std::os::unix::process::ExitStatusExt;
        Ok(std::process::ExitStatus::from_raw((code as i32) << 8))
    }
    #[cfg(not(unix))]
    {
        let _ = code;
        Err(std::io::Error::other("embedded makeindex requires unix"))
    }
}

/// Conservative index/glossary expectation detector (plan X5.1/X7.3 spirit):
/// only explicit index or glossary setup in the primary source triggers the
/// XDV-first flow. False negatives simply keep the previous two-full-session
/// behaviour; false positives cost one extra short XDV session.
fn index_run_expected(input: &Option<PathBuf>) -> bool {
    let Some(input) = input else {
        return false;
    };
    let Ok(source) = fs::read_to_string(input) else {
        return false;
    };
    source.contains("\\makeindex")
        || source.contains("\\makeglossary")
        || source.contains("\\usepackage{makeidx}")
        || source.contains("\\usepackage{imakeidx}")
        || source.contains("\\usepackage{glossaries}")
}

fn rerun_after_index(
    plan: &CompilationPlan,
    executor: &dyn Executor,
    before: Option<(PathBuf, u64, u128)>,
    generated_files: &[PathBuf],
) -> Option<i32> {
    let (index, glossary) = if matches!(&plan.engine, EngineSelection::Embedded(_)) {
        // The embedded driver reports generated artifacts, so a broad output
        // directory scan would add latency and could choose another document's
        // index in a shared directory.
        if let Some(index) = generated_auxiliary(plan, generated_files, "idx") {
            (Some(index), false)
        } else if let Some(glo) = generated_auxiliary(plan, generated_files, "glo") {
            (Some(glo), true)
        } else if plan.first_pass_xdv {
            // XDV-first pass but no index/glossary artifacts: the detector was
            // conservative; only the final PDF conversion remains.
            (None, false)
        } else {
            return None;
        }
    } else {
        let after = index_fingerprint(plan);
        if after.as_ref().map(|value| (&value.1, &value.2))
            == before.as_ref().map(|value| (&value.1, &value.2))
        {
            return None;
        }
        (Some(after?.0), false)
    };
    if index.is_none() {
        // No indexer needed; continue straight to the final PDF session.
        return finish_index_continuation(plan, executor);
    }
    let index = index.unwrap();
    let self_path = env::current_exe().ok()?;
    let indexer =
        find_real_tool("makeindex", &self_path).or_else(|| find_real_tool("upmendex", &self_path));
    // Embedded MakeIndex first (plan X5.3): the pinned upstream tool compiled
    // into this binary, run against a copy-on-write fork so its global state
    // and EXIT paths cannot affect the host process. Falls back to an
    // external makeindex/upmendex when explicitly requested or unavailable.
    let use_embedded = env::var_os("TECTDIST_EXTERNAL_MAKEINDEX").is_none();
    if !use_embedded && indexer.is_none() {
        eprintln!("tectdist: the document produced an index (.idx) but neither makeindex nor upmendex is available; the index will not be built.");
        return None;
    }
    let index_started = Instant::now();
    let stem = index.file_stem()?.to_os_string();
    let stem_text = stem.to_string_lossy();
    let mut arguments: Vec<OsString> = Vec::new();
    if glossary {
        let style = format!("{stem_text}.ist");
        let transcript = format!("{stem_text}.glg");
        let output = format!("{stem_text}.gls");
        let input = format!("{stem_text}.glo");
        for value in ["-s", &style, "-t", &transcript, "-o", &output, &input] {
            arguments.push(value.into());
        }
    } else {
        arguments.push(stem.clone());
    }

    let attempted = if use_embedded {
        run_embedded_makeindex(&plan.output_dir, &arguments)
    } else {
        Err(std::io::Error::other("embedded makeindex disabled"))
    };
    let status = match attempted {
        Ok(status) => Ok(status),
        Err(error) => {
            if use_embedded {
                eprintln!("tectdist: embedded makeindex unavailable ({error}); trying external fallback");
            }
            let Some(ref indexer) = indexer else {
                eprintln!(
                    "tectdist: the document produced an index (.idx) but neither makeindex nor upmendex is available; the index will not be built."
                );
                return None;
            };
            let mut command = Command::new(&indexer);
            command.current_dir(&plan.output_dir);
            command.args(&arguments);
            run_external_tool(&mut command)
        }
    };

    let Ok(status) = status else {
        // Distinguish a configured-timeout kill (124) from any other spawn or
        // wait failure so callers see the documented semantics.
        let timed_out = status.as_ref().is_err_and(|error| {
            error.kind() == std::io::ErrorKind::TimedOut
        });
        let exit = if timed_out { 124 } else { 127 };
        trace_span("indexer.run", index_started.elapsed(), Some(exit));
        eprintln!(
            "tectdist: {} could not run for '{}': {}",
            if use_embedded { "makeindex" } else { "makeindex/upmendex" },
            index.display(),
            status.as_ref().err().map(ToString::to_string).unwrap_or_default()
        );
        return Some(exit);
    };
    trace_span("indexer.run", index_started.elapsed(), status.code());
    if !status.success() {
        eprintln!(
            "tectdist: {} failed on '{}'",
            indexer.as_ref().map(|path| path.display().to_string())
                .unwrap_or_else(|| "embedded makeindex".to_string()),
            index.display()
        );
        return Some(status.code().unwrap_or(128));
    }
    finish_index_continuation(plan, executor)
}

fn finish_index_continuation(
    plan: &CompilationPlan,
    executor: &dyn Executor,
) -> Option<i32> {
    let mut rerun = plan.clone();
    // The continuation session emits the final PDF (plan X5.1).
    rerun.first_pass_xdv = false;
    // The generated .ind/.gls lives in the output directory, which may be
    // separate from the source root. Both executors understand this explicit
    // Tectonic search-path option.
    rerun.engine_args.extend([
        OsString::from("-Z"),
        OsString::from(format!("search-path={}", rerun.output_dir.display())),
    ]);
    let rerun_started = Instant::now();
    let result = match executor.execute(&rerun) {
        Ok(result) => {
            // Trace the continuation's stage events so context reuse is
            // observable alongside the primary pass.
            for event in &result.events {
                trace_span(
                    event.name,
                    std::time::Duration::from_nanos(event.duration_ns.min(u64::MAX as u128) as u64),
                    Some(result.status),
                );
            }
            result
        }
        Err(error) => {
            trace_span(
                "engine.rerun_after_index",
                rerun_started.elapsed(),
                Some(127),
            );
            eprintln!("tectdist: index rerun failed: {error}");
            return Some(127);
        }
    };
    trace_span(
        "engine.rerun_after_index",
        rerun_started.elapsed(),
        Some(result.status),
    );
    Some(result.status)
}


fn latexmk(arguments: Vec<OsString>) -> i32 {
    let mut engine = OsString::from("pdflatex");
    let mut forwarded = Vec::new();
    let mut input: Option<OsString> = None;
    let mut clean = None;
    let mut dry_run = false;
    let mut silent = false;
    let mut pending: Option<&str> = None;
    for argument in arguments {
        let text = argument.to_string_lossy();
        if let Some(kind) = pending.take() {
            match kind {
                "out" => forwarded.push(OsString::from(format!("-output-directory={text}"))),
                "job" => forwarded.push(OsString::from(format!("-jobname={text}"))),
                "interaction" => forwarded.push(OsString::from(format!("-interaction={text}"))),
                "synctex" => forwarded.push(OsString::from(format!("-synctex={text}"))),
                _ => {}
            }
            continue;
        }
        match text.as_ref() {
            "-pdf" | "-latex" => engine = OsString::from("pdflatex"),
            "-pdfxe" | "-xelatex" => engine = OsString::from("xelatex"),
            "-pdflua" | "-lualatex" => engine = OsString::from("lualatex"),
            "-c" => clean = Some(false),
            "-C" => clean = Some(true),
            "-n" | "--dry-run" => dry_run = true,
            "-q" | "-quiet" | "-silent" => {
                silent = true;
                forwarded.push(OsString::from("-interaction=batchmode"));
            }
            "-interaction" => pending = Some("interaction"),
            "-synctex" => pending = Some("synctex"),
            "-outdir" | "-out-directory" | "-output-directory" | "-auxdir" | "-aux-directory" => {
                pending = Some("out")
            }
            "-jobname" => pending = Some("job"),
            "-h" | "-help" | "--help" => {
                println!("Usage: latexmk [options] file.tex\n  -pdf, -pdfxe, -pdflua, -latex, -xelatex, -lualatex\n  -outdir=DIR, -jobname=NAME, -c, -C, -n/--dry-run");
                return 0;
            }
            "-v" | "-version" | "--version" => {
                println!("latexmk (tectdist) 0.2.2 — native Tectonic-backed build driver");
                return 0;
            }
            _ if text.starts_with("-outdir=")
                || text.starts_with("-out-directory=")
                || text.starts_with("-output-directory=")
                || text.starts_with("-auxdir=")
                || text.starts_with("-aux-directory=")
                || text.starts_with("-jobname=")
                || text.starts_with("-interaction=")
                || text.starts_with("-synctex=")
                || text == "-shell-escape"
                || text == "-no-shell-escape"
                || text == "-enable-write18"
                || text == "-disable-write18"
                || text == "-recorder"
                || text == "-8bit"
                || text == "-etex"
                || text == "-file-line-error"
                || text == "-halt-on-error" =>
            {
                forwarded.push(argument)
            }
            _ if text.starts_with('-') => eprintln!("latexmk: ignoring unknown option {text}"),
            _ if input.is_none() => input = Some(argument),
            _ => eprintln!("latexmk: ignoring extra input {text}"),
        }
    }
    let Some(input) = input else {
        eprintln!("latexmk: no input file specified");
        return 1;
    };
    let input_stem = Path::new(&input)
        .file_stem()
        .unwrap_or_else(|| std::ffi::OsStr::new("texput"));
    let output_dir = forwarded
        .iter()
        .find_map(|arg| {
            arg.to_string_lossy()
                .strip_prefix("-output-directory=")
                .map(PathBuf::from)
        })
        .unwrap_or_else(|| PathBuf::from("."));
    let requested_job_name = forwarded.iter().find_map(|argument| {
        argument
            .to_string_lossy()
            .strip_prefix("-jobname=")
            .map(OsString::from)
    });
    let clean_stem = requested_job_name
        .as_ref()
        .and_then(safe_job_name)
        .unwrap_or(input_stem);
    if let Some(all) = clean {
        let extensions = [
            "aux",
            "log",
            "out",
            "toc",
            "lof",
            "lot",
            "bbl",
            "blg",
            "idx",
            "ilg",
            "ind",
            "fls",
            "fdb_latexmk",
            "synctex.gz",
            "bcf",
            "run.xml",
        ];
        if dry_run {
            println!(
                "latexmk: dry run: would clean '{}'",
                clean_stem.to_string_lossy()
            );
            return 0;
        }
        for ext in extensions {
            let _ = fs::remove_file(output_dir.join(clean_stem).with_extension(ext));
        }
        if all {
            let _ = fs::remove_file(output_dir.join(clean_stem).with_extension("pdf"));
        }
        println!("latexmk: cleaning done");
        return 0;
    }
    let mut command = forwarded;
    command.push(input);
    if dry_run {
        println!("latexmk: dry run: {}", engine.to_string_lossy());
        return 0;
    }
    // Compatibility chatter costs nothing when suppressed and is hidden in
    // silent/quiet modes or whenever stdout is not a terminal (plan X2.5).
    if !silent && std::io::IsTerminal::is_terminal(&std::io::stdout()) {
        println!("latexmk: Running '{}'", engine.to_string_lossy());
    }
    execute_engine(engine, command)
}

fn execute_engine(program: OsString, arguments: Vec<OsString>) -> i32 {
    // Backend portfolio selection (plan X7): record the semantic contract the
    // alias promises and the backend chosen for this invocation. Only
    // qualified backends are selectable; today that is Tectonic/XeTeX plus
    // the external fallback, so selection records the decision explicitly
    // without changing semantics for any alias.
    {
        use tectdist_core::backend::{
            detect_features, select_backend, SemanticContract,
        };
        let program_text = program.to_string_lossy().into_owned();
        let contract = match program_text.as_str() {
            "xelatex" => Some(SemanticContract::XeTex),
            "lualatex" => Some(SemanticContract::LuaHbTex),
            "pdflatex" | "tectdist" => Some(SemanticContract::PdfTex),
            _ => None,
        };
        let input: Option<&OsString> = arguments
                .iter()
                .find(|argument| !argument.to_string_lossy().starts_with('-'));
        if let Some(contract) = contract {
            let source = input.map(std::path::PathBuf::from);
            let features = match &source {
                Some(source) if source.is_file() => std::fs::read_to_string(source)
                    .map(|text| detect_features(&text))
                    .unwrap_or_default(),
                _ => Default::default(),
            };
            let selected = select_backend(
                contract,
                &features,
                &[
                    #[cfg(feature = "embedded")]
                    tectdist_core::backend::BackendKind::TectonicXetex,
                    tectdist_core::backend::BackendKind::ExternalFallback,
                ],
            );
            let selection_started = Instant::now();
            trace_span(
                "backend.select",
                selection_started.elapsed(),
                None,
            );
            env::set_var(
                "TECTDIST_BACKEND_LAST",
                format!("{:?}", selected),
            );
        }
    }
    let planning_started = Instant::now();
    let translation = translate(arguments);
    trace_span("planner.translate", planning_started.elapsed(), None);
    let default_mode = if cfg!(feature = "embedded") {
        "embedded"
    } else {
        "external"
    };
    let mode = env::var("TECTDIST_ENGINE_MODE").unwrap_or_else(|_| default_mode.into());
    if mode != "external" && mode != "embedded" {
        eprintln!("tectdist: unknown engine mode '{mode}'");
        return 2;
    }
    #[cfg(not(feature = "embedded"))]
    if mode == "embedded" {
        eprintln!("tectdist: embedded mode was not compiled into this binary");
        return 2;
    }
    let path = engine();
    let canonical_path = path.canonicalize().unwrap_or_else(|_| path.clone());
    let plan = CompilationPlan {
        logical_program: program,
        engine: if mode == "embedded" {
            EngineSelection::Embedded(tectdist_core::EmbeddedEngineConfig {
                build_identity: "tectonic@0.17.0".into(),
                bundle_identity: None,
            })
        } else {
            EngineSelection::External(ResolvedExternalEngine {
                path,
                canonical_path,
                version: None,
            })
        },
        input: translation.input.clone(),
        output_dir: translation.output_dir.clone(),
        job_name: translation.job_name.clone(),
        engine_args: translation.args,
        index_strategy: translation
            .input
            .as_ref()
            .and_then(|input| input.file_stem().map(PathBuf::from))
            .map(IndexStrategy::ExpectedStem)
            .unwrap_or(IndexStrategy::NoIndexCheck),
        first_pass_xdv: index_run_expected(&translation.input),
        diagnostics: Vec::new(),
    };
    if let EngineSelection::External(engine) = &plan.engine {
        let pairing_started = Instant::now();
        let pairing = check_external_pairing(&engine.path);
        trace_span(
            "pairing.resolve",
            pairing_started.elapsed(),
            Some(if pairing.is_ok() { 0 } else { 1 }),
        );
        if let Err(error) = pairing {
            eprintln!("tectdist: {error}");
            return 1;
        }
    }
    let executor: &dyn Executor = if mode == "external" {
        &ExternalTectonicExecutor
    } else {
        #[cfg(feature = "embedded")]
        {
            // Leaked once per process so the EngineContext (config, bundle,
            // format cache) is shared across engine invocations, including
            // index continuation (plan X2.1).
            &*Box::leak(Box::new(EmbeddedTectonicExecutor::default()))
        }
        #[cfg(not(feature = "embedded"))]
        {
            unreachable!("embedded mode was returned above")
        }
    };
    let index_scan_started = Instant::now();
    let before_index = if matches!(&plan.engine, EngineSelection::External(_)) {
        index_fingerprint(&plan)
    } else {
        None
    };
    trace_span(
        "filesystem.index_scan_before",
        index_scan_started.elapsed(),
        None,
    );
    let engine_started = Instant::now();
    match executor.execute(&plan) {
        Ok(result) => {
            trace_span("engine.run", engine_started.elapsed(), Some(result.status));
            for event in &result.events {
                trace_span(
                    event.name,
                    std::time::Duration::from_nanos(event.duration_ns.min(u64::MAX as u128) as u64),
                    Some(result.status),
                );
            }
            let status = if result.status == 0 {
                let index_scan_started = Instant::now();
                let rerun =
                    rerun_after_index(&plan, executor, before_index, &result.generated_files);
                trace_span(
                    "filesystem.index_scan_after",
                    index_scan_started.elapsed(),
                    rerun,
                );
                rerun.unwrap_or(result.status)
            } else {
                result.status
            };
            if status == 0 {
                let rename_started = Instant::now();
                rename_artifacts(
                    &plan.output_dir,
                    plan.input.as_deref(),
                    translation.job_name.as_ref(),
                );
                trace_span("artifacts.rename", rename_started.elapsed(), Some(status));
            }
            status
        }
        Err(error) => {
            trace_span("engine.run", engine_started.elapsed(), Some(127));
            eprintln!("tectdist: {error}");
            127
        }
    }
}

/// Populate normal Tectonic bundle/format caches with a minimal document.
/// This is deliberately a one-shot command: it preserves no tectdist result
/// cache and removes its private temporary project before returning.
fn warm() -> i32 {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_nanos())
        .unwrap_or(0);
    let directory = env::temp_dir().join(format!("tectdist-warm-{}-{nonce}", std::process::id()));
    if let Err(error) = fs::create_dir_all(&directory) {
        eprintln!("tectdist: warm: cannot create temporary directory: {error}");
        return 1;
    }
    let input = directory.join("warm.tex");
    if let Err(error) = fs::write(
        &input,
        "\\documentclass{article}\\begin{document}tectdist warm cache seed\\end{document}\n",
    ) {
        eprintln!("tectdist: warm: cannot write cache seed: {error}");
        let _ = fs::remove_dir_all(&directory);
        return 1;
    }
    println!("tectdist: warming normal bundle and format caches");
    let result = execute_engine(
        OsString::from("pdflatex"),
        vec![
            OsString::from("-output-directory"),
            directory.as_os_str().to_os_string(),
            input.as_os_str().to_os_string(),
        ],
    );
    let _ = fs::remove_dir_all(&directory);
    result
}

fn main() {
    let mut args = env::args_os();
    let arg0 = args.next().unwrap_or_else(|| OsString::from("tectdist"));
    let invoked = invoked_name(&arg0);
    let rest: Vec<OsString> = args.collect();
    if invoked == "tectdist"
        && rest
            .first()
            .map(|a| a == "--version" || a == "version")
            .unwrap_or(false)
    {
        println!(
            "tectdist 0.2.2 (native {}-engine mode)",
            if cfg!(feature = "embedded") {
                "embedded"
            } else {
                "external"
            }
        );
        return;
    }
    if invoked == "tectdist"
        && rest
            .first()
            .map(|argument| argument == "-h" || argument == "-help" || argument == "--help")
            .unwrap_or(false)
    {
        help_text();
        return;
    }
    if invoked == "tectdist"
        && rest
            .first()
            .map(|argument| argument == "warm")
            .unwrap_or(false)
    {
        if rest
            .get(1)
            .is_some_and(|argument| argument == "--help" || argument == "-h")
        {
            println!("usage: tectdist warm\n\nPopulate normal Tectonic bundle and format caches with a temporary minimal document.");
            return;
        }
        std::process::exit(warm());
    }
    if invoked == "tectdist"
        && rest
            .first()
            .map(|argument| argument == "doctor")
            .unwrap_or(false)
    {
        std::process::exit(doctor(rest.iter().any(|argument| argument == "--json")));
    }
    if invoked == "tectdist"
        && rest
            .first()
            .map(|argument| argument == "tools")
            .unwrap_or(false)
    {
        tools_text();
        return;
    }
    let program = if invoked == "tectdist" {
        OsString::from("pdflatex")
    } else {
        invoked
    };
    let name = program.to_string_lossy();
    if name == "latexmk" {
        std::process::exit(latexmk(rest));
    }
    if name == "kpsewhich" {
        std::process::exit(kpsewhich(rest));
    }
    // BasicTeX profile (plan B1): exact reference engines, arguments passed
    // through untranslated so BasicTeX semantics are preserved verbatim.
    if env::var("TECTDIST_PROFILE").as_deref() == Ok("basictex-2026") {
        match run_basictex_engine(&name, &rest) {
            Ok(status) => {
                trace_span("basictex.engine", Duration::from_millis(0), Some(status));
                std::process::exit(status);
            }
            Err(error) => {
                eprintln!("tectdist: {error}");
                eprintln!(
                    "tectdist: falling back to the built-in engine path; the result remains exact but is not BasicTeX-accelerated."
                );
            }
        }
    }
    if tectdist_tools::GS_TOOLS.contains(&name.as_ref()) {
        let self_path = Path::new(&arg0)
            .canonicalize()
            .unwrap_or_else(|_| PathBuf::from(&arg0));
        std::process::exit(ghostscript_tool(&name, &rest, &self_path));
    }
    if tectdist_tools::is_silent_stub(&name) {
        return;
    }
    if tectdist_tools::is_informative_stub(&name) {
        eprintln!("tectdist: {name}: this TeX Live utility is not needed with Tectonic.");
        return;
    }
    if tectdist_tools::is_proxy(&name) {
        let self_path = Path::new(&arg0)
            .canonicalize()
            .unwrap_or_else(|_| PathBuf::from(&arg0));
        if let Some(tool) = find_real_tool(&name, &self_path) {
            match Command::new(tool).args(&rest).status() {
                Ok(status) => std::process::exit(status.code().unwrap_or(128)),
                Err(error) => {
                    eprintln!("tectdist: {name}: {error}");
                    std::process::exit(127);
                }
            }
        }
        if tectdist_tools::is_proxy_or_stub(&name) {
            eprintln!("tectdist: {name}: no compatible real binary found; nothing to do.");
            return;
        }
        eprintln!("tectdist: {name}: real binary not found on this system.");
        std::process::exit(127);
    }
    if !tectdist_tools::is_engine(&program.to_string_lossy()) {
        eprintln!(
            "tectdist: native compatibility dispatch for {:?} is not yet enabled",
            program
        );
        std::process::exit(2);
    }
    let total_started = Instant::now();
    let status = execute_engine(program, rest);
    trace_span("process.total", total_started.elapsed(), Some(status));
    std::process::exit(status);
}

/// Attempt one compile through the resident supervisor via IPC.
/// Returns Ok(exit_status) on a completed compile; Err when the supervisor
/// is unavailable or refuses the request (caller falls back).
#[cfg(unix)]
fn supervisor_compile(name: &str, rest: &[OsString]) -> Result<i32, String> {
    use std::io::{BufRead, BufReader};

    let socket_path = match env::var("TECTDIST_SUPERVISOR_SOCKET") {
        Ok(explicit) => PathBuf::from(explicit),
        Err(_) => {
            let tmp = env::var("TMPDIR").unwrap_or_else(|_| "/tmp".into());
            let uid = unsafe { libc::getuid() };
            PathBuf::from(tmp)
                .join(format!(".tectdist-{uid}"))
                .join("supervisor.sock")
        }
    };
    let mut stream = UnixStream::connect(&socket_path)
        .map_err(|_| "supervisor socket not found".to_string())?;

    let cwd = env::current_dir().map_err(|e| e.to_string())?;
    let mut argv_json = Vec::new();
    argv_json.push(serde_json::Value::String(name.to_string()));
    for argument in rest {
        argv_json.push(serde_json::Value::String(
            argument.to_string_lossy().into_owned(),
        ));
    }

    // Derive the job source file the same way the supervisor does.
    let job = rest
        .iter()
        .rev()
        .find_map(|argument| {
            let text = argument.to_string_lossy();
            text.ends_with(".tex").then(|| {
                PathBuf::from(&*text)
                    .file_name()
                    .map(|n| n.to_string_lossy().into_owned())
                    .unwrap_or_else(|| text.into_owned())
            })
        })
        .unwrap_or_default();

    let request = serde_json::json!({
        "protocol_version": 1,
        "type": "compile",
        "profile": "basictex-2026",
        "cwd": cwd,
        "argv": argv_json,
        "job": job,
    });
    stream
        .write_all(request.to_string().as_bytes())
        .and_then(|_| stream.write_all(b"\n"))
        .map_err(|e| e.to_string())?;
    stream.flush().map_err(|e| e.to_string())?;

    let mut reader = BufReader::new(stream.try_clone().map_err(|e| e.to_string())?);
    let mut line = String::new();
    reader.read_line(&mut line).map_err(|e| e.to_string())?;
    let value: serde_json::Value =
        serde_json::from_str(line.trim()).map_err(|e| e.to_string())?;
    if value["ok"].as_bool() != Some(true) {
        return Err(value["error"]
            .as_str()
            .unwrap_or("supervisor refused")
            .to_string());
    }
    Ok(value["compile_accepted"]["exit_status"]
        .as_i64()
        .map(|code| code as i32)
        .unwrap_or(1))
}

/// Execute one command through the pinned BasicTeX image (plan B1).
/// Arguments are forwarded unchanged: the reference binary is the semantic
/// authority in this profile.
fn run_basictex_engine(name: &str, rest: &[OsString]) -> Result<i32, String> {
    // Resident-supervisor fast path (plan §6.1): when a supervisor is
    // running for this user, route the compile through it — the supervisor
    // serves exact engines from the pinned image, with fork-server workers
    // and (later) preamble snapshots. Any failure falls through to direct
    // execution below, preserving BT100 semantics.
    if env::var("TECTDIST_NO_SUPERVISOR").is_err() {
        match supervisor_compile(name, rest) {
            Ok(status) => return Ok(status),
            Err(_) => { /* supervisor unavailable: direct execution */ }
        }
    }
    // M1 transition: the profile resolves its engine root through the
    // shared runtime-pack resolver (TECTDIST_RUNTIME_ROOT preferred,
    // legacy oracle-image root still accepted). See
    // docs/BASICTEX_REFERENCE_CATALOGUE.md for the removal plan.
    let root_path = match tectdist_core::runtime::detect_runtime_pack_source()
    {
        Some(tectdist_core::runtime::RuntimePackSource::TectdistRoot(path))
        | Some(tectdist_core::runtime::RuntimePackSource::LegacyImageRoot(path)) => {
            path
        }
        None => {
            return Err(
                "basictex-2026 profile requires a runtime pack: set \
                 TECTDIST_RUNTIME_ROOT"
                    .to_string(),
            )
        }
    };
    let platform_dir = root_path
        .join("bin")
        .read_dir()
        .map_err(|error| format!("cannot read BasicTeX bin directory: {error}"))?
        .filter_map(|entry| entry.ok())
        .find(|entry| entry.path().is_dir())
        .ok_or_else(|| "no platform directory under BasicTeX bin/".to_string())?;
    let binary = platform_dir.path().join(name);
    if !binary.exists() {
        return Err(format!("BasicTeX image has no binary for '{name}'"));
    }
    let started = Instant::now();
    let status = Command::new(binary)
        .args(rest)
        .env("TEXMFROOT", &root_path)
        .status()
        .map_err(|error| format!("cannot launch BasicTeX {name}: {error}"))?;
    trace_span(
        "engine.basictex",
        started.elapsed(),
        Some(status.code().unwrap_or(128)),
    );
    Ok(status.code().unwrap_or(128))
}
