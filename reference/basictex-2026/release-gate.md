# Release gate (R milestone)

Overall: **FAIL**

| stage | status | detail |
|---|---|---|
| workspace-tests | pass | returncode=0, 90 tests passed |
| differential | pass | differential: OK |
| bib-differential | pass | differential corpus passed (10 cases) |
| bt100-report-gate | pass | 195 pass / 0 fail / 65 reference-blocked |
| doc-equivalence | pass | 14/14 documents equivalent -> /Users/tom/Library/CloudStorage/Dropbox/projects/tectdist/reference/basictex-2026/doc-equivalence.json |
| fail-equivalence | pass | {'equivalent-fail': 65, 'equivalent-pass': 0, 'mismatch': 0} -> /Users/tom/Library/CloudStorage/Dropbox/projects/tectdist/reference/basictex-2026/fail-equivalence.json |
| x10-e-edit | fail | body-edit 2.078x, unchanged 13.333x, structural-edit 1.839x — below 10x; requires engine-side page checkpoints (documented) |
| x10-c-warm-clean | pending | tokenised caches require engine-side work (X6); no implementation exists to measure yet |
