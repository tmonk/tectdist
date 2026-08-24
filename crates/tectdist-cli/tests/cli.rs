use std::fs;
#[cfg(unix)]
use std::os::unix::process::CommandExt;
use std::path::PathBuf;
use std::process::Command;

fn binary() -> &'static str {
    env!("CARGO_BIN_EXE_tectdist")
}

fn temporary(name: &str) -> PathBuf {
    let path = std::env::temp_dir().join(format!("tectdist-native-{name}-{}", std::process::id()));
    let _ = fs::remove_dir_all(&path);
    fs::create_dir_all(&path).unwrap();
    path
}

#[test]
fn external_engine_translates_common_flags() {
    let directory = temporary("translate");
    let engine = directory.join("engine");
    let log = directory.join("argv");
    fs::write(
        &engine,
        format!("#!/bin/sh\nprintf '%s\\n' \"$@\" > '{}'\n", log.display()),
    )
    .unwrap();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(&engine, fs::Permissions::from_mode(0o755)).unwrap();
    }
    let status = Command::new(binary())
        .current_dir(&directory)
        .env("TECTONIC", &engine)
        .env("TECTDIST_ENGINE_MODE", "external")
        .args(["-synctex=1", "-output-directory=out", "sample.tex"])
        .status()
        .unwrap();
    assert!(status.success());
    assert_eq!(
        fs::read_to_string(log).unwrap(),
        "--synctex\n-o\nout\nsample.tex\n"
    );
}

#[test]
fn external_engine_uses_generated_flag_rules_and_search_paths() {
    let directory = temporary("generated-flags");
    let engine = directory.join("engine");
    let log = directory.join("argv");
    fs::write(
        &engine,
        format!("#!/bin/sh\nprintf '%s\\n' \"$@\" > '{}'\n", log.display()),
    )
    .unwrap();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(&engine, fs::Permissions::from_mode(0o755)).unwrap();
    }
    let status = Command::new(binary())
        .current_dir(&directory)
        .env("TECTONIC", &engine)
        .env("TECTDIST_ENGINE_MODE", "external")
        .env("TEXINPUTS", "styles:")
        .args([
            "-include-directory=local",
            "-fmt=latex",
            "-main-memory",
            "9000000",
            "-recorder",
            "sample.tex",
        ])
        .status()
        .unwrap();
    assert!(status.success());
    assert_eq!(
        fs::read_to_string(log).unwrap(),
        "-o\n.\n-Z\nsearch-path=local\n-f\nlatex\n-Z\nsearch-path=styles\n-Z\nsearch-path=.\nsample.tex\n"
    );
}

#[test]
fn latexmk_uses_the_shared_native_engine_path() {
    let directory = temporary("latexmk-shared-path");
    let engine = directory.join("engine");
    let log = directory.join("argv");
    fs::write(
        &engine,
        format!("#!/bin/sh\nprintf '%s\\n' \"$@\" > '{}'\n", log.display()),
    )
    .unwrap();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(&engine, fs::Permissions::from_mode(0o755)).unwrap();
    }
    let status = Command::new(binary())
        .arg0("latexmk")
        .current_dir(&directory)
        .env("TECTONIC", &engine)
        .env("TECTDIST_ENGINE_MODE", "external")
        .args(["-pdf", "-outdir", "out", "sample.tex"])
        .status()
        .unwrap();
    assert!(status.success());
    assert_eq!(fs::read_to_string(log).unwrap(), "-o\nout\nsample.tex\n");
}

#[test]
fn native_latexmk_clean_uses_requested_jobname() {
    let directory = temporary("latexmk-clean-jobname");
    let farm = directory.join("latexmk");
    std::os::unix::fs::symlink(binary(), &farm).unwrap();
    fs::write(directory.join("sample.tex"), "\\documentclass{article}").unwrap();
    fs::write(directory.join("renamed.pdf"), "pdf").unwrap();
    fs::write(directory.join("renamed.aux"), "aux").unwrap();
    let status = Command::new(&farm)
        .current_dir(&directory)
        .args(["-C", "-jobname=renamed", "sample.tex"])
        .status()
        .unwrap();
    assert!(status.success());
    assert!(!directory.join("renamed.pdf").exists());
    assert!(!directory.join("renamed.aux").exists());
}

