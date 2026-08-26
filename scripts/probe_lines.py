"""Dump line-preserving normalised text around a search term.

normalise() flattens newlines, which hides whether a table header sits on its
own line. normalise_lines() keeps that structure.
"""
import json
import sys
from pathlib import Path

from aleph.documents import extract_note, extract_statement
from aleph.infra.textnorm import normalise_lines
from aleph.schemas import DocumentRecord

doc_id, target, needle = sys.argv[1], sys.argv[2], sys.argv[3].lower()
before = int(sys.argv[4]) if len(sys.argv) > 4 else 6
after = int(sys.argv[5]) if len(sys.argv) > 5 else 4

record = next(
    DocumentRecord(**r)
    for r in json.loads(Path("data/manifest.json").read_text(encoding="utf-8"))
    if r["doc_id"] == doc_id
)
path = Path("data") / record.file_name

kind, _, ref = target.partition(":")
text = (extract_note(path, record.notes, int(ref)) if kind == "note"
        else extract_statement(path, record.statements, ref))

lines = normalise_lines(text, fold_case=False).split("\n")
for index, line in enumerate(lines):
    if needle in line.lower():
        low, high = max(0, index - before), min(len(lines), index + after + 1)
        print(f"--- match at line {index} ---")
        for offset in range(low, high):
            marker = ">>" if offset == index else "  "
            print(f"{marker} {offset:>4}  {lines[offset][:130]}")
        print()