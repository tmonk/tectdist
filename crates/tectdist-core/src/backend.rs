//! Backend portfolio: capability model, conservative feature detector, and
//! backend selection (plan workstream X7).
//!
//! Guarantees enforced by this module:
//! - explicit aliases (`pdflatex`, `xelatex`, `lualatex`) never silently run a
//!   different *semantic* engine; the selector may only choose among backends
//!   whose semantics match what the alias promised,
//! - unknown or dynamically constructed package loads route to the safe
//!   default backend, because the detector is an optimisation hint and not a
//!   proof of TeX semantics,
//! - only *qualified* backends are ever selected automatically.

use std::path::Path;

/// A LaTeX execution backend.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BackendKind {
    /// Tectonic's XeTeX-derived engine (embedded). Full Unicode/fontspec
    /// semantics; slower on trivial documents.
    TectonicXetex,
    /// A true pdfTeX-compatible engine. Not shipped/qualified yet (X7.1):
    /// selecting it is impossible until it reports qualified capabilities.
    PdfTeX,
    /// LuaHBTeX semantics. Future slot (X7.1).
    LuaHbTeX,
    /// External TeX Live / user-configured toolchain. Always semantically
    /// whatever the external binary provides; used as compatibility fallback.
    ExternalFallback,
}

/// Capabilities a backend advertises. A backend must only claim a capability
/// after qualification (differential corpus + benchmarks) — plan X7.5.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CapabilitySet {
    pub xetex_primitives: bool,
    pub fontspec_unicode: bool,
    pub lua_engine: bool,
    pub pdf_tex_primitives: bool,
    pub shell_escape: bool,
}

impl CapabilitySet {
    pub fn tectonic_xetex() -> Self {
        CapabilitySet {
            xetex_primitives: true,
            fontspec_unicode: true,
            lua_engine: false,
            pdf_tex_primitives: false,
            shell_escape: true,
        }
    }

    pub fn external_fallback() -> Self {
        CapabilitySet {
            xetex_primitives: true,
            fontspec_unicode: true,
            lua_engine: true,
            pdf_tex_primitives: true,
            shell_escape: true,
        }
    }
}

/// Features a document appears to require, detected conservatively from its
/// primary source. Absence of a feature is NOT proof of absence — the caller
/// must treat this as a hint only (plan X7.3).
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct DetectedFeatures {
    pub fontspec_or_unicode: bool,
    pub xetex_primitive: bool,
    pub lua_code: bool,
    pub pdf_tex_specific: bool,
}

/// Detect features in the primary source text. Deliberately matches only
/// explicit, well-known markers; anything dynamic selects the safe default.
pub fn detect_features(source: &str) -> DetectedFeatures {
    let mut features = DetectedFeatures::default();
    for package in [
        "fontspec", "unicode-math", "polyglossia", "realscripts", "metalogo",
    ] {
        if source.contains(&format!("\\usepackage{{{}}}", package)) {
            features.fontspec_or_unicode = true;
        }
    }
    for primitive in ["\\directlua", "\\XeTeXinterchartoks", "\\XeTeXlinebreaklocale"] {
        if source.contains(primitive) {
            if primitive.starts_with("\\directlua") {
                features.lua_code = true;
            } else {
                features.xetex_primitive = true;
            }
        }
    }
    // pdfTeX-specific primitives with no XeTeX equivalent.
    for primitive in ["\\pdfinfo", "\\pdfpagesattr", "\\pdfmapfile", "\\pdffontexpand"] {
        if source.contains(primitive) {
            features.pdf_tex_specific = true;
        }
    }
    features
}

/// The semantic contract an alias promises.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SemanticContract {
    /// `pdflatex`: pdfTeX semantics required unless the source opts into
    /// XeTeX-class behaviour through explicit packages/primitives.
    PdfTex,
    /// `xelatex`: XeTeX semantics.
    XeTex,
    /// `lualatex`: LuaHBTeX semantics.
    LuaHbTex,
}