#[test]
fn native_trace_file_records_planning_engine_and_total_spans() {
    let directory = temporary("trace");
    let engine = directory.join("engine");
    let trace = directory.join("trace.jsonl");
    fs::write(&engine, "#!/bin/sh\nexit 0\n").unwrap();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(&engine, fs::Permissions::from_mode(0o755)).unwrap();
    }
    let status = Command::new(binary())
        .current_dir(&directory)
        .env("TECTONIC", &engine)
        .env("TECTDIST_ENGINE_MODE", "external")
        .env("TECTDIST_TRACE_FILE", &trace)
        .arg("sample.tex")
        .status()
        .unwrap();
    assert!(status.success());
    let trace = fs::read_to_string(trace).unwrap();
    for span in [
        "planner.translate",
        "engine.spawn",
        "engine.run",
        "artifacts.rename",
        "process.total",
    ] {
        assert!(trace.contains(span), "missing {span} in {trace}");
    }
}

#[test]
fn invalid_executor_mode_still_records_total_trace() {
    let directory = temporary("bad-mode-trace");
    let trace = directory.join("trace.jsonl");
    let output = Command::new(binary())
        .current_dir(&directory)
        .env("TECTDIST_ENGINE_MODE", "not-a-mode")
        .env("TECTDIST_TRACE_FILE", &trace)
        .arg("sample.tex")
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(2));
    let trace = fs::read_to_string(trace).unwrap();
    assert!(trace.contains("planner.translate"));
    assert!(trace.contains("process.total"));
}

#[test]
fn native_external_pairing_refuses_a_mismatched_tectonic() {
    let directory = temporary("pairing-mismatch");
    let engine = directory.join("engine");
    fs::write(
        &engine,
        "#!/bin/sh\nif test \"$1\" = --version; then echo 'Tectonic 0.18.0'; fi\nexit 0\n",
    )
    .unwrap();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(&engine, fs::Permissions::from_mode(0o755)).unwrap();
    }
    let output = Command::new(binary())
        .current_dir(&directory)
        .env("TECTONIC", &engine)
        .env("TECTDIST_ENGINE_MODE", "external")
        .arg("sample.tex")
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(1));
    assert!(String::from_utf8_lossy(&output.stderr).contains("requires Tectonic 0.17.x"));
}

#[test]
fn native_doctor_reports_declared_pairing_and_rejects_mismatch() {
    let directory = temporary("doctor-pairing");
    let engine = directory.join("engine");
    let biber = directory.join("biber");
    fs::write(&engine, "#!/bin/sh\necho 'Tectonic 0.18.0'\n").unwrap();
    fs::write(&biber, "#!/bin/sh\necho 'biber version: 2.17'\n").unwrap();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(&engine, fs::Permissions::from_mode(0o755)).unwrap();
        fs::set_permissions(&biber, fs::Permissions::from_mode(0o755)).unwrap();
    }
    let old_path = std::env::var("PATH").unwrap_or_default();
    let output = Command::new(binary())
        .env("TECTONIC", &engine)
        .env("TECTDIST_ENGINE_MODE", "external")
        .env("TECTDIST_BUNDLE_ID", "bundle-test")
        .env("TECTDIST_BUNDLE_SOURCE", "fixture://bundle")
        .env("TECTDIST_BUNDLE_MANIFEST_SHA256", "abc123")
        .env("TECTDIST_FORMAT_CACHE_ID", "format-test")
        .env("PATH", format!("{}:{old_path}", directory.display()))
        .args(["doctor", "--json"])
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(1));
    let json = String::from_utf8_lossy(&output.stdout);
    assert!(json.contains("\"tectonic\":\"0.17\""));
    assert!(json.contains("\"biber\":\"2.17\""));
    assert!(json.contains("\"identity\":\"bundle-test\""));
    assert!(json.contains("\"source\":\"fixture://bundle\""));
    assert!(json.contains("\"manifest_sha256\":\"abc123\""));
    assert!(json.contains("\"format_cache_identity\":\"format-test\""));
    assert!(json.contains("\"ok\":false"));
}

