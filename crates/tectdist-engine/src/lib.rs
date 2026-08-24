//! Engine executor boundary. The external executor is usable now; embedding
//! is gated on an audited, pinned Tectonic driver API.
use std::io;
use std::process::Command;
#[cfg(feature = "embedded")]
use std::time::Instant;
use tectdist_core::{EngineSelection, ExecutionEvent, ExecutionResult};
#[cfg(feature = "embedded")]
pub mod observer;
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

/// Output artifact retention policy (plan X2.2).
#[cfg(feature = "embedded")]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RetentionPolicy {
    /// Traditional artifacts: PDF, logs, and all intermediates (default).
    Compat,
    /// PDF plus logs and requested SyncTeX output only.
    Minimal,
    /// Nothing beyond the requested final outputs.
    Internal,
}

#[cfg(feature = "embedded")]
impl RetentionPolicy {
    fn keep_logs(self) -> bool {
        matches!(self, RetentionPolicy::Compat | RetentionPolicy::Minimal)
    }

    fn keep_intermediates(self) -> bool {
        self == RetentionPolicy::Compat
    }
}

/// One configuration and resource context per process (plan X2.1).
///
/// The persistent configuration, format-cache path, and opened bundle are
/// resolved once and reused by every session in this process, including an
/// index/glossary continuation. The bundle is shared behind a mutex because
/// Tectonic's builder consumes it; driver I/O is single-threaded, so locking
/// is uncontended.
#[cfg(feature = "embedded")]
pub struct EngineContext {
    // Retained so bundle identity and cache paths stay pinned to one
    // configuration for the whole process lifetime.
    #[allow(dead_code)]
    config: tectonic::config::PersistentConfig,
    format_cache: std::path::PathBuf,
    bundle:
        std::sync::Arc<std::sync::Mutex<Box<dyn tectonic_bundles::Bundle>>>,
    io_counters: std::sync::Arc<observer::BundleIoCounters>,
    /// Names the bundle answered NotAvailable for. The bundle is immutable,
    /// so a miss is final for the whole process; rerun passes re-probe many
    /// of these names and would otherwise pay full bundle resolution again
    /// (plan X4.3).
    negative_cache: std::sync::Arc<std::sync::Mutex<std::collections::HashSet<String>>>,
}

#[cfg(feature = "embedded")]
impl EngineContext {
    pub fn open() -> io::Result<Self> {
        let config = tectonic::config::PersistentConfig::open(false).map_err(|error| {
            io::Error::other(format!("embedded Tectonic config: {error}"))
        })?;
        let bundle = config
            .default_bundle(false)
            .map_err(|error| io::Error::other(format!("embedded Tectonic bundle: {error}")))?;
        let format_cache = config.format_cache_path().map_err(|error| {
            io::Error::other(format!("embedded Tectonic format cache: {error}"))
        })?;
        Ok(Self {
            config,
            format_cache,
            bundle: std::sync::Arc::new(std::sync::Mutex::new(bundle)),
            io_counters: std::sync::Arc::new(observer::BundleIoCounters::default()),
            negative_cache: std::sync::Arc::new(std::sync::Mutex::new(
                std::collections::HashSet::new(),
            )),
        })
    }

    /// A per-session view of the shared context's bundle with I/O counting
    /// and the shared negative-open cache.
    fn context_bundle(&self) -> ContextBundle {
        ContextBundle {
            bundle: self.bundle.clone(),
            counters: self.io_counters.clone(),
            negative_cache: self.negative_cache.clone(),
        }
    }
}

/// A per-session adapter sharing one context's bundle across sessions while
/// timing and counting every engine read of bundle resources (plans X1.2/X2.1).
#[cfg(feature = "embedded")]
struct ContextBundle {
    bundle: std::sync::Arc<std::sync::Mutex<Box<dyn tectonic_bundles::Bundle>>>,
    counters: std::sync::Arc<observer::BundleIoCounters>,
    negative_cache: std::sync::Arc<
        std::sync::Mutex<std::collections::HashSet<String>>,
    >,
}

#[cfg(feature = "embedded")]
impl tectonic::io::IoProvider for ContextBundle {
    fn input_open_name(
        &mut self,
        name: &str,
        status: &mut dyn tectonic::status::StatusBackend,
    ) -> tectonic::io::OpenResult<tectonic::io::InputHandle> {
        if self.negative_cache.lock().expect("negative cache poisoned").contains(name) {
            return tectonic::io::OpenResult::NotAvailable;
        }
        let started = Instant::now();
        let result = self
            .bundle
            .lock()
            .expect("context bundle mutex poisoned")
            .input_open_name(name, status);
        let outcome = match &result {
            tectonic::io::OpenResult::Ok(_) => 0u8,
            tectonic::io::OpenResult::NotAvailable => {
                self.negative_cache
                    .lock()
                    .expect("negative cache poisoned")
                    .insert(name.to_string());
                1u8
            }
            tectonic::io::OpenResult::Err(_) => 2u8,
        };
        self.counters.record(started.elapsed(), outcome);
        result
    }
}

#[cfg(feature = "embedded")]
impl tectonic_bundles::Bundle for ContextBundle {
    fn get_digest(&mut self) -> tectonic::Result<tectonic::io::digest::DigestData> {
        self.bundle
            .lock()
            .expect("context bundle mutex poisoned")
            .get_digest()
    }

    fn all_files(&self) -> Vec<String> {
        self.bundle
            .lock()
            .expect("context bundle mutex poisoned")
            .all_files()
    }
}

pub struct EmbeddedTectonicExecutor {
    #[cfg(feature = "embedded")]
    context: std::sync::Mutex<Option<EngineContext>>,
}