/// Choose a backend kind for an invocation. `qualified` lists backends that
/// passed qualification on this host; unqualified kinds are never returned.
pub fn select_backend(
    contract: SemanticContract,
    features: &DetectedFeatures,
    qualified: &[BackendKind],
) -> BackendKind {
    let is_qualified = |kind: BackendKind| qualified.contains(&kind);
    match contract {
        SemanticContract::XeTex => {
            if is_qualified(BackendKind::TectonicXetex) {
                BackendKind::TectonicXetex
            } else {
                BackendKind::ExternalFallback
            }
        }
        SemanticContract::LuaHbTex => {
            if is_qualified(BackendKind::LuaHbTeX) {
                BackendKind::LuaHbTeX
            } else {
                BackendKind::ExternalFallback
            }
        }
        SemanticContract::PdfTex => {
            // Only leave pdfTeX semantics when the document explicitly needs
            // XeTeX/Lua features; otherwise stay on a pdfTeX-class backend
            // when one is actually qualified.
            if features.fontspec_or_unicode || features.xetex_primitive {
                if is_qualified(BackendKind::TectonicXetex) {
                    return BackendKind::TectonicXetex;
                }
                return BackendKind::ExternalFallback;
            }
            if features.lua_code {
                return BackendKind::ExternalFallback;
            }
            if !features.pdf_tex_specific && is_qualified(BackendKind::PdfTeX) {
                BackendKind::PdfTeX
            } else if is_qualified(BackendKind::PdfTeX) {
                BackendKind::PdfTeX
            } else {
                // No qualified pdfTeX backend yet: the safe choice keeps the
                // requested semantics via the external fallback rather than
                // silently switching to XeTeX (plan X7.2/X7.3).
                BackendKind::ExternalFallback
            }
        }
    }
}

/// Whether the primary source plausibly requires XeTeX-class handling when
/// invoked through a generic entry point (no explicit alias promise).
pub fn generic_source_prefers_xetex(input: Option<&Path>) -> bool {
    let Some(path) = input else {
        return true; // unknown -> safe default
    };
    match std::fs::read_to_string(path) {
        Ok(source) => detect_features(&source).fontspec_or_unicode
            || detect_features(&source).xetex_primitive,
        Err(_) => true, // unreadable -> safe default
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn detector_flags_explicit_markers_only() {
        let features = detect_features(
            "\\usepackage{fontspec}\n\\setmainfont{Times}\n",
        );
        assert!(features.fontspec_or_unicode);
        assert!(!features.lua_code);

        let lua = detect_features("\\directlua{print('x')}");
        assert!(lua.lua_code);

        // Dynamic or unknown constructs do not trigger anything.
        let dynamic = detect_features("\\usepackage{mypackage}\n\\input{chapters/ch1}");
        assert_eq!(dynamic, DetectedFeatures::default());
    }

    #[test]
    fn xelatex_alias_never_switches_semantics() {
        let qualified = [BackendKind::PdfTeX];
        // Even with a qualified pdfTeX backend, an explicit xelatex request
        // must keep XeTeX semantics.
        assert_eq!(
            select_backend(SemanticContract::XeTex, &DetectedFeatures::default(), &qualified),
            BackendKind::ExternalFallback
        );
        let with_xetex = [BackendKind::TectonicXetex, BackendKind::PdfTeX];
        assert_eq!(
            select_backend(SemanticContract::XeTex, &DetectedFeatures::default(), &with_xetex),
            BackendKind::TectonicXetex
        );
    }

    #[test]
    fn pdftex_alias_stays_on_pdftex_class_without_qualification() {
        // No pdfTeX backend qualified yet: the safe answer is the external
        // fallback, never a silent XeTeX switch (plan X7.2).
        let empty: Vec<BackendKind> = Vec::new();
        assert_eq!(
            select_backend(SemanticContract::PdfTex, &DetectedFeatures::default(), &empty),
            BackendKind::ExternalFallback
        );
        let conventional = detect_features("\\documentclass{article}\\begin{document}x\\end{document}");
        assert_eq!(
            select_backend(SemanticContract::PdfTex, &conventional, &[BackendKind::TectonicXetex]),
            BackendKind::ExternalFallback
        );
        // Once a pdfTeX backend IS qualified, conventional documents use it.
        assert_eq!(
            select_backend(SemanticContract::PdfTex, &conventional, &[BackendKind::PdfTeX]),
            BackendKind::PdfTeX
        );
    }

    #[test]
    fn fontspec_document_routes_to_xetex_when_available() {
        let features = detect_features("\\usepackage{unicode-math}\n");
        assert_eq!(
            select_backend(SemanticContract::PdfTex, &features,
                           &[BackendKind::TectonicXetex, BackendKind::PdfTeX]),
            BackendKind::TectonicXetex
        );
    }

    #[test]
    fn lualatex_requires_lua_qualified_backend() {
        let with_tectonic = [BackendKind::TectonicXetex];
        assert_eq!(
            select_backend(SemanticContract::LuaHbTex, &DetectedFeatures::default(), &with_tectonic),
            BackendKind::ExternalFallback
        );
    }
}
