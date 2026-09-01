"""Report language changes in one section between two filings.

Passing the same doc_id twice runs the null control, which must come back
empty in every bucket before any other result here means anything.
"""
import json
import sys
from pathlib import Path

from aleph.forensics.language import diff_section, self_diff
from aleph.schemas.documents import DocumentRecord

earlier_id, later_id = sys.argv[1], sys.argv[2]
item = sys.argv[3] if len(sys.argv) > 3 else "7"
limit = int(sys.argv[4]) if len(sys.argv) > 4 else 10

records = {
    r["doc_id"]: DocumentRecord(**r)
    for r in json.loads(Path("data/manifest.json").read_text(encoding="utf-8"))
}

if earlier_id == later_id:
    print("NULL CONTROL - every bucket below must read zero")
    result = self_diff(records[earlier_id], item)
else:
    result = diff_section(records[earlier_id], records[later_id], item)


def collapse(sentences):
    """Collapse exact repeats, which a filing does carry more than once."""
    counts = {}
    for sentence in sentences:
        counts[sentence] = counts.get(sentence, 0) + 1
    return list(counts.items())


def show(sentences, marker, width=200):
    for sentence, n in collapse(sentences)[:limit]:
        suffix = f" (x{n})" if n > 1 else ""
        print(f"  {marker} {sentence[:width]}{suffix}")


print(f"Item {result.item}: {result.earlier_doc} -> {result.later_doc}")
print(f"  {result.earlier_chars:,} -> {result.later_chars:,} chars "
      f"({result.length_delta_pct:+.1f}%) after cleaning")
print(f"  cleaning: {result.numbered_lines_dropped} page-number lines | "
      f"{len(result.headers_stripped)} running headers "
      f"(threshold {result.header_threshold} repeats) | "
      f"{result.discarded_count} non-prose fragments")
print(f"  headers: {result.headers_stripped[:4]}")
print(f"  sentences: {result.earlier_sentences} -> {result.later_sentences}")
print(f"  {result.retained_count} retained | {len(result.removed)} removed | "
      f"{len(result.rolled_off)} rolled off | "
      f"{len(result.still_present)} still present | "
      f"{len(result.added)} added | {len(result.reworded)} reworded | "
      f"{len(result.moved)} moved")
print(f"  {result.dropped_phrase_count} phrases dropped inside surviving "
      f"sentences | noise ratio {result.noise_ratio:.0%}")

# The two channels that carry the finding come first. Everything after them is
# either diagnostic or a control.
print(f"\nREMOVED (first {limit}) - gone from the later filing entirely")
show(result.removed, "-")

print(f"\nDROPPED PHRASES (first {limit}) - omission inside a surviving sentence")
shown = 0
for rewrite in result.reworded:
    if not rewrite.dropped_phrases or shown >= limit:
        continue
    shown += 1
    print(f"  ~ {rewrite.ratio:.2f}")
    for phrase in rewrite.dropped_phrases:
        print(f"     dropped: {phrase[:180]}")
    print(f"     now: {rewrite.after[:180]}")

print(f"\nADDED (first {limit})")
show(result.added, "+")

print(f"\nROLLED OFF (first {limit}) - left with the comparative window")
show(result.rolled_off, "o", 180)

print(f"\nSTILL PRESENT (first {limit}) - in the later filing, but not as its "
      f"own sentence")
show(result.still_present, "=", 180)

print(f"\nMOVED (first {limit}) - same disclosure, different position")
for rewrite in result.moved[:limit]:
    print(f"  > {rewrite.ratio:.2f} {rewrite.after[:180]}")

print(f"\nDISCARDED (first {limit}) - rejected as non-prose, audit this list")
for fragment in result.discarded_sample[:limit]:
    print(f"  x {fragment[:180]}")