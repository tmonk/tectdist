# BT100 Compatibility Report

Image: `395f0b4d7ce47684…`
Gate: **PASS**

| metric | count |
|---|---:|
| Total packages | 372 |
| Tested | 194 |
| Untested | 178 |
| Pass | 141 |
| Fail | 0 |
| Reference-blocked | 53 |
| Reference failures recorded | 0 |

Output pipelines: 7/7 qualified
Standalone probes: 142 pass / 53 fail

## Reference-failure attribution

207 interaction reference-failures, all attributed:

- explained by a component failing standalone: 207
- pair-specific (unattributed): 0
- components failing standalone: 53

| standalone-failing package | cause |
|---|---|
| amscls | ! LaTeX Error: File `amsart.sty' not found. |
| arabxetex | ! Fatal Package fontspec Error: The fontspec package requires either XeTeX or |
| babel | ! Package babel Error: You are loading directly a language style. |
| babel-spanish | ! Undefined control sequence. |
| babelbib | ! Undefined control sequence. |
| beamer | ! LaTeX Error: File `beamer.sty' not found. |
| bidipresentation | ! LaTeX Error: File `bidipresentation.sty' not found. |
| businesscard-qrcode | ! LaTeX Error: File `businesscard-qrcode.sty' not found. |
| cqubeamer | ! Undefined control sequence. |
| ctable | ! LaTeX Error: File `transparent.sty' not found. |
| ctablestack | ! Undefined control sequence. |
| fixlatvian | ! LaTeX Error: File `svn-prov.sty' not found. |
| fontbook | ! Fatal Package fontspec Error: The fontspec package requires either XeTeX or |
| fontspec | ! Fatal Package fontspec Error: The fontspec package requires either XeTeX or |
| fontwrap | ! Fatal Package fontspec Error: The fontspec package requires either XeTeX or |
| gmp | ! LaTeX Error: File `environ.sty' not found. |
| hypcap | ! Package hypcap Error: You have to load 'hyperref' first. |
| ifplatform | ! LaTeX Error: File `catchfile.sty' not found. |
| interchar | ! LaTeX Error: Variant form 'cx' deprecated for base form '\prop_item:cn'. One |
| koma-script | ! LaTeX Error: File `koma-script-source-doc.sty' not found. |
| lineno | ! Package ednmath0 Error: Bad lineno.sty version. |
| ltx-talk | ! LaTeX Error: File `ltx-talk.sty' not found. |
| ltxmisc | ! LaTeX Error: File `abstbook.sty' not found. |
| lua-unicode-math | ! Critical Package lua-unicode-math Error: lua-unicode-math can only be used |
| luamml | ! Undefined control sequence. |
| luaotfload | ! Undefined control sequence. |
| luatexbase | ! Undefined control sequence. |
| lwarp | ! LaTeX Error: File `ifptex.sty' not found. |
| mathspec | ! Emergency stop. |
| mfpic4ode | ! Undefined control sequence. |
| mpgraphics | ! LaTeX Error: File `moreverb.sty' not found. |
| na-position | ! LaTeX Error: File `tkz-tab.sty' not found. |
| pdfcolfoot | ! LaTeX Error: File `pdfcol.sty' not found. |
| philokalia | ! Emergency stop. |
| ptext | ! LaTeX Error: File `biditools.sty' not found. |
| revtex | ! Undefined control sequence. |
| simple-resume-cv | ! LaTeX Error: File `simpleresumecv.sty' not found. |
| simple-thesis-dissertation | ! LaTeX Error: File `simplethesisdissertation.sty' not found. |
| tagpdf | ! Package tagpdf Error: PDF resource management is no active! |
| textpath | ! LaTeX Error: File `soul.sty' not found. |
| ucharcat | ! Package ucharcat Error: \Ucharcat may only be used with xetex and luatex. |
| ucharclasses | ! Emergency stop. |
| unicode-bidi | ! Undefined control sequence. |
| unicode-math | ! Package unicode-math Error: Cannot be run with pdftex! |
| xebaposter | ! LaTeX Error: File `xebaposter.sty' not found. |
| xecolor | ! Fatal Package fontspec Error: The fontspec package requires either XeTeX or |
| xeindex | ! Undefined control sequence. |
| xesearch | ! Undefined control sequence. |
| xetexko | ! Bad character code (4095). |
| xevlna | ! Undefined control sequence. |
| xltxtra | ! Emergency stop. |
| xunicode | ! LaTeX Error: *** this package currently works only with XeTeX *** |
| zbmath-review-template | ! LaTeX Error: File `stmaryrd.sty' not found. |


## Untested packages (no loadable styles discovered)

| package |
|---|
| 00texlive.config |
| 00texlive.installation |
| attachfile2.universal-darwin |
| automata |
| babel-basque |
| babel-czech |
| babel-danish |
| babel-dutch |
| babel-english |
| babel-finnish |
| babel-french |
| babel-german |
| babel-hungarian |
| babel-italian |
| babel-norsk |
| babel-polish |
| babel-portuges |
| babel-swedish |
| bbcard |
| bibtex.universal-darwin |
| blockdraw_mp |
| bpolynomial |
| cm |
| cmarrows |
| collection-basic |
| collection-latex |
| collection-latexrecommended |
| collection-metapost |
| collection-xetex |
| dehyph |
| drv |
| dviincl |
| dvipdfmx |
| dvipdfmx.universal-darwin |
| dvips.universal-darwin |
| ec |
| enctex |
| epsincl |
| epstopdf |
| epstopdf.universal-darwin |
| etex |
| euenc |
| expressg |
| exteps |
| extractbb |
| extractbb.universal-darwin |
| featpost |
| fiziko |
| font-change-xetex |
| garrigues |
| geometry |
| glyphlist |
| graphics-cfg |
| graphics-def |
| hatching |
| hershey-mp |
| huffman |
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
| knuth-lib |
| knuth-local |
| kpathsea |
| kpathsea.universal-darwin |
| l3backend |
| l3backend-dev |
| latex-bin |
| latex-bin-dev |
| latex-bin-dev.universal-darwin |
| latex-bin.universal-darwin |
| latex-fonts |
| latexconfig |
| latexmp |
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
| mcf2graph |
| metafont |
| metafont.universal-darwin |
| metago |
| metaobj |
| metaplot |
| metapost |
| metapost-colorbrewer |
| metapost.universal-darwin |
| metauml |
| mfware |
| mfware.universal-darwin |
| minim-hatching |
| modes |
| mp-geom2d |
| mp-neuralnetwork |
| mp3d |
| mparrows |
| mpattern |
| mpchess |
| mpcolornames |
| mpkiviat |
| mptopdf |
| mptopdf.universal-darwin |
| mptrees |
| pdftex |
| pdftex.universal-darwin |
| piechartmp |
| plain |
| repere |
| roex |
| roundrect |
| scheme-basic |
| scheme-infraonly |
| scheme-minimal |
| scheme-small |
| shapes |
| slideshow |
| splines |
| suanpan |
| symbol |
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
| threeddice |
| thumbpdf.universal-darwin |
| times |
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
| zapfding |
