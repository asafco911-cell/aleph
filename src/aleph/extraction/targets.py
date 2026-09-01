"""Company-agnostic extraction targets.

Note NUMBERING differs between filers, so a hardcoded number silently returns
the wrong note. Notes are resolved by TITLE against the manifest instead.

Note LOCATION differs too. Measured: Uber discloses geographic revenue in its
segment note ("Segment Information and Geographic Information"); DoorDash
discloses it in the revenue note while its segment note carries none. Optional
disclosures are therefore asked of every note that could hold them, and their
absence is recorded as a fact about the filer rather than a tool failure.
"""
from ..schemas.documents import DocumentRecord

# (key, target, question, required)
# Periods are requested explicitly. Measured on LYFT_FY2025: the same prompt
# shape returned three periods from the cash flow statement, two from the
# balance sheet and one from the income statement, which left revenue_growth
# with a single period and nothing to compute a trend from. The note-level
# questions below already say "for each year"; the statement-level ones did
# not, and the model filled the gap with its own judgement.
STATEMENT_TARGETS = [
    ("cash_flows", "statement:cash_flows",
     "Extract net cash provided by operating activities, purchases of "
     "property and equipment, and stock-based compensation, for each "
     "period presented.", True),
    ("operations", "statement:operations",
     "Extract total revenue, diluted weighted-average shares outstanding, "
     "interest expense, and net income attributable to the company, for each "
     "period presented.", True),
    ("balance_sheet", "statement:balance_sheet",
     "Extract cash and cash equivalents, short-term investments, restricted "
     "cash, and long-term debt net of current portion, for each period "
     "presented.", True),
]

# One distinctive word, disambiguated by uniqueness. Guessing a full phrase
# fails: filers write "Segment Information", "Segment Reporting", or
# "Segments and Geographic Information".
NOTE_TARGETS = [
    ("segments", ("segment",),
     "Extract revenue by reportable segment for each year.", False),
    # Presentation of the tax rate varies: some filers state a percentage,
    # others reconcile only in dollars. Asking for the components as well lets
    # Python compute the rate rather than depend on presentation.
    ("taxes", ("income tax",),
     "Extract the effective income tax rate if stated as a percentage, and "
     "also the total provision for income taxes and income or loss before "
     "income taxes, for each year.", True),
]

# Asked of EVERY note whose title contains any of these words.
GEOGRAPHY_NOTE_WORDS = ("segment", "revenue")
GEOGRAPHY_QUESTION = (
    "Extract revenue by geography or by country for each year, if disclosed."
)


def resolve_targets(record: DocumentRecord) -> list[tuple[str, str, str, bool]]:
    """Return (key, target, question, required) for one filing."""
    resolved = list(STATEMENT_TARGETS)

    for key, keywords, question, required in NOTE_TARGETS:
        matches = [
            note for note in record.notes
            if all(word in note.title.lower() for word in keywords)
        ]
        # Zero or several matches is an ambiguous resolution, not a target.
        target = (f"note:{matches[0].number}" if len(matches) == 1
                  else f"UNRESOLVED:{len(matches)}")
        resolved.append((key, target, question, required))

    seen: set[int] = set()
    for note in record.notes:
        title = note.title.lower()
        if not any(word in title for word in GEOGRAPHY_NOTE_WORDS):
            continue
        if note.number in seen:
            continue
        seen.add(note.number)
        resolved.append(
            (f"geography_n{note.number}", f"note:{note.number}",
             GEOGRAPHY_QUESTION, False)
        )

    return resolved