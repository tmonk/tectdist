//! Engine executor boundary. The external executor is usable now; embedding
//! is gated on an audited, pinned Tectonic driver API.
use std::io;
use std::process::Command;
#[cfg(feature = "embedded")]
use std::time::Instant;
use tectdist_core::{EngineSelection, ExecutionEvent, ExecutionResult};
#[cfg(feature = "embedded")]
use tectonic::unstable_opts::UnstableOptions;
#[cfg(feature = "embedded")]
use tectonic_bridge_core::{SecuritySettings, SecurityStance};

pub trait Executor {
    fn execute(&self, plan: &tectdist_core::CompilationPlan) -> io::Result<ExecutionResult>;
}

pub struct ExternalTectonicExecutor;
impl Executor for ExternalTectonicExecutor {
    fn execute(&self, plan: &tectdist_core::CompilationPlan) -> io::Result<ExecutionResult> {
        let EngineSelection::External(engine) = &plan.engine else {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "external executor received embedded plan",
            ));
        };
        let status = Command::new(&engine.path)
            .args(&plan.engine_args)
            .status()?;
        Ok(ExecutionResult {
            status: status.code().unwrap_or(128),
            engine_passes: 1,
            generated_files: Vec::new(),
            events: vec![
                ExecutionEvent {
                    name: "engine.spawn",
                    value: engine.path.display().to_string(),
                    duration_ns: 0,
                },
                ExecutionEvent {
                    name: "engine.run",
                    value: "pass=1".into(),
                    duration_ns: 0,
                },
            ],
        })
    }
}

pub struct EmbeddedTectonicExecutor;

