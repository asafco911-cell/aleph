"""Skip the tests that need the six 10-K PDFs, loudly, when they are absent.

Measured, on a checkout with `data/*.pdf` moved away: `python -m pytest tests/`
was 181 failed, 628 passed - every failure a FileNotFoundError on a filing the
repository deliberately does not distribute (docs/adr/0006). That is what a
fresh clone looks like, and CI runs `python -m pytest tests/` on every push, so
the workflow could not pass for anyone but the author.

Two ways to fix that, and only one of them is honest:

  - Make the tests pass without the filings. They cannot: 181 of them assert
    on real numbers from real documents. Faking the documents would leave 181
    green checks that prove nothing about the pipeline.
  - Skip them, and say so at the top of the summary, every time.

This is the second. It is the same stance as docs/adr/0008, which deleted a
workflow rather than teach it to skip silently: a green check on a run that
verified nothing is the failure mode this whole project is built against. The
difference is that here the skip is REPORTED - pytest_terminal_summary prints
the count and the missing file, so a reader of a CI log cannot mistake the pass
line for a whole-suite pass.

Which tests carry the marker was measured, not guessed: the 181 failures above
were mapped back to 158 test functions (no parametrised case was mixed - every
parametrisation failed wholly or not at all), and exactly those functions were
marked. `python -m pytest tests/` with the filings present must report 0
skipped; if it does not, a test that never needed a filing has been marked.
"""
import functools
import json
from pathlib import Path

import pytest

from aleph.infra.paths import DATA_DIR

MANIFEST = DATA_DIR / "manifest.json"

# Set by pytest_collection_modifyitems, read by pytest_terminal_summary.
_skipped_count = 0
_skip_reason = ""


@functools.cache
def missing_filings() -> tuple[str, ...]:
    """Filings the manifest lists that are not on disk, as absolute paths.

    The manifest is the list, not a glob over data/: a glob would report
    "nothing missing" on an empty directory, which is the vacuous pass this
    file exists to prevent.

    Cached: the answer cannot change during a run, and asking the filesystem
    once per marked test would be 181 answers to one question.
    """
    if not MANIFEST.is_file():
        return (str(MANIFEST),)
    records = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return tuple(str(DATA_DIR / r["file_name"])
                 for r in records
                 if not (DATA_DIR / r["file_name"]).is_file())


@pytest.fixture(scope="session")
def filings_dir() -> Path:
    """DATA_DIR, once every filing the manifest lists is present.

    The marker is the mechanism; this is here for a test that wants the
    directory itself rather than just the guarantee, and it skips on the same
    condition so the two can never disagree about what "present" means.
    """
    missing = missing_filings()
    if missing:
        pytest.skip(f"filing not present: {missing[0]}")
    return DATA_DIR


def pytest_collection_modifyitems(config, items) -> None:
    """Skip everything marked needs_filings when a filing is absent.

    Done at collection rather than through an autouse fixture so the reason
    reaches the report for tests that request no fixture at all.
    """
    global _skipped_count, _skip_reason
    missing = list(missing_filings())
    if not missing:
        return

    _skip_reason = (
        f"needs the 10-K filings; {len(missing)} missing, first: {missing[0]}"
    )
    mark = pytest.mark.skip(reason=_skip_reason)
    for item in items:
        if "needs_filings" in item.keywords:
            item.add_marker(mark)
            _skipped_count += 1


def pytest_terminal_summary(terminalreporter, exitstatus, config) -> None:
    """Say what was NOT verified, where a reader cannot miss it.

    A count of skips buried in pytest's own summary line reads as housekeeping.
    This says the thing itself: those tests are not evidence for anything in
    this run.
    """
    if _skipped_count <= 0:
        return
    terminalreporter.write_sep("=", "NOT VERIFIED BY THIS RUN", red=True)
    terminalreporter.write_line(
        f"SKIPPED {_skipped_count} tests that need the filings; "
        "they are NOT verified by this run."
    )
    terminalreporter.write_line(f"  reason: {_skip_reason}")
    terminalreporter.write_line(
        "  the six 10-K PDFs are not distributed with this repository - "
        "see data/README.md for the EDGAR source of each."
    )
