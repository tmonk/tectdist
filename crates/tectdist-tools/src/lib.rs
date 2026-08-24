//! Native utility dispatch support. Kept independent from CLI parsing.
include!("generated_flags.rs");

pub fn is_engine(name: &str) -> bool {
    ENGINE_ALIASES.contains(&name)
}

pub fn is_silent_stub(name: &str) -> bool {
    SILENT_STUBS.contains(&name)
}
pub fn is_informative_stub(name: &str) -> bool {
    STUB_BIB.contains(&name)
        || STUB_DVI.contains(&name)
        || INFORMATIVE_MAINTENANCE.contains(&name)
        || FONT_STUBS.contains(&name)
        || METAFONT_STUBS.contains(&name)
        || CONTEXT_STUBS.contains(&name)
        || SPECIAL_STUBS.contains(&name)
}
pub fn is_proxy(name: &str) -> bool {
    PROXIES.contains(&name) || PROXY_OR_STUB.contains(&name)
}

pub fn is_proxy_or_stub(name: &str) -> bool {
    PROXY_OR_STUB.contains(&name)
}
