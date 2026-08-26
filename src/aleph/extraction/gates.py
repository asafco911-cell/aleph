"""Deterministic validation of LLM-extracted facts.

The model is asked to copy, not to compute. Every gate here is Python checking
that copying actually happened, because LLM verification is probabilistic and
Python is not. A fact that fails any gate is rejected, never repaired.
"""
import re
from dataclasses import dataclass

from ..infra.textnorm import normalise
from ..schemas.evidence import Fact

RE_NUMBER = re.compile(r"\(?\d[\d,]*(?:\.\d+)?\)?")
RE_COLUMN_YEARS = re.compile(
    r"year(?:s)? ended [a-z]+ \d{1,2},?\s+((?:\d{4}\s+){1,5})", re.IGNORECASE
)


@dataclass
class Rejection:
    fact_name: str
    gate: str
    detail: str


def _number_forms(value: float) -> set[str]:
    """Plausible renderings of a number in a filing.

    Filings write negatives in parentheses, group thousands with commas, and
    drop trailing zeros. All of these are the same number on the page.
    """
    magnitude = abs(value)
    forms: set[str] = set()
    for rendered in (f"{magnitude:,.0f}", f"{magnitude:.0f}",
                     f"{magnitude:,.1f}", f"{magnitude:.1f}",
                     f"{magnitude:,.2f}", f"{magnitude:.2f}"):
        forms.add(rendered)
        if rendered.endswith(".0"):
            forms.add(rendered[:-2])
    if value < 0:
        forms |= {f"({form})" for form in forms} | {f"-{form}" for form in forms}
    return forms


def column_periods(source_text: str) -> list[str]:
    """Derive column ordering from the statement header.

    Python derives this; the model never states it. Column-to-period mapping is
    vertical information, and PDF text extraction destroys vertical structure -
    the row survives, the column headers do not travel with it.
    """
    match = RE_COLUMN_YEARS.search(re.sub(r"\s+", " ", source_text))
    if not match:
        return []
    return [f"FY{year}" for year in match.group(1).split()]


def check_has_source(fact: Fact) -> Rejection | None:
    """Provenance is required: a number without an origin is uninterpretable."""
    if fact.source is not None:
        return None
    return Rejection(fact.name, "has_source", "missing provenance")


def check_quote_exists(fact: Fact, source_text: str) -> Rejection | None:
    """The quote must appear in the source. This turns grounding into proof."""
    if normalise(fact.quote) in normalise(source_text):
        return None
    return Rejection(fact.name, "quote_exists",
                     f"quote not found in source: {fact.quote[:80]!r}")


def check_value_in_quote(fact: Fact) -> Rejection | None:
    """The value must appear inside its own quote.

    This catches the commonest extraction failure: reading the right table and
    copying the wrong cell. The result is a plausible number with a real
    citation attached, which has no red flag of its own.
    """
    flat = re.sub(r"\s+", "", fact.quote)
    if any(re.sub(r"\s+", "", form) in flat for form in _number_forms(fact.value)):
        return None
    return Rejection(fact.name, "value_in_quote",
                     f"value {fact.value} not present in quote: {fact.quote[:80]!r}")


def check_column_alignment(fact: Fact, columns: list[str]) -> Rejection | None:
    """The value's position in the row must match its period's column position.

    Without this, a row containing three years passes every other gate no
    matter which number is assigned to which year: the quote is real, the
    number is present, and the result is silently wrong.
    """
    if not columns or fact.period is None:
        return None  # Not a multi-column row, or period unknown: not checkable.
    if fact.period not in columns:
        return Rejection(fact.name, "column_alignment",
                         f"period {fact.period} not among columns {columns}")

    numbers = RE_NUMBER.findall(fact.quote)
    if len(numbers) < len(columns):
        return None  # Fewer numbers than columns: not a full data row.

    # Data columns are the trailing N numbers; any leading number belongs to
    # the row label (e.g. "Note 13").
    cells = numbers[-len(columns):]
    expected = cells[columns.index(fact.period)]
    flat = re.sub(r"\s+", "", expected)
    if any(re.sub(r"\s+", "", form) == flat for form in _number_forms(fact.value)):
        return None
    return Rejection(
        fact.name, "column_alignment",
        f"{fact.period} is column {columns.index(fact.period) + 1} of "
        f"{columns} -> expected {expected}, got {fact.value}"
    )


def validate(
    facts: list[Fact], source_text: str
) -> tuple[list[Fact], list[Rejection]]:
    """Split facts into accepted and rejected. Nothing is silently dropped."""
    columns = column_periods(source_text)
    accepted, rejected = [], []
    for fact in facts:
        failure = (
            check_has_source(fact)
            or check_quote_exists(fact, source_text)
            or check_value_in_quote(fact)
            or check_column_alignment(fact, columns)
        )
        (rejected.append(failure) if failure else accepted.append(fact))
    return accepted, rejected