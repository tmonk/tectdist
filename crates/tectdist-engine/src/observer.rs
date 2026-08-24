//! Stage-level observation of the embedded Tectonic processing driver
//! (plan workstream X1).
//!
//! The pinned driver emits distinct status notes when each internal stage
//! begins ("Running TeX", "Rerunning TeX", "Running BibTeX", "Running
//! xdvipdfmx", "Running external tool", "generating format"). Wrapping the
//! caller's status backend therefore yields per-stage wall-clock timings and
//! counters without forking the engine. The design is deliberately
//! upstreamable: an upstream version would add explicit observer callbacks to
//! the driver loop instead of matching note text.

use std::fmt::Arguments;
use std::time::{Duration, Instant};
use tectonic::io::OpenResult;
use tectonic::status::{MessageKind, StatusBackend};

/// A named engine stage observed during one processing session.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Stage {
    FormatGeneration,
    TexPass,
    Bibtex,
    ExternalTool(String),
    Xdvipdfmx,
}

impl Stage {
    pub fn event_name(&self) -> &'static str {
        match self {
            Stage::FormatGeneration => "engine.stage.format_generation",
            Stage::TexPass => "engine.stage.tex_pass",
            Stage::Bibtex => "engine.stage.bibtex",
            Stage::ExternalTool(_) => "engine.stage.external_tool",
            Stage::Xdvipdfmx => "engine.stage.xdvipdfmx",
        }
    }

    /// Stable short label used by stage-budget reports.
    pub fn label(&self) -> String {
        match self {
            Stage::FormatGeneration => "format_generation".into(),
            Stage::TexPass => "tex_pass".into(),
            Stage::Bibtex => "bibtex".into(),
            Stage::ExternalTool(name) => format!("external_tool:{name}"),
            Stage::Xdvipdfmx => "xdvipdfmx".into(),
        }
    }
}

/// One completed stage interval with its monotonic wall duration.
#[derive(Debug, Clone)]
pub struct StageRecord {
    pub stage: Stage,
    pub duration: Duration,
}

enum TraceState {
    Idle,
    InStage { stage: Stage, started: Instant },
}

/// A status backend that recognises driver stage notes and records timings,
/// forwarding every message unchanged to the wrapped backend so user-visible
/// output is identical with and without observation.
pub struct ObservingStatusBackend<'a> {
    inner: &'a mut dyn StatusBackend,
    state: TraceState,
    completed: Vec<StageRecord>,
}

impl<'a> ObservingStatusBackend<'a> {
    pub fn new(inner: &'a mut dyn StatusBackend) -> Self {
        ObservingStatusBackend { inner, state: TraceState::Idle, completed: Vec::new() }
    }

    fn classify(message: &str) -> Option<Stage> {
        // Order matters: match the most specific prefixes first.
        if message.starts_with("Running BibTeX") {
            Some(Stage::Bibtex)
        } else if message.starts_with("Running xdvipdfmx") {
            Some(Stage::Xdvipdfmx)
        } else if let rest @ ("Running TeX" | "Rerunning TeX") = &message[..message.len().min(13)] {
            let _ = rest;
            Some(Stage::TexPass)
        } else if let Some(rest) = message.strip_prefix("Running external tool ") {
            let name = rest.split_whitespace().next().unwrap_or("unknown").to_string();
            Some(Stage::ExternalTool(name))
        } else if message.contains("generating format") {
            Some(Stage::FormatGeneration)
        } else {
            None
        }
    }

    fn open_stage(&mut self, stage: Stage) {
        self.close_stage();
        self.state = TraceState::InStage { stage, started: Instant::now() };
    }

    fn close_stage(&mut self) {
        if let TraceState::InStage { stage, started } =
            std::mem::replace(&mut self.state, TraceState::Idle)
        {
            self.completed.push(StageRecord { stage, duration: started.elapsed() });
        }
    }

    /// Close any open stage and return all observed stage records.
    pub fn finish(&mut self) -> Vec<StageRecord> {
        self.close_stage();
        std::mem::take(&mut self.completed)
    }
}

impl StatusBackend for ObservingStatusBackend<'_> {
    fn report(&mut self, kind: MessageKind, args: Arguments, err: Option<&tectonic::Error>) {
        if matches!(kind, MessageKind::Note) {
            let message = args.to_string();
            if let Some(stage) = Self::classify(&message) {
                self.open_stage(stage);
            }
        }
        self.inner.report(kind, args, err);
    }

    fn report_error(&mut self, err: &tectonic::Error) {
        self.inner.report_error(err);
    }

    fn dump_error_logs(&mut self, output: &[u8]) {
        self.inner.dump_error_logs(output);
    }
}

/// Counters for bundle I/O observed while the engine reads support files.
/// Shared atomically so the executor can retain a handle after the bundle is
/// moved into the processing session.
#[derive(Debug, Default)]
pub struct BundleIoCounters {
    pub open_count: std::sync::atomic::AtomicU64,
    pub hit_count: std::sync::atomic::AtomicU64,
    pub miss_count: std::sync::atomic::AtomicU64,
    pub error_count: std::sync::atomic::AtomicU64,
    /// Cumulative time spent opening bundle inputs, in microseconds.
    pub open_duration_us: std::sync::atomic::AtomicU64,
}

impl BundleIoCounters {
    pub(crate) fn record(&self, duration: Duration, outcome: u8) {
        use std::sync::atomic::Ordering::Relaxed;
        self.open_count.fetch_add(1, Relaxed);
        self.open_duration_us
            .fetch_add(duration.as_micros() as u64, Relaxed);
        match outcome {
            0 => self.hit_count.fetch_add(1, Relaxed),
            1 => self.miss_count.fetch_add(1, Relaxed),
            _ => self.error_count.fetch_add(1, Relaxed),
        };
    }
}

/// A bundle wrapper that times and counts engine reads of bundle resources
/// (plan X1.2 file-event counters). Delegation is transparent.
pub struct ObservingBundle<B> {
    inner: B,
    counters: std::sync::Arc<BundleIoCounters>,
}

impl<B> ObservingBundle<B> {
    pub fn new(inner: B) -> Self {
        ObservingBundle { inner, counters: std::sync::Arc::new(BundleIoCounters::default()) }
    }

    /// A handle to this bundle's counters; valid after the bundle is consumed.
    pub fn counters(&self) -> std::sync::Arc<BundleIoCounters> {
        self.counters.clone()
    }
}

impl<B: tectonic::io::IoProvider> tectonic::io::IoProvider for ObservingBundle<B> {
    fn input_open_name(
        &mut self,
        name: &str,
        status: &mut dyn StatusBackend,
    ) -> OpenResult<tectonic::io::InputHandle> {
        let started = Instant::now();
        let result = self.inner.input_open_name(name, status);
        let outcome = match &result {
            OpenResult::Ok(_) => 0u8,
            OpenResult::NotAvailable => 1u8,
            OpenResult::Err(_) => 2u8,
        };
        self.counters.record(started.elapsed(), outcome);
        result
    }
}

impl<B: tectonic_bundles::Bundle> tectonic_bundles::Bundle for ObservingBundle<B> {
    fn get_digest(&mut self) -> tectonic::Result<tectonic::io::digest::DigestData> {
        self.inner.get_digest()
    }

    fn all_files(&self) -> Vec<String> {
        self.inner.all_files()
    }
}
