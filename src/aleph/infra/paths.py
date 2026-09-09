"""Where `data/` is - resolved from the package, never from the CWD.

Eleven places under `src/aleph/` spelled the location of the data directory
themselves, every one of them as the relative string `"data"`. A relative
path is not a location; it is a location plus an assumption about the
current working directory. The assumption held because every documented
command is run from the repository root, and it fails silently the moment
one is not: `FileNotFoundError: data/manifest.json` names a path that does
exist, from a directory that is not the one the reader is looking at.

Resolution order, and why:

1. `ALEPH_DATA_DIR`, if set. The filings are not distributed with this
   repository (docs/adr/0006), so someone holding them elsewhere - a shared
   drive, a machine where `data/` would sit inside OneDrive - needs a way to
   say so that does not involve editing source.
2. `<repo root>/data`, found by walking up from THIS FILE:
   src/aleph/infra/paths.py -> src/aleph/infra -> src/aleph -> src -> root.
   This is the branch every documented command takes, and it produces the
   same directory the old relative string produced when run from the root.
3. `Path("data").resolve()` - the old CWD-relative behaviour - only when
   step 2 names a directory that does not exist, which means the package is
   installed somewhere other than a source checkout (a wheel in
   site-packages, where `parents[3]` is not a repository root). Not a silent
   guess at a number: any file actually missing still raises
   FileNotFoundError naming the absolute path it looked at.

This module imports nothing from the rest of the package and must stay that
way - `infra.cache`, `valuation.pipeline`, `extraction.extractor` and
`forensics.language` all import it.
"""
import os
from pathlib import Path

ENV_VAR = "ALEPH_DATA_DIR"


def resolve_data_dir() -> Path:
    """The data directory, by the order documented above."""
    override = os.environ.get(ENV_VAR)
    if override:
        return Path(override).expanduser().resolve()

    from_package = Path(__file__).resolve().parents[3] / "data"
    if from_package.is_dir():
        return from_package

    return Path("data").resolve()


# Resolved once, at import. `ALEPH_DATA_DIR` is read here and not re-read
# later: a directory that changes underneath a running process would mean
# two facts in one result came from two different sets of filings.
DATA_DIR = resolve_data_dir()


def data_path(*parts: str) -> Path:
    """DATA_DIR / parts - the one spelling callers should use."""
    return DATA_DIR.joinpath(*parts)
