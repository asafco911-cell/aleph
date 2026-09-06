"""Prove a filing replaced under an existing doc_id is detected (ISSUES.md #30).

sha256 is documented in schemas/documents.py as content identity - "The file
name is metadata; this is not" - and until this check existed nothing
compared a freshly computed hash against the one already committed. None of
inspect()'s own checks can catch a replacement: the form-type regex, the
fiscal-year regex and the anchor strings can all still match while the bytes
change underneath the same doc_id.

Runs on the committed data/manifest.json and needs no PDFs, so it runs in CI
alongside the other fixture tests. The records are real DocumentRecord
instances, not stand-ins: a test that passes against a namespace with two
attributes would not prove the real model's fields are read correctly.
"""
import json
import subprocess
from pathlib import Path

from aleph.documents.manifest import committed_hashes, replaced_documents
from aleph.schemas.documents import DocumentRecord

MANIFEST = Path("data/manifest.json")

# What docs/adr/0006, README.md and data/README.md all promise is absent.
NEVER_DISTRIBUTED = (".pdf", "aleph_cache.db", ".env")


def real_records() -> list[DocumentRecord]:
    return [DocumentRecord(**row)
            for row in json.loads(MANIFEST.read_text(encoding="utf-8"))]


def test_committed_hashes_reads_the_manifest():
    hashes = committed_hashes(Path("data"))
    records = real_records()
    assert len(hashes) == len(records), (len(hashes), len(records))
    for record in records:
        assert hashes[record.doc_id] == record.sha256
    assert all(len(h) == 64 for h in hashes.values()), hashes
    print(f"PASS test_committed_hashes_reads_the_manifest ({len(hashes)} filings)")


def test_missing_manifest_is_not_an_error():
    """The first build has nothing to compare against."""
    assert committed_hashes(Path("data/does-not-exist")) == {}
    print("PASS test_missing_manifest_is_not_an_error")


def test_unchanged_documents_report_no_replacement():
    """The negative control. Without it, every test below would pass just as
    well against a function that reported every doc_id as replaced."""
    records = real_records()
    previous = {r.doc_id: r.sha256 for r in records}
    assert replaced_documents(records, previous) == []
    print("PASS test_unchanged_documents_report_no_replacement")


def test_a_changed_hash_is_reported():
    records = real_records()
    target = records[0]
    previous = {r.doc_id: r.sha256 for r in records}
    previous[target.doc_id] = "0" * 64          # the same doc_id, other bytes

    replaced = replaced_documents(records, previous)
    assert len(replaced) == 1, replaced
    doc_id, old, new = replaced[0]
    assert doc_id == target.doc_id
    assert old == "0" * 64
    assert new == target.sha256                  # the real hash, not the fake
    print(f"PASS test_a_changed_hash_is_reported ({doc_id})")


def test_every_doc_id_is_checked_not_just_the_first():
    """A loop that returned after its first hit would pass the test above."""
    records = real_records()
    previous = {r.doc_id: "f" * 64 for r in records}
    replaced = replaced_documents(records, previous)
    assert len(replaced) == len(records), (len(replaced), len(records))
    print(f"PASS test_every_doc_id_is_checked_not_just_the_first ({len(replaced)})")


def test_a_new_doc_id_is_not_a_replacement():
    """A filing added since the last manifest has no committed hash to differ
    from. Reporting it as replaced would block every legitimate addition."""
    records = real_records()
    previous = {r.doc_id: r.sha256 for r in records[1:]}   # first one is new
    assert replaced_documents(records, previous) == []
    print("PASS test_a_new_doc_id_is_not_a_replacement")


def test_no_filing_is_anywhere_in_git_history():
    """docs/adr/0006, README.md and data/README.md all state that the filings
    are not distributed by this repository. Enforce it instead of asserting it.

    Removing a file from HEAD does not remove it from history, and for most of
    this project's life these blobs WERE in history - data/README.md carried a
    section saying so and explaining why that was acceptable. History was
    rewritten on 2026-09-06, before the first push, so all three documents
    became true. Nothing stopped them becoming false again: a filing committed
    once, by accident, would republish it and no test would notice.

    A shallow clone cannot answer this question, so it raises rather than
    passing. A check that cannot see the history it is checking must not
    report success - that is the vacuous pass this project names as its own
    worst failure mode.
    """
    shallow = subprocess.run(
        ["git", "rev-parse", "--is-shallow-repository"],
        capture_output=True, text=True,
    )
    if shallow.returncode != 0:
        raise AssertionError(f"cannot run git: {shallow.stderr.strip()}")
    if shallow.stdout.strip() == "true":
        raise AssertionError(
            "shallow clone: history cannot be inspected, so this check would "
            "pass without proving anything. Use fetch-depth: 0."
        )

    # `git rev-list --objects` is the obvious command here and is WRONG for
    # this: it prints each object once, under a single one of its paths.
    # Git deduplicates blobs by content, so a filing whose bytes happen to
    # match another tracked file is listed under that other file's name and a
    # path-based scan misses it. Found by a negative control that copied one
    # tracked file to a .pdf name and was not caught.
    #
    # `git log --all --name-only` walks every commit and prints every path it
    # touched, so it is complete regardless of content deduplication.
    listing = subprocess.run(
        ["git", "log", "--all", "--name-only", "--pretty=format:"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert listing.returncode == 0, listing.stderr

    offenders = sorted({
        path for path in (l.strip() for l in listing.stdout.splitlines())
        if path and any(p in path for p in NEVER_DISTRIBUTED)
    })
    assert not offenders, (
        "these paths are in git history, so a clone distributes them, and "
        f"docs/adr/0006 is false: {offenders}"
    )

    commits = len(subprocess.run(
        ["git", "rev-list", "--all"], capture_output=True, text=True
    ).stdout.split())
    print(f"PASS test_no_filing_is_anywhere_in_git_history ({commits} commits scanned)")


if __name__ == "__main__":
    test_committed_hashes_reads_the_manifest()
    test_missing_manifest_is_not_an_error()
    test_unchanged_documents_report_no_replacement()
    test_a_changed_hash_is_reported()
    test_every_doc_id_is_checked_not_just_the_first()
    test_a_new_doc_id_is_not_a_replacement()
    test_no_filing_is_anywhere_in_git_history()
    print("\nAll tests passed.")
