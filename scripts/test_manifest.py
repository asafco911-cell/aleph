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
from pathlib import Path

from aleph.documents.manifest import committed_hashes, replaced_documents
from aleph.schemas.documents import DocumentRecord

MANIFEST = Path("data/manifest.json")


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


if __name__ == "__main__":
    test_committed_hashes_reads_the_manifest()
    test_missing_manifest_is_not_an_error()
    test_unchanged_documents_report_no_replacement()
    test_a_changed_hash_is_reported()
    test_every_doc_id_is_checked_not_just_the_first()
    test_a_new_doc_id_is_not_a_replacement()
    print("\nAll tests passed.")