#[test]
fn native_meta_commands_do_not_fall_through_to_compilation() {
    let help = Command::new(binary()).arg("--help").output().unwrap();
    assert!(help.status.success());
    assert!(String::from_utf8_lossy(&help.stdout).contains("tectdist doctor"));

    let tools = Command::new(binary()).arg("tools").output().unwrap();
    assert!(tools.status.success());
    let text = String::from_utf8_lossy(&tools.stdout);
    assert!(text.contains("pdflatex"));
    assert!(text.contains("latexmk"));
    assert!(text.contains("kpsewhich"));
}

#[test]
fn native_warm_uses_a_one_shot_cache_seed() {
    let directory = temporary("warm");
    let engine = directory.join("engine");
    let log = directory.join("engine.args");
    fs::write(
        &engine,
        format!("#!/bin/sh\nprintf '%s\\n' \"$@\" > '{}'\n", log.display()),
    )
    .unwrap();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(&engine, fs::Permissions::from_mode(0o755)).unwrap();
    }
    let output = Command::new(binary())
        .env("TECTONIC", &engine)
        .env("TECTDIST_ENGINE_MODE", "external")
        .env("TECTDIST_SKIP_PAIRING", "1")
        .arg("warm")
        .output()
        .unwrap();
    assert!(output.status.success());
    assert!(String::from_utf8_lossy(&output.stdout).contains("warming normal bundle"));
    let arguments = fs::read_to_string(log).unwrap();
    assert!(arguments.contains("-o"));
    assert!(arguments.contains("warm.tex"));
}

#[test]
fn native_kpsewhich_uses_only_supported_search_variables() {
    let directory = temporary("kpsewhich");
    let styles = directory.join("styles");
    fs::create_dir(&styles).unwrap();
    fs::write(styles.join("example.sty"), "").unwrap();

    let found = Command::new(binary())
        .arg0("kpsewhich")
        .current_dir(&directory)
        .env("TEXINPUTS", "styles:")
        .args(["-format=sty", "example.sty"])
        .output()
        .unwrap();
    assert!(found.status.success());
    assert_eq!(
        String::from_utf8_lossy(&found.stdout).trim(),
        "styles/example.sty"
    );

    let variable = Command::new(binary())
        .arg0("kpsewhich")
        .env("TEXINPUTS", "styles:")
        .args(["-var-value", "TEXINPUTS"])
        .output()
        .unwrap();
    assert!(variable.status.success());
    assert_eq!(String::from_utf8_lossy(&variable.stdout).trim(), "styles:");

    let unknown = Command::new(binary())
        .arg0("kpsewhich")
        .args(["-var-value", "HOME"])
        .output()
        .unwrap();
    assert_eq!(unknown.status.code(), Some(1));
    assert!(String::from_utf8_lossy(&unknown.stderr).contains("unknown variable"));
}

#[test]
fn native_ps2pdf_routes_to_ghostscript_without_a_shell() {
    let directory = temporary("ps2pdf");
    let farm = directory.join("ps2pdf");
    std::os::unix::fs::symlink(binary(), &farm).unwrap();
    let gs = directory.join("gs");
    let log = directory.join("gs.argv");
    fs::write(
        &gs,
        format!("#!/bin/sh\nprintf '%s\\n' \"$@\" > '{}'\n", log.display()),
    )
    .unwrap();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(&gs, fs::Permissions::from_mode(0o755)).unwrap();
    }
    let input = directory.join("sample.ps");
    fs::write(&input, "%!PS-Adobe-3.0\nshowpage\n").unwrap();
    let output = directory.join("result.pdf");
    let status = Command::new(&farm)
        .env("PATH", &directory)
        .args([input.as_os_str(), output.as_os_str()])
        .status()
        .unwrap();
    assert!(status.success());
    let arguments = fs::read_to_string(log).unwrap();
    assert!(arguments.contains("-sDEVICE=pdfwrite"));
    assert!(arguments.contains("-sOutputFile="));
    assert!(arguments.contains("sample.ps"));
}

