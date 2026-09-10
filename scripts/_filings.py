"""Turn a missing 10-K into one line and exit 1, at the CLI boundary.

Principle 5: a library raises, the CLI decides the exit code. Nothing under
`src/aleph/` catches FileNotFoundError - pypdf's exception is allowed all the
way up, because a library that swallows it cannot be reused by a caller that
wants to handle it differently. The documented commands catch it here.

MEASURED on a checkout with `data/*.pdf` moved away, before this existed:

    scripts/run_valuation.py UBER_FY2024 76.95    39 lines, pypdf traceback
    scripts/diagnose_valuation.py UBER_FY2024 ..  39 lines, pypdf traceback
    scripts/test_sections.py                      26 lines, pypdf traceback
    scripts/test_regression.py                    32 lines, pypdf traceback
    scripts/test_multicompany.py                  97 lines, one FAIL per
                                                  target (no traceback - its
                                                  own broad handler caught
                                                  each one and kept going)

The first of those is the FIRST command in README's list, so it was the first
thing a reader who followed the setup instructions saw: a stack trace for the
one condition this repository documents at length and expects
(docs/adr/0006, data/README.md).

This does not fix the condition, which is correct and deliberate. It fixes
the report. Exit code stays 1 in every case, and with the filings present
nothing here runs at all.
"""
import sys


def exit_on_missing_filing(exc: FileNotFoundError) -> None:
    """Print one line naming the missing path, then exit 1. Never returns."""
    path = exc.filename or "a filing listed in data/manifest.json"
    print(f"MISSING FILING: {path} - this repository does not distribute the "
          f"10-K PDFs; see data/README.md for the EDGAR source of each and "
          f"the file name it is expected under.")
    sys.exit(1)
