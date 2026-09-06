# 0008. The ch05 evaluation gate is removed from CI, not made to skip

## Context

`.github/workflows/eval-gate.yml` ran `experiments/ch05_evaluation/02_ab_test.py`
on every pull request to `main`. That script opens `data/uber_10k.pdf` at
module level, unconditionally, on line 34.

`docs/adr/0006` decided that the filing PDFs are not distributed with this
repository, and on 2026-09-06 the git history was rewritten so that decision
became true of every commit, not only of `HEAD`. The file therefore cannot
exist on a CI runner.

Measured, on a fresh `git clone` of the public repository rather than on a
local working copy: `PdfReader("data/uber_10k.pdf")` raises
`FileNotFoundError`. The script dies before any evaluation runs and before
its own dependencies matter.

The workflow's last successful run was `eb8940f3`, dated 2026-08-13. The
PDF was untracked in `350ac47` on 2026-09-02, after that run, so the green
result predates the condition that breaks it - and that commit hash no
longer exists in this history, since the rewrite changed every SHA. The one
piece of evidence that this gate ever worked points at a history that is
gone.

Left in place, it would fail on the first pull request to `main`, for a
reason unrelated to the change under review.

## Decision

`eval-gate.yml` is deleted. The ch05 retrieval evaluation is a local check,
run by hand against a working copy that has the filings, in the same
category as `test_sections.py`, `test_multicompany.py`,
`test_regression.py` and `run_valuation.py`'s 77.08 anchor - all of which
need the filings and none of which run in CI.

`experiments/ch05_evaluation/02_ab_test.py` is NOT modified. `experiments/`
is archived course work, read-only by the working agreement in `CLAUDE.md`;
editing an archived chapter to accommodate a CI decision would falsify what
that chapter was.

The coverage gap is stated in `README.md` and `CLAUDE.md` beside the gaps
already recorded there, so the absence is documented rather than silent.

## Alternative rejected

Make the workflow skip when the PDF is absent - a conditional step, or an
early exit in the script - so the gate stays configured and reports success
on runners that cannot evaluate anything.

Rejected because it manufactures exactly the failure this project names as
its worst: a result that sounds right and is not, carrying no red flag. A
green check on "Evaluation Gate" would mean "the golden dataset passed" to
every reader of the PR page, while meaning "nothing was evaluated" in fact.
A gate that cannot run should be visibly absent, not invisibly vacuous.
`pipeline-tests.yml` already takes this position for the three tests it
cannot run, and `test_manifest.py` takes it for shallow clones, where it
raises rather than passing without having seen the history it checks.

Also rejected: committing `data/uber_10k.pdf` so the gate can run. That
reverses ADR 0006 to keep a workflow for archived course work, and would
republish a filing the repository states it does not distribute.

## Consequence

`requirements-eval.txt` is kept. It is the dependency list for running the
ch05 evaluation locally, which is still the supported way to run it, and
nothing else references it.

Reinstating this gate needs a way for CI to obtain the filing - a fetch
from EDGAR at run time, or a stored artifact - not a change to the script.
Whoever does that should note that ISSUES.md #3, #4 and #5, the findings
this gate would protect, are all in the retrieval layer, which `README.md`
states is course work and not part of the capstone pipeline.

Decided by Asi, 2026-09-06.
