"""Prove each extraction gate rejects what it is supposed to reject.

A gate that has only ever passed is an assumption, not a mechanism.
"""
import sys

from aleph.extraction.gates import column_periods, validate
from aleph.schemas.evidence import Fact, FactSource

SOURCE = (
    "Year ended December 31, 2022 2023 2024\n"
    "Net cash provided by operating activities 642 3,585 7,137\n"
    "Purchases of property and equipment (252) (223) (242)\n"
)
SRC = FactSource(doc_id="TEST_FY2024", kind="statement", ref="cash_flows", pages=[1])
ROW = "Net cash provided by operating activities 642 3,585 7,137"

CASES = [
    ("correct mapping", None, Fact(
        name="CFO FY2024", value=7137.0, unit="USD millions",
        quote=ROW, period="FY2024", source=SRC)),
    ("swapped columns", "column_alignment", Fact(
        name="CFO FY2024 swapped", value=642.0, unit="USD millions",
        quote=ROW, period="FY2024", source=SRC)),
    ("unknown period", "column_alignment", Fact(
        name="CFO FY2021", value=642.0, unit="USD millions",
        quote=ROW, period="FY2021", source=SRC)),
    ("fabricated quote", "quote_exists", Fact(
        name="CFO invented", value=9999.0, unit="USD millions",
        quote="Net cash provided by financing activities 9,999",
        period="FY2024", source=SRC)),
    ("value absent from quote", "value_in_quote", Fact(
        name="CFO wrong value", value=5000.0, unit="USD millions",
        quote=ROW, period="FY2024", source=SRC)),
    ("missing provenance", "has_source", Fact(
        name="CFO no source", value=7137.0, unit="USD millions",
        quote=ROW, period="FY2024")),
]

columns = column_periods(SOURCE)
print(f"columns detected: {columns}")
if columns != ["FY2022", "FY2023", "FY2024"]:
    print("FAILED: column detection is wrong")
    sys.exit(1)

failures = 0
for label, expected_gate, fact in CASES:
    accepted, rejected = validate([fact], SOURCE)
    actual = rejected[0].gate if rejected else None
    ok = actual == expected_gate
    failures += not ok
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<26} "
          f"expected={expected_gate or 'accept':<17} actual={actual or 'accept'}")

sys.exit(1 if failures else 0)