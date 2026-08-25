# BT100 Compatibility Report

Image: `395f0b4d7ce47684…`
Gate: **PASS**

| metric | count |
|---|---:|
| Total packages | 372 |
| Tested | 260 |
| Untested | 112 |
| Pass | 195 |
| Fail | 0 |
| Reference-blocked | 65 |
| Reference failures recorded | 0 |

Output pipelines: 7/7 qualified
Standalone probes: 195 pass / 65 fail

## Reference-failure attribution

207 interaction reference-failures, all attributed:

- explained by a component failing standalone: 207
- pair-specific (unattributed): 0
- components failing standalone: 65

| standalone-failing package | cause |
|---|---|
| arabxetex | ! Fatal Package fontspec Error: The fontspec package requires either XeTeX or |
| babel | ! Package babel Error: You are loading directly a language style. |
| babelbib | ! Undefined control sequence. |
| businesscard-qrcode | ! LaTeX Error: File `marvosym.sty' not found. |
| cm | ! LaTeX Error: The font size command \normalsize is not defined: |
| cqubeamer | ! Undefined control sequence. |
| ctable | ! LaTeX Error: File `transparent.sty' not found. |
| ctablestack | ! Undefined control sequence. |
| drv | ! drv: "verbatimtex%&latex" is missing. |
| ec | ! LaTeX Error: The font size command \normalsize is not defined: |
| etex | ! LaTeX Error: The font size command \normalsize is not defined: |
| expressg | ! ! Unable to read mpx file. |
| fixlatvian | ! LaTeX Error: File `svn-prov.sty' not found. |
| fontbook | ! Fatal Package fontspec Error: The fontspec package requires either XeTeX or |
| fontspec | ! Fatal Package fontspec Error: The fontspec package requires either XeTeX or |
| fontwrap | ! Fatal Package fontspec Error: The fontspec package requires either XeTeX or |
| gmp | ! LaTeX Error: File `environ.sty' not found. |
| huffman | ! ! Unable to read mpx file. |
| hypcap | ! Package hypcap Error: You have to load 'hyperref' first. |
| ifplatform | ! LaTeX Error: File `catchfile.sty' not found. |
| interchar | ! LaTeX Error: Variant form 'cx' deprecated for base form '\prop_item:cn'. One |
| knuth-lib | ! LaTeX Error: The font size command \normalsize is not defined: |
| knuth-local | ! LaTeX Error: The font size command \normalsize is not defined: |
| koma-script | ! LaTeX Error: File `hypdoc.sty' not found. |
| latex-fonts | ! LaTeX Error: The font size command \normalsize is not defined: |
| lineno | ! Package ednmath0 Error: Bad lineno.sty version. |
| ltx-talk | ! LaTeX Error: This file needs \DocumentMetadata. |
| ltxmisc | ! LaTeX Error: File `minitoc.sty' not found. |
| lua-unicode-math | ! Critical Package lua-unicode-math Error: lua-unicode-math can only be used |
| luamml | ! Undefined control sequence. |
| luaotfload | ! Undefined control sequence. |
| luatexbase | ! Undefined control sequence. |
| lwarp | ! LaTeX Error: File `ifptex.sty' not found. |
| mathspec | ! Emergency stop. |
| metaobj | ! ! Unable to read mpx file. |
| mfpic4ode | ! Undefined control sequence. |
| minim-hatching | ! Isolated expression. |
| mp-neuralnetwork | ! Isolated expression. |
| mpgraphics | ! LaTeX Error: File `moreverb.sty' not found. |
| na-position | ! LaTeX Error: File `tkz-tab.sty' not found. |
| pdfcolfoot | ! LaTeX Error: File `pdfcol.sty' not found. |
| pdftex | ! Font \probe=texmf-dist/fonts/tfm/public/pdftex/dummy-space not loadable: Metr |
| philokalia | ! Emergency stop. |
| ptext | ! LaTeX Error: File `biditools.sty' not found. |
| revtex | ! Undefined control sequence. |
| simple-resume-cv | ! LaTeX Error: File `hyphenat.sty' not found. |
| simple-thesis-dissertation | ! LaTeX Error: File `environ.sty' not found. |
| suanpan | ! ! Unable to read mpx file. |
| symbol | ! Font \probe=texmf-dist/fonts/tfm/adobe/symbol/psyr not loadable: Metric (TFM) |
| tagpdf | ! Package tagpdf Error: PDF resource management is no active! |
| textpath | ! LaTeX Error: File `soul.sty' not found. |
| times | ! Font \probe=texmf-dist/fonts/tfm/adobe/times/psyro not loadable: Metric (TFM) |
| ucharcat | ! Package ucharcat Error: \Ucharcat may only be used with xetex and luatex. |
| ucharclasses | ! Emergency stop. |
| unicode-bidi | ! Undefined control sequence. |
| unicode-math | ! Package unicode-math Error: Cannot be run with pdftex! |
| xecolor | ! Fatal Package fontspec Error: The fontspec package requires either XeTeX or |
| xeindex | ! Undefined control sequence. |
| xesearch | ! Undefined control sequence. |
| xetexko | ! Bad character code (4095). |
| xevlna | ! Undefined control sequence. |
| xltxtra | ! Emergency stop. |
| xunicode | ! LaTeX Error: *** this package currently works only with XeTeX *** |
| zapfding | ! Font \probe=texmf-dist/fonts/tfm/adobe/zapfding/pzdr not loadable: Metric (TF |
| zbmath-review-template | ! LaTeX Error: File `stmaryrd.sty' not found. |