#[test]
fn native_external_path_runs_indexer_then_reruns_engine() {
    let directory = temporary("index-rerun");
    let engine = directory.join("engine");
    let indexer = directory.join("makeindex");
    let count = directory.join("engine.count");
    let index_log = directory.join("index.argv");
    fs::write(
        &engine,
        format!(
            "#!/bin/sh\nn=0\nif test -f '{count}'; then n=$(/bin/cat '{count}'); fi\nn=$((n + 1))\nprintf '%s' \"$n\" > '{count}'\nif test \"$n\" = 1; then printf '%s\\n' '\\indexentry{{alpha}}{{1}}' > sample.idx; fi\n",
            count = count.display()
        ),
    )
    .unwrap();
    fs::write(
        &indexer,
        format!(
            "#!/bin/sh\nprintf '%s\\n' \"$@\" > '{log}'\nprintf '%s\\n' 'alpha, 1' > \"$1.ind\"\n",
            log = index_log.display()
        ),
    )
    .unwrap();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(&engine, fs::Permissions::from_mode(0o755)).unwrap();
        fs::set_permissions(&indexer, fs::Permissions::from_mode(0o755)).unwrap();
    }
    fs::write(directory.join("sample.tex"), "\\documentclass{article}").unwrap();
    let old_path = std::env::var("PATH").unwrap_or_default();
    let status = Command::new(binary())
        .current_dir(&directory)
        .env("TECTONIC", &engine)
        .env("TECTDIST_ENGINE_MODE", "external")
        .env("TECTDIST_SKIP_PAIRING", "1")
        .env("PATH", format!("{}:{old_path}", directory.display()))
        .arg("sample.tex")
        .status()
        .unwrap();
    assert!(status.success());
    assert_eq!(fs::read_to_string(count).unwrap(), "2");
    assert_eq!(fs::read_to_string(index_log).unwrap(), "sample\n");
}

#[test]
fn native_indexer_timeout_is_reported() {
    let directory = temporary("index-timeout");
    let engine = directory.join("engine");
    let indexer = directory.join("makeindex");
    fs::write(
        &engine,
        "#!/bin/sh\nprintf '%s\\n' '\\indexentry{alpha}{1}' > sample.idx\n",
    )
    .unwrap();
    fs::write(&indexer, "#!/bin/sh\nsleep 1\n").unwrap();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(&engine, fs::Permissions::from_mode(0o755)).unwrap();
        fs::set_permissions(&indexer, fs::Permissions::from_mode(0o755)).unwrap();
    }
    fs::write(directory.join("sample.tex"), "\\documentclass{article}").unwrap();
    let old_path = std::env::var("PATH").unwrap_or_default();
    let output = Command::new(binary())
        .current_dir(&directory)
        .env("TECTONIC", &engine)
        .env("TECTDIST_ENGINE_MODE", "external")
        .env("TECTDIST_SKIP_PAIRING", "1")
        .env("TECTDIST_EXTERNAL_TOOL_TIMEOUT_MS", "10")
        .env("PATH", format!("{}:{old_path}", directory.display()))
        .arg("sample.tex")
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(124));
    assert!(String::from_utf8_lossy(&output.stderr).contains("exceeded configured timeout"));
}

#[test]
fn native_jobname_cannot_escape_output_directory() {
    let directory = temporary("unsafe-jobname");
    let engine = directory.join("engine");
    fs::write(&engine, "#!/bin/sh\nprintf 'pdf' > sample.pdf\n").unwrap();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(&engine, fs::Permissions::from_mode(0o755)).unwrap();
    }
    fs::write(directory.join("sample.tex"), "\\documentclass{article}").unwrap();
    let output = Command::new(binary())
        .current_dir(&directory)
        .env("TECTONIC", &engine)
        .env("TECTDIST_ENGINE_MODE", "external")
        .env("TECTDIST_SKIP_PAIRING", "1")
        .args(["-jobname=/", "sample.tex"])
        .output()
        .unwrap();
    assert!(output.status.success());
    assert!(directory.join("sample.pdf").is_file());
    assert!(String::from_utf8_lossy(&output.stderr).contains("refusing unsafe -jobname"));
}