#[cfg(feature = "embedded")]
impl Executor for EmbeddedTectonicExecutor {
    fn execute(&self, plan: &tectdist_core::CompilationPlan) -> io::Result<ExecutionResult> {
        let input = plan.input.as_ref().ok_or_else(|| {
            io::Error::new(
                io::ErrorKind::InvalidInput,
                "embedded mode requires an input file",
            )
        })?;

        let mut format = "latex";
        let mut synctex = false;
        let mut quiet = false;
        let mut unstable = UnstableOptions::default();
        let mut allow_insecures = false;
        let mut shell_escape_work_dir = None;
        let mut args = plan.engine_args.iter();
        while let Some(argument) = args.next() {
            match argument.to_str() {
                Some("-f") => {
                    format = args
                        .next()
                        .and_then(|value| value.to_str())
                        .ok_or_else(|| {
                            io::Error::new(io::ErrorKind::InvalidInput, "-f requires a format")
                        })?;
                }
                Some("--synctex") => synctex = true,
                Some("--chatter") => {
                    quiet = matches!(
                        args.next().and_then(|value| value.to_str()),
                        Some("minimal")
                    );
                }
                Some("-Z") => {
                    let option = args
                        .next()
                        .and_then(|value| value.to_str())
                        .ok_or_else(|| {
                            io::Error::new(io::ErrorKind::InvalidInput, "-Z requires an option")
                        })?;
                    if option == "shell-escape" {
                        unstable.shell_escape = true;
                        allow_insecures = true;
                        shell_escape_work_dir = Some(std::env::current_dir()?);
                    } else if let Some(path) = option.strip_prefix("search-path=") {
                        if path.is_empty() {
                            return Err(io::Error::new(
                                io::ErrorKind::InvalidInput,
                                "-Z search-path requires a non-empty path",
                            ));
                        }
                        unstable.extra_search_paths.push(path.into());
                        allow_insecures = true;
                    } else if let Some(path) = option.strip_prefix("shell-escape-cwd=") {
                        if path.is_empty() {
                            return Err(io::Error::new(
                                io::ErrorKind::InvalidInput,
                                "-Z shell-escape-cwd requires a non-empty path",
                            ));
                        }
                        unstable.shell_escape = true;
                        unstable.shell_escape_cwd = Some(path.into());
                        allow_insecures = true;
                        shell_escape_work_dir = Some(path.into());
                    } else {
                        return Err(io::Error::new(
                            io::ErrorKind::Unsupported,
                            format!("embedded mode does not support Tectonic -Z {option}"),
                        ));
                    }
                }
                _ => {}
            }
        }

        let input_name = input
            .file_name()
            .and_then(|name| name.to_str())
            .ok_or_else(|| {
                io::Error::new(io::ErrorKind::InvalidInput, "input has no UTF-8 file name")
            })?;
        std::fs::create_dir_all(&plan.output_dir)?;

        let configuration_started = Instant::now();
        let config = tectonic::config::PersistentConfig::open(false)
            .map_err(|error| io::Error::other(format!("embedded Tectonic config: {error}")))?;
        let configuration_duration = configuration_started.elapsed();
        let bundle_started = Instant::now();
        let bundle = config
            .default_bundle(false)
            .map_err(|error| io::Error::other(format!("embedded Tectonic bundle: {error}")))?;
        let bundle_duration = bundle_started.elapsed();
        let format_cache_started = Instant::now();
        let format_cache = config.format_cache_path().map_err(|error| {
            io::Error::other(format!("embedded Tectonic format cache: {error}"))
        })?;
        let format_cache_duration = format_cache_started.elapsed();
        let security = SecuritySettings::new(if allow_insecures {
            SecurityStance::MaybeAllowInsecures
        } else {
            SecurityStance::DisableInsecures
        });
        let mut builder = tectonic::driver::ProcessingSessionBuilder::new_with_security(security);
        builder
            .unstables(unstable)
            .bundle(bundle)
            .primary_input_path(input)
            .tex_input_name(input_name)
            .format_name(format)
            .format_cache_path(format_cache)
            .output_dir(&plan.output_dir)
            .output_format(tectonic::driver::OutputFormat::Pdf)
            .keep_logs(true)
            .keep_intermediates(true)
            .synctex(synctex)
            .print_stdout(false)
            .build_date_from_env(false);
        if let Some(work_dir) = shell_escape_work_dir {
            builder.shell_escape_with_work_dir(work_dir);
        }
        // Preserve normal compiler diagnostics while keeping
        // `-interaction=batchmode` quiet. No formatting work is paid when
        // output is suppressed.
        let mut status: Box<dyn tectonic::status::StatusBackend> = if quiet {
            Box::new(tectonic::status::NoopStatusBackend::default())
        } else {
            Box::new(tectonic::status::termcolor::TermcolorStatusBackend::new(
                tectonic::status::ChatterLevel::Normal,
            ))
        };
        let session_started = Instant::now();
        let mut session = builder
            .create(status.as_mut())
            .map_err(|error| io::Error::other(format!("embedded Tectonic setup: {error}")))?;
        let session_duration = session_started.elapsed();
        let pass_started = Instant::now();
        session
            .run(status.as_mut())
            .map_err(|error| io::Error::other(format!("embedded Tectonic: {error}")))?;

        let pass_duration = pass_started.elapsed();
        let output = plan
            .output_dir
            .join(input.file_stem().ok_or_else(|| {
                io::Error::new(io::ErrorKind::InvalidInput, "input has no file stem")
            })?)
            .with_extension("pdf");
        if !output.is_file() {
            return Err(io::Error::new(
                io::ErrorKind::NotFound,
                "embedded Tectonic completed without a PDF output",
            ));
        }
        let mut generated_files = vec![output.clone()];
        let mut events = vec![
            ExecutionEvent {
                name: "engine.embedded",
                value: "tectonic@0.17.0".into(),
                duration_ns: 0,
            },
            ExecutionEvent {
                name: "engine.config",
                value: "persistent-config".into(),
                duration_ns: configuration_duration.as_nanos(),
            },
            ExecutionEvent {
                name: "bundle.open",
                value: "default-bundle".into(),
                duration_ns: bundle_duration.as_nanos(),
            },
            ExecutionEvent {
                name: "format_cache.resolve",
                value: "format-cache-path".into(),
                duration_ns: format_cache_duration.as_nanos(),
            },
            ExecutionEvent {
                name: "engine.session_create",
                value: "processing-session".into(),
                duration_ns: session_duration.as_nanos(),
            },
            ExecutionEvent {
                name: "engine.pass",
                value: "1".into(),
                duration_ns: pass_duration.as_nanos(),
            },
            ExecutionEvent {
                name: "artifact.pdf",
                value: output.display().to_string(),
                duration_ns: 0,
            },
        ];
        let stem = input
            .file_stem()
            .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidInput, "input has no file stem"))?;
        for (extension, event_name) in [
            ("aux", "artifact.aux"),
            ("toc", "artifact.toc"),
            ("idx", "artifact.idx"),
            ("ind", "artifact.ind"),
            ("glo", "artifact.glo"),
            ("gls", "artifact.gls"),
            ("ist", "artifact.ist"),
            ("bcf", "artifact.bcf"),
            ("bbl", "artifact.bbl"),
            ("run.xml", "artifact.run_xml"),
        ] {
            let artifact = plan.output_dir.join(stem).with_extension(extension);
            if artifact.is_file() {
                generated_files.push(artifact.clone());
                events.push(ExecutionEvent {
                    name: event_name,
                    value: artifact.display().to_string(),
                    duration_ns: 0,
                });
            }
        }
        Ok(ExecutionResult {
            status: 0,
            engine_passes: 1,
            generated_files,
            events,
        })
    }
}

#[cfg(not(feature = "embedded"))]
impl Executor for EmbeddedTectonicExecutor {
    fn execute(&self, _: &tectdist_core::CompilationPlan) -> io::Result<ExecutionResult> {
        Err(io::Error::new(
            io::ErrorKind::Unsupported,
            "embedded Tectonic support requires the pinned driver feature",
        ))
    }
}
