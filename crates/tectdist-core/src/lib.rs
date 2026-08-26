//! Compatibility planning model shared by all native executors.
pub mod backend;
pub mod runtime;
pub mod snapshot;
use std::ffi::OsString;
use std::path::PathBuf;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Invocation {
    pub invoked_name: OsString,
    pub args: Vec<OsString>,
    pub cwd: PathBuf,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ResolvedExternalEngine {
    pub path: PathBuf,
    pub canonical_path: PathBuf,
    pub version: Option<String>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum EngineSelection {
    External(ResolvedExternalEngine),
    /// Configuration is intentionally separate so the embedded executor can
    /// be introduced without changing compatibility planning.
    Embedded(EmbeddedEngineConfig),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EmbeddedEngineConfig {
    pub build_identity: String,
    pub bundle_identity: Option<String>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum IndexStrategy {
    NoIndexCheck,
    ExpectedStem(PathBuf),
    DirectoryScan,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompilationPlan {
    pub logical_program: OsString,
    pub engine: EngineSelection,
    pub input: Option<PathBuf>,
    pub output_dir: PathBuf,
    pub job_name: Option<OsString>,
    pub engine_args: Vec<OsString>,
    pub index_strategy: IndexStrategy,
    /// Plan X5.2: when an index/glossary run is expected, the first session
    /// stops at the XDV stage so no PDF conversion is performed that would
    /// immediately be discarded; the continuation session emits the final PDF.
    pub first_pass_xdv: bool,
    pub diagnostics: Vec<Diagnostic>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DiagnosticKind {
    InvalidInvocation,
    EngineNotFound,
    EngineNotExecutable,
    PairingMismatch,
    UnsupportedFormat,
    ExternalToolUnavailable,
    ExternalToolFailed,
    OutputRenameFailed,
    RequiredStageSkipped,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Diagnostic {
    pub kind: DiagnosticKind,
    pub message: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ExecutionEvent {
    pub name: &'static str,
    pub value: String,
    /// Stage duration measured by the executor. Zero denotes a discrete
    /// event (for example an external-process spawn) rather than a timed
    /// stage. Keeping this in the shared result makes trace consumers avoid
    /// inferring engine work from filesystem timestamps.
    pub duration_ns: u128,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ExecutionResult {
    pub status: i32,
    pub engine_passes: u32,
    pub generated_files: Vec<PathBuf>,
    pub events: Vec<ExecutionEvent>,
}
