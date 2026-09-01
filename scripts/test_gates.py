"""Prove each extraction gate rejects what it is supposed to reject.

A gate that has only ever passed is an assumption, not a mechanism. The
fixture reproduces the real line structure measured in Uber's Note 13, so the
test exercises the same code path production does.
"""
import sys

from aleph.extraction.gates import resolve_axis, row_cells, validate
from aleph.schemas.evidence import Fact, FactSource

SOURCE = "\n".join([
    "Orphan row with no header above it 11 22 33",
    "Income from operations 1,110",
    "Year Ended December 31, 2024",
    "Mobility Delivery Freight Total",
    "Revenue $ 25,087 $ 13,750 $ 5,141 $ 43,978",
    "Broken row $ 100 $ 200 $ 300 $ 999",
])
SRC = FactSource(doc_id="TEST_FY2024", kind="note", ref="13", pages=[1])
ROW = "Revenue $ 25,087 $ 13,750 $ 5,141 $ 43,978"
BROKEN = "Broken row $ 100 $ 200 $ 300 $ 999"
ORPHAN = "Orphan row with no header above it 11 22 33"


def fact(name, value, quote=ROW, period="FY2024", source=SRC, unit="USD millions"):
    return Fact(name=name, value=value, unit=unit,
                quote=quote, period=period, source=source)


CASES = [
    ("correct label mapping", None, fact("Mobility revenue FY2024", 25087.0)),
    ("correct total", None, fact("Total revenue FY2024", 43978.0)),
    ("wrong column", "column_alignment", fact("Delivery revenue FY2024", 25087.0)),
    ("period mismatch", "column_alignment",
     fact("Mobility revenue FY2023", 25087.0, period="FY2023")),
    ("ambiguous label", "column_alignment",
     fact("Mobility and Delivery revenue FY2024", 25087.0)),
    ("components do not sum", "cross_foot",
     fact("Mobility broken FY2024", 100.0, quote=BROKEN)),
    ("no header above row", "columns_undetermined",
     fact("Orphan FY2024", 11.0, quote=ORPHAN)),
    ("fabricated quote", "quote_exists",
     fact("Invented FY2024", 9999.0, quote="Revenue $ 9,999 $ 1 $ 2 $ 3")),
    ("value absent from quote", "value_in_quote",
     fact("Mobility revenue FY2024", 5000.0)),
    ("missing provenance", "has_source",
     fact("Mobility revenue FY2024", 25087.0, source=None)),
    ("no caption in region", None,
     fact("Income from operations FY2024", 1110.0, quote="Income from operations 1,110")),
]

axis = resolve_axis(SOURCE, ROW, len(row_cells(ROW)))
print(f"axis: kind={axis.kind} labels={axis.labels} period={axis.period}")
if axis.kind != "labels" or axis.period != "FY2024":
    print("FAILED: axis resolution is wrong")
    sys.exit(1)

failures = 0
for label, expected_gate, item in CASES:
    _, rejected = validate([item], SOURCE)
    actual = rejected[0].gate if rejected else None
    ok = actual == expected_gate
    failures += not ok
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<32} "
          f"expected={expected_gate or 'accept':<21} actual={actual or 'accept'}")

# check_unit_matches_source needs a captioned region: UBER_FY2024's own
# operations statement caption, reused verbatim (measured, not invented,
# see item 1 of the unit-fix review) - "(In millions, except share amounts
# which are reflected in thousands, and per share amounts)" declares two
# scales in one sentence, which is exactly the case the share-count
# exemption exists for.
CAPTIONED_SOURCE = "\n".join([
    "UBER TECHNOLOGIES, INC.",
    "CONSOLIDATED STATEMENTS OF OPERATIONS",
    "(In millions, except share amounts which are reflected in thousands, "
    "and per share amounts)",
    "Year Ended December 31, 2024",
    "Revenue $ 43,978",
    "Diluted weighted-average shares outstanding 2,150,508",
])

UNIT_CASES = [
    ("unit contradicts caption", "unit_matches_source",
     fact("Revenue FY2024", 43978.0, quote="Revenue $ 43,978", unit="USD thousands")),
    ("share count under dual-scale caption", None,
     fact("Diluted weighted-average shares outstanding FY2024", 2150508.0,
          quote="Diluted weighted-average shares outstanding 2,150,508",
          unit="thousands")),
]

for label, expected_gate, item in UNIT_CASES:
    _, rejected = validate([item], CAPTIONED_SOURCE)
    actual = rejected[0].gate if rejected else None
    ok = actual == expected_gate
    failures += not ok
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<32} "
          f"expected={expected_gate or 'accept':<21} actual={actual or 'accept'}")

sys.exit(1 if failures else 0)
