"""Deterministic validation of LLM-extracted facts.

The model is asked to copy, not to compute. Every gate here is Python checking
that copying actually happened, because LLM verification is probabilistic and
Python is not. A fact that fails any gate is rejected, never repaired.

Column semantics are resolved LOCALLY, from the nearest header ABOVE the quoted
row, with no distance ceiling: measured, the cash flow statement's header sits
26 rows above its data while the segment note's sits 2 rows above.

Column ORDER is never assumed. Uber's cash flow statement runs 2022 2023 2024,
its balance sheet runs 2023 2024, and Lyft's cash flow statement runs
2024 2023 2022, so any rule of the form "the last column is the most recent
year" works on one statement and silently mis-assigns on another.

Header LAYOUT is not assumed either. Uber prints "As of December 31, 2023 As of
December 31, 2024" on one line; DoorDash prints the date phrase and each year
on separate lines. Lone years are therefore accumulated while climbing and
reversed into printed order.
"""
import re
from dataclasses import dataclass

from ..infra.textnorm import normalise, normalise_lines
from ..infra.units import resolve_scale
from ..schemas.evidence import Fact

RE_NUMBER = re.compile(r"\(?\$?\s?\d[\d,]*(?:\.\d+)?\)?")
RE_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")

MONTHS = ("january|february|march|april|may|june|july|"
          "august|september|october|november|december")

# "As of December 31," / "December 31," - the day number is part of the date
# and must not be counted as table data.
RE_DATE_PHRASE = re.compile(rf"(?:as\s+of\s+)?(?:{MONTHS})\s+\d{{1,2}},?", re.IGNORECASE)

RE_PERIOD_LINE = re.compile(
    r"^(?:year|years|three months|six months|nine months)\s+ended\b|^as\s+of\b",
    re.IGNORECASE,
)

TOTAL_TOKENS = ("total", "consolidated")

# A running header carrying the registrant's name is not a column axis.
# "DOORDASH, INC." is two capitalised tokens above a two-column row and passed
# a purely typographic test.
ENTITY_MARKERS = ("inc.", "inc", "corp.", "corp", "llc", "ltd.", "ltd",
                  "plc", "company", "holdings", "technologies")

# Statement and note captions declare scale near their table, e.g.
# "(In millions)" or "(in thousands)". A region can hold more than one:
# measured, UBER_FY2024 note:13 is 7,738 characters and declares
# "(in millions)" twice - once at offset 2,138 above the segment table, again
# at offset 7,046 above the geography table. One caption per table, not one
# per region. The caption that governs a quoted row is therefore the nearest
# one ABOVE it, with no distance ceiling - the same principle resolve_axis
# already uses for column headers.
RE_SCALE_CAPTION = re.compile(r"\(\s*in\s+(thousand|million|billion)s?\b", re.IGNORECASE)


@dataclass
class Rejection:
    fact_name: str
    gate: str
    detail: str

@dataclass
class Axis:
    """What the columns of the quoted row mean."""
    kind: str  # "years" | "labels" | "unknown"
    labels: list[str]
    period: str | None = None  # Set when a single period governs the table.


def _parse_number(token: str) -> float | None:
    """Parse a filing-formatted number. Parentheses mean negative."""
    negative = "(" in token
    digits = re.sub(r"[^\d.]", "", token)
    if not digits or digits == ".":
        return None
    try:
        value = float(digits)
    except ValueError:
        return None
    return -value if negative else value


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


def row_cells(quote: str) -> list[float]:
    """Numeric cells of a quoted row, in order."""
    parsed = [_parse_number(token) for token in RE_NUMBER.findall(quote)]
    return [value for value in parsed if value is not None]


def _strip_dates(line: str) -> str:
    """Remove date phrases so their day numbers are not read as table data."""
    return RE_DATE_PHRASE.sub(" ", line)


