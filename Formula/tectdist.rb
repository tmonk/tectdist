class Tectdist < Formula
  desc "Standard-TeX-compatible TeX distribution backed by Tectonic"
  homepage "https://github.com/tmonk/tectdist"
  url "https://github.com/tmonk/tectdist/archive/refs/tags/v0.1.0.tar.gz"
  # sha256 of the archive as fetched by Homebrew (ghcr.io mirror of the
  # GitHub-generated tarball).  GitHub's codeload gzip is regenerated and
  # NOT byte-stable, so verify with `brew fetch` rather than curl:
  #   brew fetch --force tmonk/brew/tectdist
  #   shasum -a 256 $(ls -t ~/Library/Caches/Homebrew/downloads/*tectdist-0.1.0.tar.gz | head -1)
  sha256 "31c7e188c203c8c3e04980e6f7a9d077fff46e94c7fec1bf0efa696bf2445163"
  license "AGPL-3.0-only"

  depends_on "ghostscript" # epstopdf / eps2eps / ps2pdf / pdfcrop
  depends_on "poppler"     # pdfinfo / pdftotext / pdfunite / ... (proxied)
  depends_on "python@3.12" # the zipapp interpreter
  depends_on "qpdf"         # proxied
  depends_on "tectonic"     # the engine — required

  # tectdist is a single-file Python zipapp (dist/tectdist) plus a symlink
  # farm: every TeX tool name points at it and the dispatcher switches on
  # the invoked name.  Names provided by the dependencies above (poppler /
  # qpdf / ghostscript tools) are intentionally NOT in the farm, so the
  # passthrough proxies always find the real binaries.
  def install
    python = formula_opt_bin("python@3.12")/"python3.12"
    system python, "build.py", "--python", python,
           "-o", buildpath/"dist/tectdist"
    libexec.install "dist/tectdist"

    bin.mkpath # make_symlink does not create the directory
    farm = %w[
      tectdist
      pdflatex latex xelatex lualatex platex uplatex pdftex tex etex luatex
      luahbtex dvilualatex dviluatex xetex pdfetex
      bibtex bibtex8 bibtexu biber makeindex xindy upmendex
      dvips dvipdfm dvipdfmx xdvipdfmx dvitype dvicopy dvipos dvidvi
      mktexlsr texhash mktexfmt mktexpk mktextfm fmtutil fmtutil-sys
      updmap updmap-sys texconfig tlmgr texdoc
      tftopl pltotf vftovp vptovf gftopk gftype afm2tfm otftotfm
      mf mpost mft tangle weave context texexec
      epstopdf pdfcrop
      kpsewhich latexmk
    ]
    farm.each do |name|
      (bin/name).make_symlink libexec/"tectdist"
    end
  end

  def caveats
    <<~EOS
      The tectdist farm intentionally shadows nothing: poppler, qpdf and
      ghostscript tools come from those formulae themselves.  If another
      TeX installation already provides some of the farm names, run:
        brew link --overwrite tectdist
    EOS
  end

  test do
    assert_match "tectdist", shell_output("#{bin}/tectdist --version")
    assert_match "latexmk", shell_output("#{bin}/latexmk --version")
    # 61 farm names + the tectdist launcher link (keep in sync with the
    # `farm` list above; tests/check_formula.py guards against drift)
    assert_operator Dir[bin/"*"].count, :>=, 62, "symlink farm incomplete"
  end
end
