# tectdist fork-server engine builds (plan X1)

Instrumented TeX engines carrying the `tectdist_forkserver_serve` hook:
a resident parent preloads a format, accepts one-line jobs over a Unix
socket, and forks copy-on-write children per compile. Children install
the job into the terminal buffer at the convergence point and resume
mainbody.

## Contents

- `patches/texmfmp-forkserver.patch` — the serve() implementation
  appended to `texk/web2c/lib/texmfmp.c` (shared by all engines).
  Includes the normalized install window (`first >= 1`, bounds-checked)
  required because XeTeX's lab1 convergence point still holds the
  startup value of `first`.
- `patches/pdftexini-forkserver.patch` — call-site insertion after the
  second `fixdateandtime()` in generated `pdftexini.c` (the proven
  working anchor for pdfTeX).
- `patches/xetexini-forkserver.patch` — call site for XeTeX. NOTE: the
  committed tree places it after `fixdateandtime()`; XeTeX's non-init
  mainbody executes `goto lab1` early, so production placement is under
  review — see "Known gaps".
- `bin/forkproto/` — compiled, ad-hoc signed binaries deployed to
  `<BasicTeX image>/bin/forkproto/`.

## Build recipe (XeTeX, macOS arm64)

Executed against `reference/texlive-source/texlive-20260301-source`
with build dir `build-fs`:

1. teckit builds from in-tree sources: `make -C libs/teckit`
2. Re-run top-level configure with the EXACT original argument list
   (extract from `build-fs/config.log`) but `--enable-xetex` replacing
   `--disable-xetex`, plus `--with-system-fontconfig=yes`, with
   PKG_CONFIG_PATH including brew fontconfig/freetype.
3. TL does not bundle fontconfig — inject system flags manually into
   `texk/web2c/Makefile`:
   FONTCONFIG_INCLUDES = -I<brew fc>/include -I<brew ft>/include/freetype2
   FONTCONFIG_LIBS     = -L<brew fc>/lib -lfontconfig
4. XeTeXLayoutInterface.cpp needs ICU: append
   -I<build>/libs/icu/include to includes; add
   -L<build>/libs/icu/icu-build/lib -licuuc -licui18n -licudata -licuio
   to the link line.
5. ICU headers require C++17: make xetex CXXFLAGS="-g -O2 -std=c++17"
6. Apply ini hooks (script below), rebuild, re-sign ad-hoc
   (`codesign -s - -f <binary>` — stale Dropbox-served exec content
   otherwise kills fresh binaries on launch), deploy.

## Ini hook insertion

`scripts/forkserver_apply_patch.py --build <build> --engines pdftex xetex`
inserts the call after the second `fixdateandtime()` in each generated
`<engine>ini.c`. For pdftex this is the proven anchor. For xetex the
equivalent post-fixdateandtime position lets serve() run but CHILDREN
die silently on resume (exit 1, no output) — an XeTeX-specific state
issue between resume-at-lab1 and input consumption requiring lldb-level
debugging of the fork child. Until resolved, XeTeX workers fail fast
and escalate to exact one-shot execution (BT100 preserved by design).

## Verification status (2026-08)

| engine | composed path | base-worker path |
|---|---|---|
| pdfTeX | ✅ verified byte-identical across batteries | ✅ working |
| XeTeX | ⚠️ engages; children die silently → escalation | ⚠️ same |
