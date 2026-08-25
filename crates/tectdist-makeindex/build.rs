use std::env;
use std::path::PathBuf;

fn main() {
    let root = PathBuf::from(env::var("CARGO_MANIFEST_DIR").unwrap());
    let sources = [
        "c/mkind.c",
        "c/genind.c",
        "c/qsort.c",
        "c/scanid.c",
        "c/scanst.c",
        "c/sortid.c",
        "c/shim.c",
    ];
    let mut build = cc::Build::new();
    build
        .files(sources.iter().map(|source| root.join(source)))
        // Rename the tool's main so it can be called in-process, and redirect
        // its EXIT (exit) macro target to the shim's longjmp-based exit so a
        // fatal MakeIndex condition never terminates the host process.
        .define("main", "makeindex_main")
        .define("exit", "tectdist_makeindex_exit")
        .flag_if_supported("-O2")
        // The vendored C is pinned upstream (docs/ENGINE_PIN.md); silence
        // its benign -Wformat-extra-args noise from the FATAL macro rather
        // than modifying pinned sources.
        .warnings(false);
    build.compile("tectdist_makeindex");
    println!("cargo:include={}", root.join("c").display());
}
