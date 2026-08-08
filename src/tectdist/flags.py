"""Static tables describing the bin/ symlink farm and the web2c flag
vocabulary accepted by every engine name.

This is the single source of truth used by the dispatcher (``dispatcher.py``),
the launcher help text, ``make_links.py`` and the Homebrew formula.
"""

# ---------------------------------------------------------------------------
# The symlink farm: every name below is symlinked to the tectdist launcher.
# The dispatcher switches on the invoked basename (argv[0]).
# ---------------------------------------------------------------------------

ENGINES = (
    "pdflatex", "latex", "xelatex", "lualatex", "platex", "uplatex",
    "pdftex", "tex", "etex", "luatex", "luahbtex", "dvilualatex",
    "dviluatex", "xetex", "pdfetex",
)

# bibliography: processed inside the Tectonic compile (built-in BiBTeX)
STUB_BIB = ("bibtex", "bibtex8", "bibtexu")

# index/bibliography tools that proxy to the real system binary when one is
# installed (like the poppler/qpdf proxies); otherwise an honest exit-0 stub
PROXY_OR_STUB = ("biber", "makeindex", "xindy", "upmendex")

# dvi / ps handling: Tectonic never produces DVI (no DVI/PS pipeline exists)
STUB_DVI = ("dvips", "dvipdfm", "dvipdfmx", "dvipdf", "xdvipdfmx",
            "dvitype", "dvicopy", "dvipos", "dvidvi")

# maintenance: silent no-ops
STUB_MNT_SILENT = ("mktexlsr", "texhash")

# font/format management: handled by Tectonic's bundle
STUB_MNT_VERBOSE = ("mktexfmt", "mktexpk", "mktextfm", "fmtutil", "fmtutil-sys",
                    "updmap", "updmap-sys", "texconfig")

# font conversion: not needed with Tectonic
STUB_FNT = ("tftopl", "pltotf", "vftovp", "vptovf", "gftopk", "gftype",
            "afm2tfm", "otftotfm")

# MetaFont/MetaPost family: not supported by Tectonic
STUB_MF = ("mf", "mpost", "mft", "tangle", "weave")

# ConTeXt: not supported by Tectonic (LaTeX is)
STUB_CONTEXT = ("context", "texexec")

STUB_SPECIAL = ("tlmgr", "texdoc")

# real binaries of the same name, proxied through exec
PROXIES = ("pdftotext", "pdfinfo", "pdfimages", "pdftoppm", "pdftocairo",
           "pdfunite", "pdfseparate", "pdftops", "qpdf")

# implemented on top of Ghostscript
GS_TOOLS = ("epstopdf", "eps2eps", "ps2pdf", "pdfcrop")

# everything that make_links.py symlinks to the launcher
FARM_NAMES = (ENGINES + STUB_BIB + PROXY_OR_STUB + STUB_DVI + STUB_MNT_SILENT
              + STUB_MNT_VERBOSE + STUB_FNT + STUB_MF + STUB_CONTEXT
              + STUB_SPECIAL + PROXIES + GS_TOOLS + ("kpsewhich", "latexmk"))

# names the Homebrew formula must NOT symlink into the prefix bin: those are
# provided by its own dependencies (poppler/qpdf/ghostscript) or bundled by
# the formula itself (biber, as a real binary resource), so the farm must
# never shadow them.
FORMULA_EXCLUDED = frozenset(PROXIES + ("dvipdf", "eps2eps", "ps2pdf",
                                        "biber"))
FORMULA_FARM_NAMES = tuple(n for n in FARM_NAMES if n not in FORMULA_EXCLUDED)

# ---------------------------------------------------------------------------
# web2c flag vocabulary
# ---------------------------------------------------------------------------

# classic flags that have no Tectonic equivalent: accepted and dropped
IGNORED_FLAGS = frozenset((
    "file-line-error", "no-file-line-error", "halt-on-error", "recorder",
    "8bit", "etex", "enc", "draftmode", "draft", "pdf", "no-pdf", "dvi",
    "no-dvi", "parse-first-line", "no-parse-first-line", "progname",
    "cnf-line", "translate-file", "src-specials", "ipc", "ipc-start",
    "maketex", "no-maketex", "enable-installer", "disable-installer",
    "enable-enctex", "disable-enctex", "initialize", "ini", "undump",
    "preload", "no-mktexpk", "no-mktexfmt", "pdftex", "xetex", "luatex",
    "luatex0", "luajittex", "pagetranslate", "pagectr", "c-style-errors",
    "file-line-error-style", "allow-orphan-aux", "no-allow-orphan-aux",
    "no-shell-escape", "disable-write18", "disable-shell-escape",
    "shell-restricted", "output-comment", "tcx", "utf8", "no-pdf-output",
    "max-pages", "max-strings", "max-fonts", "enable-8bit-chars",
    "no-enable-8bit-chars", "fmt", "latex", "babel",
))

# memory / config knobs: accepted and dropped
MEMORY_KNOBS = frozenset((
    "main-memory", "extra-mem-top", "extra-mem-bot", "font-max",
    "font-mem-size", "pool-size", "buf-size", "nest-size", "param-size",
    "save-size", "stack-size", "strings", "pkin", "tfm", "hash-size",
    "max-in-open", "max-print-line", "error-line", "half-error-line",
))

# search-path env vars consulted by the engine dispatcher and kpsewhich
ENGINE_PATH_VARS = ("TEXINPUTS", "BIBINPUTS", "BSTINPUTS", "INDEXSTYLE")
KPSEWHICH_PATH_VARS = ("TEXINPUTS", "BIBINPUTS", "BSTINPUTS")

# fallback engine location (mirrors the old bash resolution: TECTONIC env,
# then PATH lookup, then this single hard fallback)
TECTONIC_FALLBACK = "/opt/homebrew/bin/tectonic"
