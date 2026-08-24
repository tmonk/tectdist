//! Embedded MakeIndex: the pinned upstream C tool compiled into the binary
//! (plan X5.3). Used for the common index/glossary path so no external
//! process is required; unsupported invocations fall back to an external
//! makeindex/upmendex.
//!
//! The C code keeps mutable global state and a jump buffer, so invocations
//! are serialised with a mutex. Fatal MakeIndex conditions (`EXIT`) unwind
//! through a longjmp in the shim and surface as the returned exit code.

//! Embedded MakeIndex: the pinned upstream C tool compiled into the binary
//! (plan X5.3). Used for the common index/glossary path so no external
//! binary or PATH lookup is required; unsupported invocations fall back to an
//! external makeindex/upmendex.
//!
//! MakeIndex keeps mutable global state and terminates through `EXIT` (an
//! `exit` macro), which the build shim converts into a return value. Because
//! that state does not fully reset between invocations, `run()` isolates each
//! call in a forked child: the child executes the compiled tool against a
//! copy-on-write snapshot and exits with its code. This preserves the
//! no-exec/no-PATH-lookup benefit while guaranteeing process-equivalent
//! semantics for every invocation.

use std::ffi::{c_char, c_int, CString};
use std::sync::Mutex;

extern "C" {
    fn tectdist_makeindex_run(argc: c_int, argv: *const *const c_char) -> c_int;
}

static RUN_LOCK: Mutex<()> = Mutex::new(());

/// Run embedded MakeIndex with `arguments` (argv[0] is program name).
/// Returns the process-equivalent exit code; Ok(0) means success.
///
/// The call is serialised and executed in a forked child so the C tool's
/// global state can never leak between invocations or corrupt the host
/// process on fatal paths. Callers must not run this from contexts where
/// another thread may hold the malloc lock at fork time (the CLI is
/// single-threaded here by construction).
pub fn run(arguments: &[CString]) -> Result<i32, String> {
    let _guard = RUN_LOCK.lock().map_err(|_| "makeindex lock poisoned".to_string())?;
    let mut pointers: Vec<*const c_char> = arguments.iter().map(|value| value.as_ptr()).collect();
    pointers.push(std::ptr::null());
    let argc = arguments.len() as c_int;

    // SAFETY: pointers stays alive for the call; the child only invokes the
    // tool and exits without unwinding, and the parent only waits.
    #[cfg(unix)]
    unsafe {
        let pid = libc::fork();
        if pid < 0 {
            return Err("makeindex fork failed".to_string());
        }
        if pid == 0 {
            let code = tectdist_makeindex_run(argc, pointers.as_ptr());
            libc::_exit(code);
        }
        let mut status: libc::c_int = 0;
        if libc::waitpid(pid, &mut status, 0) < 0 {
            return Err("makeindex waitpid failed".to_string());
        }
        let code = if libc::WIFEXITED(status) {
            libc::WEXITSTATUS(status)
        } else if libc::WIFSIGNALED(status) {
            128 + libc::WTERMSIG(status)
        } else {
            125
        };
        return Ok(code);
    }

    #[cfg(not(unix))]
    unsafe {
        let code = tectdist_makeindex_run(argc, pointers.as_ptr());
        Ok(code)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn builds_a_simple_index() {
        let directory = tempfile::tempdir().unwrap();
        std::fs::write(
            directory.path().join("sample.idx"),
            "\\indexentry{alpha}{1}\n\\indexentry{beta|textbf}{2}\n",
        )
        .unwrap();
        let arguments = vec![
            CString::new("makeindex").unwrap(),
            CString::new(directory.path().join("sample.idx").to_str().unwrap()).unwrap(),
        ];
        let status = run(&arguments).expect("embedded makeindex");
        assert_eq!(status, 0, "embedded makeindex should succeed");
        let ind = std::fs::read_to_string(directory.path().join("sample.ind")).unwrap();
        assert!(ind.contains("alpha"));
        assert!(ind.contains("textbf"));
    }

    #[test]
    fn repeated_runs_are_independent() {
        for name in ["one", "two"] {
            let directory = tempfile::tempdir().unwrap();
            std::fs::write(
                directory.path().join(format!("{name}.idx")),
                "\\indexentry{x}{1}\n",
            )
            .unwrap();
            let arguments = vec![
                CString::new("makeindex").unwrap(),
                CString::new(
                    directory
                        .path()
                        .join(format!("{name}.idx"))
                        .to_str()
                        .unwrap(),
                )
                .unwrap(),
            ];
            assert_eq!(run(&arguments).unwrap(), 0);
        }
    }

    #[test]
    fn fatal_conditions_return_nonzero_without_exiting() {
        let directory = tempfile::tempdir().unwrap();
        let arguments = vec![
            CString::new("makeindex").unwrap(),
            CString::new(directory.path().join("missing.idx").to_str().unwrap()).unwrap(),
        ];
        let status = run(&arguments).expect("embedded makeindex");
        assert_ne!(status, 0, "missing input must be a nonzero failure");
    }
}

#[cfg(test)]
mod differential_tests {
    use super::*;

    /// Differential fixtures against MakeIndex 2.12 behaviour (plan X5.3):
    /// sorting, ranges, encapsulation, and custom .ist styles. Expected
    /// outputs follow the upstream tool's documented semantics.
    #[test]
    fn ranges_encapsulation_and_style() {
        let directory = tempfile::tempdir().unwrap();
        std::fs::write(
            directory.path().join("d.idx"),
            "\\indexentry{alpha|textbf}{1}\n\\indexentry{alpha|textbf}{3}\n\
             \\indexentry{beta}{2}\n\\indexentry{gamma|(}{4}\n\\indexentry{gamma|)}{6}\n",
        )
        .unwrap();
        let arguments = vec![
            CString::new("makeindex").unwrap(),
            CString::new(directory.path().join("d.idx").to_str().unwrap()).unwrap(),
        ];
        assert_eq!(run(&arguments).unwrap(), 0);
        let ind = std::fs::read_to_string(directory.path().join("d.ind")).unwrap();
        // MakeIndex 2.12 semantics: repeated encapsulated pages stay listed;
        // open/close range encapsulation collapses to a page range.
        assert!(ind.contains("\\textbf{1}, \\textbf{3}"));
        assert!(ind.contains("4--6"));
        // Standard preamble present.
        assert!(ind.contains("\\begin{theindex}"));
    }

    #[test]
    fn custom_style_is_applied() {
        let directory = tempfile::tempdir().unwrap();
        std::fs::write(directory.path().join("c.idx"), "\\indexentry{zeta}{1}\n").unwrap();
        std::fs::write(
            directory.path().join("c.ist"),
            "preamble \"\\\\documentclass{article}\\\\begin{document}\\n\"\n",
        )
        .unwrap();
        let arguments = vec![
            CString::new("makeindex").unwrap(),
            CString::new("-s").unwrap(),
            CString::new(directory.path().join("c.ist").to_str().unwrap()).unwrap(),
            CString::new(directory.path().join("c.idx").to_str().unwrap()).unwrap(),
        ];
        assert_eq!(run(&arguments).unwrap(), 0);
        let ind = std::fs::read_to_string(directory.path().join("c.ind")).unwrap();
        assert!(ind.contains("\\begin{document}"));
    }
}
