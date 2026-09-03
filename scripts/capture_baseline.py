"""Capture run_valuation.py's full output for the four valued filings.

Determinism has to be PROVEN before a refactor can claim it preserved
output: a byte-for-byte diff against a baseline is only evidence if the
baseline itself is reproducible. Run this twice into two directories and
diff them - any line that differs between two runs of unchanged code is a
line a post-refactor diff cannot attribute to the refactor.

subprocess captures stdout and stderr directly, never shell redirection:
redirection makes the shell, not Python, decide the encoding, and this
pipeline prints filing text containing typographic characters that a
cp1255 console encodes differently than a file.
"""
import subprocess
import sys
from pathlib import Path

RUNS = [
    ("UBER_FY2024", "76.95"),
    ("UBER_FY2025", "76.95"),
    ("LYFT_FY2025", "17.35"),
    ("DASH_FY2025", "231.89"),
]

outdir = Path(sys.argv[1])
outdir.mkdir(parents=True, exist_ok=True)

for doc_id, price in RUNS:
    completed = subprocess.run(
        [sys.executable, "scripts/run_valuation.py", doc_id, price],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    # stderr is captured with stdout: a traceback belongs in the baseline as
    # much as a RESULT block does, and dropping it would hide a run that
    # printed the right numbers on its way to failing.
    (outdir / f"{doc_id}.txt").write_text(
        completed.stdout + completed.stderr, encoding="utf-8"
    )
    print(f"  {doc_id:<12} exit={completed.returncode} "
          f"{len(completed.stdout):,} bytes stdout, "
          f"{len(completed.stderr):,} bytes stderr")

print(f"\nWrote {len(RUNS)} files to {outdir}")