#[test]
#[cfg(unix)]
fn native_external_engine_accepts_non_utf8_input_paths() {
    use std::ffi::OsString;
    use std::os::unix::ffi::OsStringExt;

    let directory = temporary("non-utf8-path");
    let engine = directory.join("engine");
    fs::write(&engine, "#!/bin/sh\nexit 0\n").unwrap();
    use std::os::unix::fs::PermissionsExt;
    fs::set_permissions(&engine, fs::Permissions::from_mode(0o755)).unwrap();
    let input = PathBuf::from(OsString::from_vec(b"sample-\xff.tex".to_vec()));
    // APFS rejects invalid filename bytes, but the command-line transport
    // must still retain them without panicking before the external engine
    // reports any eventual file error.
    let status = Command::new(binary())
        .current_dir(&directory)
        .env("TECTONIC", &engine)
        .env("TECTDIST_ENGINE_MODE", "external")
        .env("TECTDIST_SKIP_PAIRING", "1")
        .arg(&input)
        .status()
        .unwrap();
    assert!(status.success());
}

#[test]
#[cfg(not(feature = "embedded"))]
fn uncompiled_embedded_mode_is_explicitly_rejected() {
    let output = Command::new(binary())
        .env("TECTDIST_ENGINE_MODE", "embedded")
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(2));
    assert!(String::from_utf8_lossy(&output.stderr).contains("not compiled"));
}

#[test]
#[cfg(feature = "embedded")]
fn embedded_build_reports_embedded_mode() {
    let output = Command::new(binary()).arg("--version").output().unwrap();
    assert!(output.status.success());
    assert!(String::from_utf8_lossy(&output.stdout).contains("embedded-engine mode"));
}

#[test]
#[cfg(feature = "embedded")]
fn embedded_warm_populates_caches_without_a_project_output() {
    let output = Command::new(binary()).arg("warm").output().unwrap();
    assert!(output.status.success());
    assert!(String::from_utf8_lossy(&output.stdout).contains("warming normal bundle"));
}

#[test]
#[cfg(feature = "embedded")]
fn embedded_and_external_executors_agree_on_tiny_document_semantics() {
    let directory = temporary("embedded-external-equivalence");
    fs::write(
        directory.join("main.tex"),
        include_str!("../../../benchmarks/corpus/tiny/main.tex"),
    )
    .unwrap();
    let embedded_output = directory.join("embedded");
    let external_output = directory.join("external");
    let embedded = Command::new(binary())
        .current_dir(&directory)
        .args(["-output-directory", "embedded", "main.tex"])
        .status()
        .unwrap();
    assert!(embedded.success());
    let external = Command::new(binary())
        .current_dir(&directory)
        .env("TECTDIST_ENGINE_MODE", "external")
        .env("TECTDIST_SKIP_PAIRING", "1")
        .args(["-output-directory", "external", "main.tex"])
        .status()
        .unwrap();
    assert!(external.success());
    let extract = |pdf: PathBuf| {
        let output = Command::new("pdftotext")
            .args([pdf, PathBuf::from("-")])
            .output()
            .unwrap();
        assert!(output.status.success());
        String::from_utf8(output.stdout).unwrap()
    };
    let embedded_text = extract(embedded_output.join("main.pdf"));
    let external_text = extract(external_output.join("main.pdf"));
    assert_eq!(embedded_text, external_text);
    assert!(embedded_text.contains("tectdist tiny benchmark"));
}

#[test]
#[cfg(feature = "embedded")]
fn embedded_mode_maps_explicit_search_paths() {
    let directory = temporary("embedded-search-path");
    let styles = directory.join("styles");
    fs::create_dir(&styles).unwrap();
    fs::write(
        styles.join("local.sty"),
        "\\ProvidesPackage{local}\\newcommand{\\localmarker}{search path works}",
    )
    .unwrap();
    fs::write(
        directory.join("sample.tex"),
        "\\documentclass{article}\\usepackage{local}\\begin{document}\\localmarker\\end{document}",
    )
    .unwrap();
    let output = Command::new(binary())
        .current_dir(&directory)
        .args(["-include-directory=styles", "sample.tex"])
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(directory.join("sample.pdf").is_file());
}

