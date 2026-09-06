# 0007. A filing replaced under an existing doc_id stops the build until a flag says it was deliberate

## Context

`schemas/documents.py` states that `doc_id` is the stable, human-authored id
and `sha256` is "Content identity. The file name is metadata; this is not."
Same `doc_id`, different hash therefore means the document at that path was
replaced.

Nothing checked it. `build_manifest()` computed a fresh hash from whatever
bytes sat at `data/<file_name>` and `scripts/build_manifest.py` wrote it into
`data/manifest.json` unconditionally, never reading the hash already
committed for that `doc_id`. None of `inspect()`'s own checks can catch a
replacement, because none of them look at bytes: the form-type regex, the
fiscal-year regex, and the anchor-string match can all still pass while the
content changes underneath.

Measured, on the case that matters - a replacement that passes everything
else. Re-serialising `data/uber_10k_fy2024.pdf` through pypdf produces a
document with identical text (still a 10-K, still fiscal year 2024, all four
anchors present) and a different sha256:
`ab5f074a...` becomes `e29543aa...`. Before this decision, that overwrote the
committed hash silently and `git status` was the only thing that would ever
have shown it.

Replacements are not all illegitimate. A corrected 10-K/A superseding an
original, or a filing re-downloaded and re-rendered, is a deliberate act. The
question is which failure mode is correct, not whether to notice.

## Decision

`build_manifest()` reads the committed `data/manifest.json` before writing,
compares each `doc_id`'s new hash against the one already recorded, and
raises `DocumentError` on any mismatch - naming every affected `doc_id` with
both hashes. `scripts/build_manifest.py` turns that into `exit(1)`.

`--allow-replacement` on the CLI proceeds with the write. It still prints
every replacement it waved through, with both hashes, above the normal
output: passing the flag is a decision to overwrite, not a reason to stop
saying what was overwritten.

A missing or unparseable `manifest.json` is not a mismatch - the first build
has nothing to compare against - and a `doc_id` absent from the committed
manifest is a new filing, not a replacement.

## Alternative rejected

A hard block with no override: any hash change stops the build, and a
deliberate replacement requires hand-editing `data/manifest.json`.

Rejected because it makes the legitimate case - a corrected filing - require
editing by hand the exact file whose integrity is the thing being protected.
An analyst who has to hand-write a sha256 into the manifest to get past a
block is doing more dangerous work than one who passes a flag, and doing it
in a file where a typo is undetectable.

Also rejected: a plain warning that writes anyway. That is the behaviour this
decision exists to remove. A warning printed above a successful write is read
as noise, and the write has already happened by the time anyone reads it.

## Consequence

The guarantee `schemas/documents.py` states is now enforced rather than
described. This closes one of the two instances of that gap named in
ISSUES.md #30; the other (`DCFInputs.base_cash_flow`'s field comment calling
itself "most recent normalized FCF" while nothing normalises anything) is a
modelling question, tracked in #29, not a missing check.

Proven end to end, not inferred from the code: with the re-rendered PDF in
place, `python scripts\build_manifest.py` exits 1 and prints both hashes;
`python scripts\build_manifest.py --allow-replacement` exits 0, prints
`REPLACED UBER_FY2024` with both hashes, and writes the manifest.
`scripts/test_manifest.py` covers the pure functions on the committed
manifest, including a negative control requiring silence when nothing
changed, and a case requiring every `doc_id` to be checked rather than only
the first.

Decided by Asi, 2026-09-06.