impl Default for EmbeddedTectonicExecutor {
    fn default() -> Self {
        Self {
            #[cfg(feature = "embedded")]
            context: std::sync::Mutex::new(None),
        }
    }
}

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

        // Intentional output retention (plan X2.2). The default `compat`
        // keeps traditional artifacts exactly as before; `minimal` keeps only
        // the PDF plus logs/SyncTeX; `internal` retains nothing beyond the
        // requested outputs.
        let retention = match std::env::var("TECTDIST_OUTPUT_RETENTION").as_deref() {
            Ok("minimal") => RetentionPolicy::Minimal,
            Ok("internal") => RetentionPolicy::Internal,
            _ => RetentionPolicy::Compat,
        };
        let security = SecuritySettings::new(if allow_insecures {
            SecurityStance::MaybeAllowInsecures
        } else {
            SecurityStance::DisableInsecures
        });
        // One configuration and resource context per process (plan X2.1):
        // repeated invocations in this process, including index continuation,
        // reuse configuration, bundle, and format-cache resolution.
        let context_started = Instant::now();
        let mut guard = self.context.lock().unwrap();
        let context_cold = guard.is_none();
        if guard.is_none() {
            *guard = Some(EngineContext::open()?);
        }
        let context = guard.as_ref().unwrap();
        let context_setup_duration = context_started.elapsed();
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
        // Observe engine-internal stages (TeX passes, BibTeX, Biber, PDF
        // conversion) by recognising the driver's stage notes; user-visible
        // status output is unchanged (plan X1.1).
        let mut observing_status = observer::ObservingStatusBackend::new(status.as_mut());
        let mut builder = tectonic::driver::ProcessingSessionBuilder::new_with_security(security);
        builder
            .unstables(unstable)
            .bundle(Box::new(context.context_bundle()))
            .primary_input_path(input)
            .tex_input_name(input_name)
            .format_name(format)
            .format_cache_path(&context.format_cache)
            .output_dir(&plan.output_dir)
            .output_format(if plan.first_pass_xdv {
                tectonic::driver::OutputFormat::Xdv
            } else {
                tectonic::driver::OutputFormat::Pdf
            })
            .keep_logs(retention.keep_logs())
            .keep_intermediates(retention.keep_intermediates())
            .synctex(synctex)
            .print_stdout(false)
            .build_date_from_env(false);
        if let Some(work_dir) = shell_escape_work_dir {
            builder.shell_escape_with_work_dir(work_dir);
        }
        let session_started = Instant::now();
        let mut session = builder
            .create(&mut observing_status as &mut dyn tectonic::status::StatusBackend)
            .map_err(|error| io::Error::other(format!("embedded Tectonic setup: {error}")))?;
        let session_duration = session_started.elapsed();
        let pass_started = Instant::now();
        session
            .run(&mut observing_status as &mut dyn tectonic::status::StatusBackend)
            .map_err(|error| io::Error::other(format!("embedded Tectonic: {error}")))?;

        let pass_duration = pass_started.elapsed();
        let stage_records = observing_status.finish();
        let stem_os = input.file_stem().ok_or_else(|| {
            io::Error::new(io::ErrorKind::InvalidInput, "input has no file stem")
        })?;
        let output = plan.output_dir.join(stem_os).with_extension("pdf");
        if !plan.first_pass_xdv && !output.is_file() {
            return Err(io::Error::new(
                io::ErrorKind::NotFound,
                "embedded Tectonic completed without a PDF output",
            ));
        }
        // The XDV intermediate is the deliverable of an XDV-first pass.
        let xdv_output = plan.output_dir.join(stem_os).with_extension("xdv");
        if plan.first_pass_xdv && !xdv_output.is_file() {
            return Err(io::Error::new(
                io::ErrorKind::NotFound,
                "embedded Tectonic completed without an XDV output",
            ));
        }
        let mut generated_files = Vec::new();
        if output.is_file() {
            generated_files.push(output.clone());
        }
        if plan.first_pass_xdv && xdv_output.is_file() {
            generated_files.push(xdv_output);
        }
        let mut events = vec![
            ExecutionEvent {
                name: "engine.embedded",
                value: "tectonic@0.17.0".into(),
                duration_ns: 0,
            },
            ExecutionEvent {
                // Reports full setup on a cold context, near-zero when an
                // existing context is reused (index continuation).
                name: if context_cold { "engine.config" } else { "engine.context.reuse" },
                value: "persistent-config".into(),
                duration_ns: context_setup_duration.as_nanos(),
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
        ];
        // Per-stage records observed inside the driver run (plan X1.1).
        for record in &stage_records {
            events.push(ExecutionEvent {
                name: record.stage.event_name(),
                value: record.stage.label(),
                duration_ns: record.duration.as_nanos(),
            });
        }
        events.push(ExecutionEvent {
            name: "engine.io.bundle_reads",
            value: format!(
                "opens={} hits={} misses={} errors={} duration_us={}",
                context.io_counters.open_count.load(std::sync::atomic::Ordering::Relaxed),
                context.io_counters.hit_count.load(std::sync::atomic::Ordering::Relaxed),
                context.io_counters.miss_count.load(std::sync::atomic::Ordering::Relaxed),
                context.io_counters.error_count.load(std::sync::atomic::Ordering::Relaxed),
                context.io_counters.open_duration_us.load(std::sync::atomic::Ordering::Relaxed),
            ),
            duration_ns: context
                .io_counters
                .open_duration_us
                .load(std::sync::atomic::Ordering::Relaxed)
                as u128
                * 1000,
        });
        events.push(ExecutionEvent {
            name: "artifact.pdf",
            value: output.display().to_string(),
            duration_ns: 0,
        });
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