#[test]
#[cfg(feature = "embedded")]
fn embedded_mode_enables_shell_escape_only_when_requested() {
    let directory = temporary("embedded-shell-escape");
    fs::write(
        directory.join("sample.tex"),
        include_str!("../../../benchmarks/corpus/shell-escape/main.tex"),
    )
    .unwrap();
    let without_flag = Command::new(binary())
        .current_dir(&directory)
        .arg("sample.tex")
        .output()
        .unwrap();
    assert!(!directory.join("tectdist-shell-escape.txt").exists());
    assert!(without_flag.status.success() || without_flag.status.code() == Some(1));

    let with_flag = Command::new(binary())
        .current_dir(&directory)
        .args(["-shell-escape", "sample.tex"])
        .output()
        .unwrap();
    assert!(
        with_flag.status.success(),
        "{}",
        String::from_utf8_lossy(&with_flag.stderr)
    );
    assert!(directory.join("tectdist-shell-escape.txt").is_file());

    fs::remove_file(directory.join("tectdist-shell-escape.txt")).unwrap();
    let untrusted = Command::new(binary())
        .current_dir(&directory)
        .env("TECTONIC_UNTRUSTED_MODE", "1")
        .args(["-shell-escape", "sample.tex"])
        .output()
        .unwrap();
    assert!(!directory.join("tectdist-shell-escape.txt").exists());
    assert!(untrusted.status.success() || untrusted.status.code() == Some(1));
}

#[test]
#[cfg(feature = "embedded")]
fn embedded_biblatex_runs_biber_and_records_artifacts() {
    let directory = temporary("embedded-biblatex");
    fs::write(
        directory.join("main.tex"),
        include_str!("../../../benchmarks/corpus/biblatex/main.tex"),
    )
    .unwrap();
    fs::write(
        directory.join("refs.bib"),
        include_str!("../../../benchmarks/corpus/biblatex/refs.bib"),
    )
    .unwrap();
    let trace = directory.join("trace.jsonl");
    let status = Command::new(binary())
        .current_dir(&directory)
        .env("TECTDIST_TRACE_FILE", &trace)
        .arg("main.tex")
        .status()
        .unwrap();
    assert!(status.success());
    assert!(directory.join("main.pdf").is_file());
    assert!(directory.join("main.bcf").is_file());
    assert!(directory.join("main.bbl").is_file());
    assert!(fs::read_to_string(directory.join("main.bbl"))
        .unwrap()
        .contains("Knuth"));
    let trace = fs::read_to_string(trace).unwrap();
    assert!(trace.contains("artifact.bcf"));
    assert!(trace.contains("artifact.bbl"));
    for stage in [
        "engine.config",
        "engine.session_create",
        "engine.pass",
        "engine.stage.tex_pass",
        "engine.stage.external_tool",
        "engine.stage.xdvipdfmx",
    ] {
        let line = trace
            .lines()
            .find(|line| line.contains(stage))
            .unwrap_or_else(|| panic!("missing trace stage {stage}"));
        let duration = line
            .split("\"duration_ns\":")
            .nth(1)
            .and_then(|value| value.split([',', '}']).next())
            .and_then(|value| value.parse::<u128>().ok())
            .unwrap_or(0);
        assert!(duration > 0, "{stage} must have a measured duration");
    }
}

