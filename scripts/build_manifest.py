"""Deterministic document verifier and manifest builder. No LLM involved.

Fails loudly on any anomaly: a silent None is worse than a crash.
"""
import hashlib
import json
import re
import sys
from pathlib import Path

from pypdf import PdfReader

DATA_DIR = Path("data")
MANIFEST_PATH = Path("data/manifest.json")

MONTHS = ("January|February|March|April|May|June|July|"
          "August|September|October|November|December")

# Statutory SEC cover-page wording. Whitespace is normalised before matching,
# so a single space matches any run of newlines, tabs or control characters.
RE_FISCAL_YEAR = re.compile(
    rf"For the fiscal year ended\s+({MONTHS})\s+(\d{{1,2}}),\s*(\d{{4}})"
)
RE_FORM_TYPE = re.compile(r"FORM\s+(10-K(?:/A)?)")


class ManifestError(Exception):
    """Raised when a document is not what it claims to be."""


def normalise(text: str) -> str:
    """Collapse every run of whitespace and control chars into one space."""
    return re.sub(r"[\s\x00-\x1f]+", " ", text)


def sha256_of(path: Path) -> str:
    """Hash file contents in chunks. Identity lives in bytes, not in the name."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def extract_one(pattern: re.Pattern, text: str, label: str, path: Path) -> re.Match:
    """Return the single match, or raise. Zero and two are both failures."""
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise ManifestError(
            f"{path.name}: expected exactly 1 match for {label}, "
            f"found {len(matches)}.\nPage 1 excerpt:\n{text[:300]}"
        )
    return matches[0]


def inspect(path: Path) -> dict:
    reader = PdfReader(path)
    page_one = normalise(reader.pages[0].extract_text() or "")

    form_type = extract_one(RE_FORM_TYPE, page_one, "form type", path).group(1)
    if form_type != "10-K":
        raise ManifestError(
            f"{path.name}: form type is {form_type}, not 10-K. "
            "Amendments are partial documents and break year-over-year language forensics."
        )

    fiscal = extract_one(RE_FISCAL_YEAR, page_one, "fiscal year end", path)
    month, day, year = fiscal.group(1), int(fiscal.group(2)), int(fiscal.group(3))

    return {
        "file_name": path.name,
        "sha256": sha256_of(path),
        "size_bytes": path.stat().st_size,
        "n_pages": len(reader.pages),
        "form_type": form_type,
        "fiscal_year_end": f"{year}-{month}-{day:02d}",
        "fiscal_year": year,
    }


def main() -> None:
    pdfs = sorted(DATA_DIR.glob("*.pdf"))
    if not pdfs:
        raise ManifestError(f"No PDFs found in {DATA_DIR.resolve()}")

    records, seen_hashes = [], {}
    for path in pdfs:
        record = inspect(path)

        # Same bytes under two names means one document downloaded twice.
        digest = record["sha256"]
        if digest in seen_hashes:
            raise ManifestError(
                f"Duplicate content: {path.name} and {seen_hashes[digest]} "
                "share the same SHA-256."
            )
        seen_hashes[digest] = path.name

        records.append(record)
        print(f"OK  {record['file_name']:<26} "
              f"FY{record['fiscal_year']}  "
              f"{record['n_pages']:>3}p  {digest[:12]}")

    MANIFEST_PATH.write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(f"\nWrote {len(records)} records to {MANIFEST_PATH}")


if __name__ == "__main__":
    try:
        main()
    except ManifestError as exc:
        print(f"\nMANIFEST FAILED\n{exc}", file=sys.stderr)
        sys.exit(1)