def _non_year_numbers(line: str) -> list[str]:
    return [
        token for token in RE_NUMBER.findall(line)
        if not RE_YEAR.fullmatch(token.strip())
    ]


def _is_label_header(labels: list[str]) -> bool:
    """Distinguish a column header from a subheading or a registrant name.

    Word count alone is insufficient: "Costs and expenses" has three words
    above a three-column row, and "DOORDASH, INC." has two above a two-column
    row. Column headers capitalise every token AND name no legal entity. The
    test fails safe - a rejected real header yields columns_undetermined, never
    a false accept.
    """
    if not labels or not all(token[:1].isupper() for token in labels):
        return False
    return not any(token.lower().strip(",") in ENTITY_MARKERS for token in labels)


def _find_line(lines: list[str], quote: str) -> int:
    """Index of the source line the quote came from, or -1."""
    target = normalise(quote)
    for index, line in enumerate(lines):
        if target and target in normalise(line):
            return index
    return -1


def _find_period_above(lines: list[str], start: int) -> str | None:
    """Climb above the column header looking for the governing period."""
    for index in range(start - 1, -1, -1):
        line = lines[index].strip()
        if not line:
            continue
        bare = _strip_dates(line).strip()
        years = RE_YEAR.findall(bare)
        if RE_PERIOD_LINE.match(line):
            if len(years) == 1:
                return f"FY{years[0]}"
            continue
        if len(years) == 1 and not _non_year_numbers(bare):
            return f"FY{years[0]}"
        if RE_NUMBER.search(bare):
            return None  # A data row: the header block has ended.
    return None