#[test]
#[cfg(feature = "embedded")]
fn embedded_index_runs_indexer_and_reruns_engine() {
    let directory = temporary("embedded-index");
    fs::write(
        directory.join("main.tex"),
        include_str!("../../../benchmarks/corpus/index/main.tex"),
    )
    .unwrap();
    let indexer = directory.join("makeindex");
    fs::write(
        &indexer,
        "#!/bin/sh\nprintf '%s\\n' '\\\\begin{theindex}' '\\\\item alpha, 1' '\\\\end{theindex}' > \"$1.ind\"\n",
    )
    .unwrap();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(&indexer, fs::Permissions::from_mode(0o755)).unwrap();
    }
    let trace = directory.join("trace.jsonl");
    let old_path = std::env::var("PATH").unwrap_or_default();
    let status = Command::new(binary())
        .current_dir(&directory)
        .env("PATH", format!("{}:{old_path}", directory.display()))
        .env("TECTDIST_TRACE_FILE", &trace)
        .arg("main.tex")
        .status()
        .unwrap();
    assert!(status.success());
    assert!(directory.join("main.pdf").is_file());
    assert!(directory.join("main.ind").is_file());
    let trace = fs::read_to_string(trace).unwrap();
    assert!(trace.contains("indexer.run"));
    assert!(trace.contains("engine.rerun_after_index"));
}

#[test]
#[cfg(feature = "embedded")]
fn embedded_index_reruns_with_a_separate_output_directory() {
    let directory = temporary("embedded-index-outdir");
    fs::write(
        directory.join("main.tex"),
        include_str!("../../../benchmarks/corpus/index/main.tex"),
    )
    .unwrap();
    let indexer = directory.join("makeindex");
    fs::write(
        &indexer,
        "#!/bin/sh\nprintf '%s\\n' '\\begin{theindex}' '\\item alpha, 1' '\\end{theindex}' > \"$1.ind\"\n",
    )
    .unwrap();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(&indexer, fs::Permissions::from_mode(0o755)).unwrap();
    }
    let old_path = std::env::var("PATH").unwrap_or_default();
    let status = Command::new(binary())
        .current_dir(&directory)
        .env("PATH", format!("{}:{old_path}", directory.display()))
        .args(["-output-directory=out", "main.tex"])
        .status()
        .unwrap();
    assert!(status.success());
    assert!(directory.join("out/main.pdf").is_file());
    assert!(directory.join("out/main.ind").is_file());
}

#[test]
#[cfg(feature = "embedded")]
fn embedded_indexer_failure_is_not_reported_as_success() {
    let directory = temporary("embedded-index-failure");
    fs::write(
        directory.join("main.tex"),
        include_str!("../../../benchmarks/corpus/index/main.tex"),
    )
    .unwrap();
    let indexer = directory.join("makeindex");
    fs::write(&indexer, "#!/bin/sh\nexit 42\n").unwrap();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(&indexer, fs::Permissions::from_mode(0o755)).unwrap();
    }
    let trace = directory.join("trace.jsonl");
    let old_path = std::env::var("PATH").unwrap_or_default();
    let output = Command::new(binary())
        .current_dir(&directory)
        .env("PATH", format!("{}:{old_path}", directory.display()))
        .env("TECTDIST_TRACE_FILE", &trace)
        .arg("main.tex")
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(42));
    assert!(String::from_utf8_lossy(&output.stderr).contains("makeindex failed"));
    let trace = fs::read_to_string(trace).unwrap();
    assert!(trace.contains("indexer.run"));
}

#[test]
#[cfg(feature = "embedded")]
fn embedded_glossary_uses_makeindex_style_arguments() {
    let directory = temporary("embedded-glossary");
    fs::write(
        directory.join("main.tex"),
        include_str!("../../../benchmarks/corpus/glossary/main.tex"),
    )
    .unwrap();
    let indexer = directory.join("makeindex");
    let log = directory.join("makeindex.argv");
    fs::write(
        &indexer,
        format!(
            "#!/bin/sh\nprintf '%s\\n' \"$@\" > '{}'\nexit 42\n",
            log.display()
        ),
    )
    .unwrap();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(&indexer, fs::Permissions::from_mode(0o755)).unwrap();
    }
    let old_path = std::env::var("PATH").unwrap_or_default();
    let output = Command::new(binary())
        .current_dir(&directory)
        .env("PATH", format!("{}:{old_path}", directory.display()))
        .arg("main.tex")
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(42));
    assert_eq!(
        fs::read_to_string(log).unwrap(),
        "-s\nmain.ist\n-t\nmain.glg\n-o\nmain.gls\nmain.glo\n"
    );
}
