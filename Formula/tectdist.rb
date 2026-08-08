class Tectdist < Formula
  desc "Standard-TeX-compatible TeX distribution backed by Tectonic"
  homepage "https://github.com/tmonk/tectdist"
  url "https://github.com/tmonk/tectdist/releases/download/v0.1.0/tectdist-0.1.0.tar.gz"
  # sha256 of the release's source-tarball asset.  The asset is built
  # deterministically from the tag (`git archive | gzip -n`), uploaded once,
  # and immutable — unlike GitHub's codeload tarballs, which are regenerated
  # over time and NOT byte-stable.  Verify with `brew fetch` rather than curl:
  #   brew fetch --force tmonk/brew/tectdist
  # (NOTE: this value changes when the tag is force-retagged — see
  # RELEASING.md.)
  sha256 "0570fa6583bdf242e36ef385f52b1c1ac36ecb564e3ec1b358c05c35198796d0"
  license "AGPL-3.0-only"

  # Version pairing (the source of truth for this release):
  #   tectonic 0.17 -> bundled biblatex 3.17 -> .bcf format 3.8 -> biber 2.17
  # Each tectdist release REQUIRES a specific tectonic version.  Brew installs
  # the latest core tectonic, so the install block asserts the pairing and
  # fails fast with instructions if brew's tectonic has moved (a mismatched
  # pair breaks biblatex).  Bump TECTONIC_VERSION and the biber resources
  # together as one release unit — see RELEASING.md, "Bumping the pairing".
  TECTONIC_VERSION = "0.17".freeze

  depends_on "ghostscript" # epstopdf / eps2eps / ps2pdf / pdfcrop
  depends_on "poppler"     # pdfinfo / pdftotext / pdfunite / ... (proxied)
  depends_on "python@3.14" # the zipapp interpreter (current core default)
  depends_on "qpdf"        # proxied
  depends_on "tectonic"    # the engine — required

  # Official prebuilt biber 2.17 binaries (the same files MacTeX/TeX Live
  # ship), self-hosted on our GitHub release and sha256-pinned — users never
  # download from SourceForge (see RELEASING.md for the provenance check).
  # The darwin tarball holds a fat Mach-O (arm64 + x86_64) whose PAR
  # self-thinning bootstrap fails inside brew's sandbox, so the install thins
  # it with lipo to the host architecture.  There is no official linux/arm64
  # biber 2.17 binary; on that platform no resource is declared and the
  # install writes an explanatory stub script instead.
  if !OS.linux? || Hardware::CPU.intel?
    resource "biber" do
      on_macos do
        url "https://github.com/tmonk/tectdist/releases/download/v0.1.0/biber-2.17-darwin-universal.tar.gz"
        sha256 "182e1efa074d8a2a23a8893f2a22440d4e463cce55e4ed02076ac4c0ee0614b2"
      end
      on_linux do
        url "https://github.com/tmonk/tectdist/releases/download/v0.1.0/biber-2.17-linux-x86_64.tar.gz"
        sha256 "129d2e0332a57e985ffa253e5e9fbd28ef99af5a068d1b141145211969aa8999"
      end
    end
  end

  # tectdist is a single-file Python zipapp (dist/tectdist) plus a symlink
  # farm: every TeX tool name points at it and the dispatcher switches on
  # the invoked name.  Names provided by the dependencies above (poppler /
  # qpdf / ghostscript tools) are intentionally NOT in the farm, so the
  # passthrough proxies always find the real binaries.  biber is also not in
  # the farm: the formula installs the real bundled binary as bin/biber.
  def install
    # Pairing assertion: this release requires tectonic TECTONIC_VERSION.
    tectonic_keg = Formula["tectonic"].installed_kegs.map(&:version).max
    installed_tectonic = tectonic_keg&.to_s
    tectonic_pair = installed_tectonic.to_s.split(".").first(2).join(".")
    if tectonic_pair != TECTONIC_VERSION
      odie <<~EOS
        tectdist #{version} requires tectonic #{TECTONIC_VERSION}.x: tectonic
        #{TECTONIC_VERSION} bundles biblatex 3.17, which is only understood by
        the bundled biber 2.17.  Brew provides tectonic
        #{installed_tectonic || "(not installed)"} — installing a mismatched
        pair would silently break biblatex, so this release refuses.

        Fix: keep brew's tectonic at #{TECTONIC_VERSION}.x, or wait for the
        next tectdist release that pairs with
        #{installed_tectonic || "your tectonic version"} and then run:
          brew upgrade tmonk/brew/tectdist   # or: brew upgrade tectdist
        While tectonic is at #{TECTONIC_VERSION}.x you can also pin it so it
        cannot move underneath the pairing:
          brew pin tectonic
      EOS
    end

    python = formula_opt_bin("python@3.14")/"python3.14"
    system python, "build.py", "--python", python,
           "-o", buildpath/"dist/tectdist"
    libexec.install "dist/tectdist"

    # Bundled biber 2.17 as a real binary at bin/biber.  The darwin tarball
    # holds a fat Mach-O whose PAR self-thinning bootstrap fails inside brew's
    # sandbox, so extract the host-architecture slice with ruby-macho.
    bin.mkpath # needed before the biber install; make_symlink also uses it
    if OS.mac?
      resource("biber").stage do
        MachO::FatFile.new("biber").extract(Hardware::CPU.arch)
                      .write((bin/"biber").to_s)
        (bin/"biber").chmod 0755
      end
    elsif Hardware::CPU.intel?
      resource("biber").stage do
        (bin/"biber").install "biber"
      end
    else
      (bin/"biber").write <<~EOS
        #!/bin/sh
        # tectdist on linux/arm64: there is no official biber 2.17 binary for
        # this platform, so this stub replaces it.  Tectonic normally runs
        # biber automatically for biblatex documents; without a real biber the
        # bibliography stays empty and citations print their raw keys.
        # Install a compatible biber (e.g. `sudo apt install biber`) and make
        # sure it is found before the tectdist farm.
        echo "tectdist: biber is not available on linux/arm64 (no official biber 2.17 binary); the bibliography will be empty and citations will print raw keys. Install a compatible biber (e.g. 'apt install biber') and ensure it is found before the tectdist farm." >&2
        exit 0
      EOS
      (bin/"biber").chmod 0755
    end

    farm = %w[
      tectdist
      pdflatex latex xelatex lualatex platex uplatex pdftex tex etex luatex
      luahbtex dvilualatex dviluatex xetex pdfetex
      bibtex bibtex8 bibtexu makeindex xindy upmendex
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
      tectdist #{version} pairs with tectonic #{TECTONIC_VERSION}.x and bundles
      biber 2.17, matched to the biblatex 3.17 that tectonic #{TECTONIC_VERSION}
      bundles.  Homebrew's core `biber` (2.21) is NOT compatible with that
      biblatex and must not replace the bundled one; the formula asserts the
      pairing on every install and fails fast if brew's tectonic moves.

      The tectdist farm intentionally shadows nothing: poppler, qpdf and
      ghostscript tools come from those formulae themselves.  If another TeX
      installation already provides some of the farm names, run:
        brew link --overwrite tectdist

      Upgrading: `brew upgrade` updates both tectonic and tectdist; the weekly
      pairing check (see RELEASING.md) keeps the matched release available
      before brew's tectonic moves.  Details in the project README, "Version
      pairing".
    EOS
  end

  test do
    assert_match "tectdist", shell_output("#{bin}/tectdist --version")
    assert_match "latexmk", shell_output("#{bin}/latexmk --version")
    assert_match "biber version: 2.17", shell_output("#{bin}/biber --version")
    # 60 farm names + the tectdist launcher link + the real biber binary
    # (keep in sync with the `farm` list above; tests/check_formula.py guards
    # against drift)
    assert_operator Dir[bin/"*"].count, :>=, 62, "symlink farm incomplete"
  end
end
