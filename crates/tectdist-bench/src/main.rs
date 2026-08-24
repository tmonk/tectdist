//! Benchmark supervisor: launches a command and measures wall time plus
//! per-child resource usage around child execution only.
//!
//! The benchmark runner uses this instead of cumulative `RUSAGE_CHILDREN`
//! deltas taken from the Python process, which mix unrelated children into
//! peak-RSS figures. Wall time covers exactly spawn through completion; no
//! cache-tree walks or trace handling occur inside the timed interval.
//!
//! Usage:
//!   tectdist-bench --output <metrics.json> [--cwd <dir>] -- <command> [args...]
//!
//! The child inherits this process's stdio so the caller can capture output
//! with ordinary pipes. The supervisor exits with the child's exit code
//! (127 when the child cannot be spawned) and writes one JSON object to the
//! output path on every completed measurement.
#![cfg_attr(not(unix), allow(dead_code))]

use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::time::Instant;

#[cfg(unix)]
use libc::wait4;

const USAGE: &str = "usage: tectdist-bench --output <file> [--cwd <dir>] -- <command> [args...]";

struct Options {
    output: PathBuf,
    cwd: Option<PathBuf>,
    command: Vec<String>,
}

fn parse_arguments() -> Result<Options, String> {
    let mut arguments = std::env::args().skip(1);
    let mut output = None;
    let mut cwd = None;
    let mut command = Vec::new();
    while let Some(argument) = arguments.next() {
        match argument.as_str() {
            "--output" => {
                output =
                    Some(PathBuf::from(arguments.next().ok_or("--output requires a value")?));
            }
            "--cwd" => {
                cwd = Some(PathBuf::from(arguments.next().ok_or("--cwd requires a value")?));
            }
            "--" => {
                command.extend(arguments);
                break;
            }
            "--help" | "-h" => return Err(USAGE.to_string()),
            other => return Err(format!("unknown argument '{other}'\n{USAGE}")),
        }
    }
    if command.is_empty() {
        return Err(format!("no command given\n{USAGE}"));
    }
    Ok(Options { output: output.ok_or(format!("--output is required\n{USAGE}"))?, cwd, command })
}

fn peak_rss_unit() -> &'static str {
    // wait4's ru_maxrss is KiB on Linux and bytes on macOS/BSDs.
    if cfg!(target_os = "macos") || cfg!(target_os = "freebsd") || cfg!(target_os = "netbsd") {
        "bytes"
    } else {
        "KiB"
    }
}

#[cfg(unix)]
fn run_measured(options: &Options) -> (String, i32) {
    use std::ffi::CString;

    if let Some(directory) = &options.cwd {
        if let Err(error) = std::env::set_current_dir(directory) {
            return (format!("{{\"error\":\"chdir failed: {error}\"}}"), 125);
        }
    }

    let program = CString::new(
        options.command[0].as_bytes(),
    )
    .map_err(|_| "command contains interior NUL byte".to_string());
    let program = match program {
        Ok(value) => value,
        Err(message) => return (format!("{{\"error\":\"{message}\"}}"), 125),
    };
    let arguments: Vec<CString> = options
        .command
        .iter()
        .map(|value| CString::new(value.as_bytes()).expect("interior NUL filtered above"))
        .collect();

    let start = Instant::now();
    // Fork/exec through posix_spawn via Command is not usable here because we
    // need the pid for wait4; spawn manually with fork+exec.
    let pid = unsafe { libc::fork() };
    if pid < 0 {
        return ("{\"error\":\"fork failed\"}".to_string(), 125);
    }
    if pid == 0 {
        // Child: exec without buffering concerns; stdio already inherited.
        let raw_arguments: Vec<*const libc::c_char> = arguments
            .iter()
            .map(|value| value.as_ptr())
            .chain(std::iter::once(std::ptr::null()))
            .collect();
        unsafe {
            libc::execvp(program.as_ptr(), raw_arguments.as_ptr());
            // exec only returns on failure.
            libc::_exit(127);
        }
    }
    let mut status: libc::c_int = 0;
    let mut usage: libc::rusage = unsafe { std::mem::zeroed() };
    let waited = unsafe { wait4(pid, &mut status, 0, &mut usage) };
    let wall_ms = start.elapsed().as_secs_f64() * 1000.0;
    if waited < 0 {
        return (
            format!("{{\"error\":\"wait4 failed\",\"wall_time_ms\":{wall_ms:.3}}}"),
            125,
        );
    }
    let exit_code = if libc::WIFEXITED(status) {
        libc::WEXITSTATUS(status)
    } else if libc::WIFSIGNALED(status) {
        128 + libc::WTERMSIG(status)
    } else {
        125
    };
    let payload = format!(
        "{{\"wall_time_ms\":{wall_ms:.3},\"exit_status\":{exit_code},\
         \"user_cpu_ms\":{:.3},\"system_cpu_ms\":{:.3},\
         \"peak_rss\":{},\"peak_rss_unit\":\"{}\",\
         \"resource_method\":\"wait4-direct-child\"}}",
        usage.ru_utime.tv_sec as f64 * 1000.0 + usage.ru_utime.tv_usec as f64 / 1000.0,
        usage.ru_stime.tv_sec as f64 * 1000.0 + usage.ru_stime.tv_usec as f64 / 1000.0,
        usage.ru_maxrss,
        peak_rss_unit(),
    );
    (payload, exit_code)
}

#[cfg(not(unix))]
fn run_measured(options: &Options) -> (String, i32) {
    if let Some(directory) = &options.cwd {
        if let Err(error) = std::env::set_current_dir(directory) {
            return (format!("{{\"error\":\"chdir failed: {error}\"}}"), 125);
        }
    }
    let start = Instant::now();
    let result = Command::new(&options.command[0]).args(&options.command[1..]).status();
    let wall_ms = start.elapsed().as_secs_f64() * 1000.0;
    match result {
        Ok(status) => (
            format!(
                "{{\"wall_time_ms\":{wall_ms:.3},\"exit_status\":{},\"resource_method\":\"status-only\"}}",
                status.code().unwrap_or(128)
            ),
            status.code().unwrap_or(128),
        ),
        Err(error) => (format!("{{\"error\":\"spawn failed: {error}\"}}"), 127),
    }
}

fn write_metrics(path: &Path, payload: &str) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    let mut file = fs::File::create(path).map_err(|error| error.to_string())?;
    file.write_all(payload.as_bytes())
        .and_then(|_| file.write_all(b"\n"))
        .map_err(|error| error.to_string())
}

fn main() {
    let options = match parse_arguments() {
        Ok(value) => value,
        Err(message) => {
            eprintln!("tectdist-bench: {message}");
            std::process::exit(2);
        }
    };
    let (payload, exit_code) = run_measured(&options);
    if let Err(error) = write_metrics(&options.output, &payload) {
        eprintln!("tectdist-bench: cannot write {}: {error}", options.output.display());
        std::process::exit(124);
    }
    std::process::exit(exit_code);
}