def resolve_axis(source_text: str, quote: str, n_cells: int) -> Axis:
    """Determine column meaning from the nearest header above the quoted row."""
    lines = normalise_lines(source_text, fold_case=False).split("\n")
    row = _find_line(lines, quote)
    if row < 0 or n_cells == 0:
        return Axis("unknown", [])

    # Years printed one per line are collected while climbing. Collection runs
    # bottom-up, so the printed order is the reverse.
    stacked: list[str] = []

    for index in range(row - 1, -1, -1):
        line = lines[index].strip()
        if not line:
            continue

        bare = _strip_dates(line).strip()
        if not bare:
            continue  # A pure date phrase: still inside the header block.

        years = RE_YEAR.findall(bare)
        others = _non_year_numbers(bare)

        if len(years) >= 2 and not others:
            return Axis("years", [f"FY{year}" for year in years])

        if len(years) == 1 and not others:
            # The same year appearing twice while climbing means the lines
            # being collected are not one column header. Two identical labels
            # make index() unreachable for the second column, so the axis is
            # abandoned rather than reported.
            if years[0] in stacked:
                return Axis("unknown", [])
            stacked.append(years[0])
            if len(stacked) == n_cells:
                return Axis("years", [f"FY{y}" for y in reversed(stacked)])
            continue

        if not RE_NUMBER.search(line):
            labels = line.split()
            if len(labels) == n_cells and _is_label_header(labels):
                return Axis("labels", labels, _find_period_above(lines, index))
            continue  # Section subheading or caption: keep climbing.

        # A data row ends the header block; any years collected above it belong
        # to a different table.
        stacked = []

    return Axis("unknown", [])


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

    An em dash denotes nil in financial statements, so a zero is satisfied by
    a dash where a figure would otherwise stand.
    """
    flat = re.sub(r"\s+", "", fact.quote)
    if any(re.sub(r"\s+", "", form) in flat for form in _number_forms(fact.value)):
        return None
    if fact.value == 0 and re.search(r"[\u2014\u2013-]", fact.quote):
        return None
    return Rejection(fact.name, "value_in_quote",
                     f"value {fact.value} not present in quote: {fact.quote[:80]!r}")


def _nearest_caption_scale(source_text: str, quote: str) -> float | None:
    """Return the scale named by the caption nearest above the quote.

    Falls back to the region's only caption when the quote's exact position
    cannot be located by raw substring search (check_quote_exists tolerates
    typographic differences via normalisation; this needs a character OFFSET
    to compare positions, so it cannot). With more than one caption and an
    unlocatable quote, or with a quote that precedes every caption in the
    region, nothing can be verified - unverifiable, not wrong, so no forward
    guess is made either.
    """
    captions = list(RE_SCALE_CAPTION.finditer(source_text))
    if not captions:
        return None
    position = source_text.find(quote)
    if position < 0:
        return resolve_scale(captions[0].group(1)) if len(captions) == 1 else None
    before = [c for c in captions if c.start() <= position]
    if not before:
        return None
    return resolve_scale(before[-1].group(1))


def check_unit_matches_source(fact: Fact, source_text: str) -> Rejection | None:
    """The fact's declared unit must match the scale printed in its source.

    check_value_in_quote already proves the NUMBER was copied correctly; this
    proves the SCALE was too. A model that quotes "1,132,009" faithfully but
    labels it "USD millions" instead of "USD thousands" passes every other
    gate and produces a valuation wrong by that factor, with no red flag.

    Fails safe in two ways, both measured rather than assumed:

    - Share-count facts are skipped by NAME, not by unit string. Measured on
      UBER_FY2024's operations statement: the caption reads "(In millions,
      except share amounts which are reflected in thousands, and per share
      amounts)" - one caption, two scales. Comparing the diluted-shares fact
      (unit "thousands") against that caption's own scale token ("million")
      would false-reject the exact fact the valuation depends on. The name
      always says "shares" (the extraction prompt requires it); the unit
      string does not reliably.
    - An unrecognised or absent caption is unverifiable, not wrong, and is
      not rejected - the same rule _is_label_header uses for a header it
      cannot classify.
    """
    if "share" in fact.name.lower():
        return None
    fact_scale = resolve_scale(fact.unit)
    if fact_scale is None:
        return None  # non-currency (percent, decimal, ...) or unrecognised

    source_scale = _nearest_caption_scale(source_text, fact.quote)
    if source_scale is None:
        return None  # no caption governs this quote: unverifiable, not wrong

    if source_scale == fact_scale:
        return None
    return Rejection(
        fact.name, "unit_matches_source",
        f"fact declares unit '{fact.unit}' but the nearest source caption "
        f"above it declares a different scale: {fact.quote[:80]!r}"
    )


def check_cross_foot(fact: Fact, axis: Axis) -> Rejection | None:
    """Components of a labelled row must sum to its stated total.

    Arithmetic needs no knowledge of what the labels mean, so this catches a
    row read partially or merged with a neighbour even when the axis is
    understood.
    """
    if axis.kind != "labels":
        return None
    totals = [
        index for index, label in enumerate(axis.labels)
        if label.lower() in TOTAL_TOKENS
    ]
    if len(totals) != 1:
        return None

    cells = row_cells(fact.quote)
    if len(cells) != len(axis.labels):
        return None

    position = totals[0]
    components = sum(cells[:position] + cells[position + 1:])
    stated = cells[position]
    if abs(components - stated) <= max(1.0, abs(stated) * 0.001):
        return None
    return Rejection(
        fact.name, "cross_foot",
        f"components sum to {components:,.0f} but stated total is {stated:,.0f} "
        f"in row: {fact.quote[:90]}"
    )


def check_column_alignment(fact: Fact, axis: Axis) -> Rejection | None:
    """The value's position in the row must match its column's position.

    Refuses to accept what it cannot verify: an unverifiable multi-column fact
    is exactly the failure this gate exists to catch.
    """
    cells = row_cells(fact.quote)
    if len(cells) < 2:
        return None  # Single value: position carries no information.

    if axis.kind == "unknown" or len(axis.labels) != len(cells):
        return Rejection(
            fact.name, "columns_undetermined",
            f"row has {len(cells)} cells; nearest header gave "
            f"{axis.kind}={axis.labels or 'none'}; mapping cannot be verified"
        )

    if axis.kind == "years":
        if fact.period is None:
            return Rejection(fact.name, "column_alignment",
                             f"period missing; columns are {axis.labels}")
        if fact.period not in axis.labels:
            return Rejection(fact.name, "column_alignment",
                             f"period {fact.period} not among columns {axis.labels}")
        index = axis.labels.index(fact.period)
    else:
        name = normalise(fact.name)
        matches = [
            position for position, label in enumerate(axis.labels)
            if normalise(label) in name
        ]
        if len(matches) != 1:
            return Rejection(
                fact.name, "column_alignment",
                f"name matches {len(matches)} of the column labels {axis.labels}"
            )
        index = matches[0]
        if axis.period and fact.period and fact.period != axis.period:
            return Rejection(
                fact.name, "column_alignment",
                f"row covers {axis.period} but fact claims {fact.period}"
            )

    expected = cells[index]
    if abs(expected - fact.value) <= max(0.5, abs(expected) * 0.001):
        return None
    return Rejection(
        fact.name, "column_alignment",
        f"column {index + 1} of {axis.labels} is {expected:,.0f}, "
        f"got {fact.value:,.0f}"
    )


def validate(
    facts: list[Fact], source_text: str
) -> tuple[list[Fact], list[Rejection]]:
    """Split facts into accepted and rejected. Nothing is silently dropped."""
    accepted, rejected = [], []
    for fact in facts:
        axis = resolve_axis(source_text, fact.quote, len(row_cells(fact.quote)))
        failure = (
            check_has_source(fact)
            or check_quote_exists(fact, source_text)
            or check_value_in_quote(fact)
            or check_unit_matches_source(fact, source_text)
            or check_cross_foot(fact, axis)
            or check_column_alignment(fact, axis)
        )
        (rejected.append(failure) if failure else accepted.append(fact))
    # Coverage is judged over every fact returned, accepted or rejected: the
    # question is whether the row was transcribed, not whether each
    # transcription survived the gates above.
    rejected.extend(check_coverage(facts, source_text))
    return accepted, rejected


def check_coverage(facts: list[Fact], source_text: str) -> list[Rejection]:
    """Report columns the model cited but never transcribed.

    Every other gate asks whether what was copied is correct. This one asks
    whether copying finished, and no per-fact check can see an absence.

    Measured on LYFT_FY2025 before the targets were fixed: the income
    statement row "Revenue $ 6,316,261 $ 5,786,016 $ 4,403,589" produced a
    single fact for FY2025 and the extractor reported accepted=4 rejected=0.
    Nothing was wrong with the fact that came back; what was wrong was the two
    that did not, and the failure surfaced only three layers downstream as
    "no facts extracted for this quantity".

    Scope: rows whose axis resolves to years. A labelled axis would need each
    column mapped to a fact name to say which one is missing, which is not
    attempted here.
    """
    groups: dict[str, list[Fact]] = {}
    for fact in facts:
        groups.setdefault(normalise(fact.quote), []).append(fact)

    gaps: list[Rejection] = []
    for members in groups.values():
        quote = members[0].quote
        cells = row_cells(quote)
        if len(cells) < 2:
            continue  # A single value cannot be partially transcribed.
        axis = resolve_axis(source_text, quote, len(cells))
        if axis.kind != "years" or len(axis.labels) != len(cells):
            continue  # An unverifiable axis is column_alignment's problem.
        claimed = {fact.period for fact in members if fact.period}
        missing = [label for label in axis.labels if label not in claimed]
        if not missing:
            continue
        gaps.append(Rejection(
            f"{members[0].name} [{', '.join(missing)}]",
            "coverage",
            f"row quotes {len(cells)} periods {axis.labels} but only "
            f"{sorted(claimed)} were transcribed: {quote[:90]}"
        ))
    return gaps