## Untested packages (no loadable styles discovered)

| package |
|---|
| 00texlive.config |
| 00texlive.installation |
| attachfile2.universal-darwin |
| bibtex.universal-darwin |
| collection-basic |
| collection-latex |
| collection-latexrecommended |
| collection-metapost |
| collection-xetex |
| dehyph |
| dvipdfmx |
| dvipdfmx.universal-darwin |
| dvips.universal-darwin |
| enctex |
| epstopdf |
| epstopdf.universal-darwin |
| euenc |
| extractbb |
| extractbb.universal-darwin |
| font-change-xetex |
| glyphlist |
| graphics-cfg |
| graphics-def |
| hyph-utf8 |
| hyphen-base |
| hyphen-basque |
| hyphen-czech |
| hyphen-danish |
| hyphen-dutch |
| hyphen-english |
| hyphen-finnish |
| hyphen-french |
| hyphen-german |
| hyphen-hungarian |
| hyphen-italian |
| hyphen-norwegian |
| hyphen-polish |
| hyphen-portuguese |
| hyphen-spanish |
| hyphen-swedish |
| hyphenex |
| kpathsea |
| kpathsea.universal-darwin |
| l3backend |
| l3backend-dev |
| latex-bin |
| latex-bin-dev |
| latex-bin-dev.universal-darwin |
| latex-bin.universal-darwin |
| latexconfig |
| lm-math |
| lua-alt-getopt |
| lua-uni-algos |
| luahbtex |
| luahbtex.universal-darwin |
| lualibs |
| luaotfload.universal-darwin |
| luatex |
| luatex.universal-darwin |
| lwarp.universal-darwin |
| make4ht |
| make4ht.universal-darwin |
| makeindex |
| makeindex.universal-darwin |
| metafont |
| metafont.universal-darwin |
| metapost |
| metapost.universal-darwin |
| mfware |
| mfware.universal-darwin |
| modes |
| mptopdf |
| mptopdf.universal-darwin |
| pdftex.universal-darwin |
| plain |
| roex |
| scheme-basic |
| scheme-infraonly |
| scheme-minimal |
| scheme-small |
| synctex |
| synctex.universal-darwin |
| tex |
| tex-ini-files |
| tex.universal-darwin |
| tex4ebook.universal-darwin |
| tex4ht.universal-darwin |
| texlive-common |
| texlive-en |
| texlive-msg-translations |
| texlive-scripts |
| texlive-scripts-extra |
| texlive-scripts-extra.universal-darwin |
| texlive-scripts.universal-darwin |
| texlive.infra |
| texlive.infra.universal-darwin |
| thumbpdf.universal-darwin |
| tlshell |
| tlshell.universal-darwin |
| unicode-data |
| unimath-plain-xetex |
| xdvi |
| xdvi.universal-darwin |
| xelatex-dev |
| xelatex-dev.universal-darwin |
| xetex |
| xetex-itrans |
| xetex-pstricks |
| xetex-tibetan |
| xetex.universal-darwin |
| xetexconfig |
| xetexfontinfo |
