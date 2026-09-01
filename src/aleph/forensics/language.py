"""Year-over-year language forensics on a single section.

Omission is the signal, so every choice here serves one question: what did the
filer stop saying. Answering it honestly means four separate disciplines.

FIRST, REMOVE WHAT THE PDF ADDED.

  PAGE FURNITURE. Sections are extracted as whole pages, each carrying a
  running header and a bare page number, and the two filings paginate
  differently. Page numbers are found by shape. Headers are found by
  repetition, but repetition alone is not enough: risk factors end in the same
  boilerplate clause dozens of times, and a naive frequency rule deleted the
  word "impacted." from the middle of a sentence, which then glued itself to
  the next bullet and was reported as an omission. A running header appears
  about once per page, so the threshold is scaled to the page count, which the
  page-number lines already measure.

  BULLETS. A bulleted line often carries no terminal punctuation, so the next
  bullet joins it into one unmatchable fragment. Bullet markers therefore open
  a sentence.

  ABBREVIATIONS. Splitting on [.!?] cuts "Uber Technologies, Inc." and
  "certain U.S. federal" into fragments that can never match across years.

  TABLES. Table rows survive extraction without terminal punctuation and glue
  themselves to the sentence below, so the debris is cut off the front, at the
  point where a long run of ordinary words begins.

SECOND, FILTER AS LITTLE AS POSSIBLE.

  The filter is asymmetric in its consequences. A table row that slips through
  is masked into a constant and quietly retained; a real sentence that is
  filtered out disappears with no flag at all. An earlier version of this
  design rejected "Adjusted EBITDA was $6.5 billion, growing $2.4 billion
  year-over-year" because it contains no long run of consecutive words - which
  is a property of every numeric sentence in MD&A, the exact sentences worth
  tracking. So the only structural test is word density, and everything
  rejected is reported for audit.

  NUMBERS. Every figure moves every year, so digits, years and percentages are
  masked before comparison. Magnitude is a separate signal.

THIRD, DISTINGUISH THE KINDS OF CHANGE.

  Sentences are aligned in order before anything is compared, because set
  difference discards document order and pairs sentences from unrelated parts
  of the section. What fails to align is sorted into rewriting, motion,
  roll-off of the oldest comparative year, survival elsewhere, and genuine
  omission. Rewriting is not the opposite of omission: a sentence rewritten at
  0.72 similarity had "demonstrated sustained profitability" taken out of it,
  so every rewrite reports the phrases that vanished inside it. Sentence-level
  omission is the loud case; phrase-level omission inside a surviving sentence
  is the quiet one, and the quiet one is more common.

FOURTH, VERIFY EVERY CLAIM OF OMISSION AGAINST THE LATER FILING.

  Extraction loses a sentence boundary often enough that two sentences arrive
  as one. Pairing then matches the first half and reports the entire second
  half as dropped, which is how this module once claimed that a cash balance
  disclosure had been removed while it sat, intact, in the added list. So
  before anything is called an omission - phrase or sentence - it is checked
  against the masked full text of the later filing. What the filing still
  contains was not dropped.

Python finds the differences. An LLM may later interpret the list, but it
never searches, never compares, and never decides what counts as a change.
"""
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from math import ceil
from pathlib import Path

from ..documents import extract_section
from ..documents.errors import DocumentError
from ..infra.textnorm import normalise
from ..schemas.documents import DocumentRecord

# Masking. Years are masked before numbers so a year is never swallowed by the
# more permissive numeric pattern.
RE_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
RE_MASK_NUMBER = re.compile(r"\$?\s?\d[\d,]*(?:\.\d+)?\s?%?")

# Sentence splitting. The sentinel cannot occur in extracted text, so
# protecting and restoring a dot is lossless.
DOT = "\x00"
BULLETS = "\u2022\u25cf\u25aa\u25e6"
RE_INITIALISM = re.compile(r"\b(?:[A-Za-z]\.){2,}")
ABBREVIATIONS = (
    "Inc.", "Corp.", "Ltd.", "Co.", "plc.", "No.", "Nos.", "Mr.", "Ms.",
    "Mrs.", "Dr.", "Jr.", "Sr.", "St.", "vs.", "etc.", "approx.", "Sec.",
    "Fig.", "Ref.", "Art.",
)
RE_SENTENCE = re.compile(r"(?<=[.!?])\s+|\s+(?=[" + BULLETS + r"])")
# Cross-references like "Item 1A." and "Part II." are not sentence ends. Left
# unprotected they cut a sentence in two and leave an orphan fragment, which
# showed up in the discard list of every run on both registrants.
RE_ITEM_REF = re.compile(
    r"\b(?:Item\s+\d{1,2}[A-Za-z]?|Part\s+[IVX]{1,4})\.", re.IGNORECASE)

# Page furniture. A page number is a line of nothing but digits; a running
# header is a short line repeating on the order of once per page.
RE_BARE_NUMBER_LINE = re.compile(r"^[\s|]*\d{1,4}[\s|]*$")
MAX_HEADER_CHARS = 90
MIN_HEADER_REPEATS = 3
HEADER_PAGE_FRACTION = 0.5

# Prose test.
RE_WORD = re.compile(r"^[A-Za-z][A-Za-z'\u2019\-]*$")
STRIP_CHARS = ".,;:()[]\"'\u201c\u201d\u2018\u2019" + BULLETS
TRIM_PROSE_RUN = 8
MIN_DEBRIS_TOKENS = 3
MIN_WORD_RATIO = 0.6
MIN_SENTENCE_CHARS = 25

# Above this similarity a change is a rewrite rather than an omission. The
# threshold only decides how the change is presented: a rewrite still reports
# what was taken out of it, so nothing is hidden by pairing.
REWORD_SIMILARITY = 0.65
MIN_DROPPED_PHRASE_WORDS = 3

# Sections that present a rolling comparative window. In these, the oldest
# year leaves the filing every year by construction, which is not a
# disclosure decision. Item 1A has no comparative window, so a year
# disappearing from a risk factor there is a real change.
ROLLOFF_ITEMS = ("7", "7A", "8")

DISCARD_SAMPLE_SIZE = 12


@dataclass
class Rewrite:
    before: str
    after: str
    ratio: float
    dropped_phrases: list[str] = field(default_factory=list)


@dataclass
class SectionDiff:
    item: str
    earlier_doc: str
    later_doc: str
    earlier_chars: int = 0
    later_chars: int = 0
    earlier_sentences: int = 0
    later_sentences: int = 0
    retained_count: int = 0
    removed: list[str] = field(default_factory=list)
    rolled_off: list[str] = field(default_factory=list)
    still_present: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    reworded: list[Rewrite] = field(default_factory=list)
    moved: list[Rewrite] = field(default_factory=list)
    headers_stripped: list[str] = field(default_factory=list)
    header_threshold: int = 0
    numbered_lines_dropped: int = 0
    discarded_count: int = 0
    discarded_sample: list[str] = field(default_factory=list)

    @property
    def length_delta_pct(self) -> float:
        if not self.earlier_chars:
            return 0.0
        return (self.later_chars / self.earlier_chars - 1.0) * 100.0

    @property
    def change_candidates(self) -> int:
        return (len(self.removed) + len(self.rolled_off)
                + len(self.still_present) + len(self.added)
                + len(self.reworded) + len(self.moved))

    @property
    def noise_ratio(self) -> float:
        """Share of the change set that is not a sentence-level omission.

        A diagnostic, not a feature. A high value early on means the cleaning
        above is incomplete; a high value once the null control passes means
        the filer rewrote rather than dropped.
        """
        if not self.change_candidates:
            return 0.0
        return ((len(self.reworded) + len(self.moved)
                 + len(self.still_present)) / self.change_candidates)

    @property
    def dropped_phrase_count(self) -> int:
        return sum(len(r.dropped_phrases) for r in self.reworded)


@dataclass
class _Prepared:
    keys: list[str]
    originals: list[str]
    discarded: list[str]
    headers: list[str]
    header_threshold: int
    numbered_lines: int
    chars: int
    masked_text: str


def _strip_page_furniture(text: str) -> tuple[str, list[str], int, int]:
    """Remove page numbers and running headers, then rejoin the section.

    Rejoining with a single space heals a sentence cut at a page break, which
    is why the furniture has to go before splitting.
    """
    lines = [line.strip() for line in text.split("\n")]
    pages = sum(1 for line in lines if RE_BARE_NUMBER_LINE.match(line))
    threshold = max(MIN_HEADER_REPEATS, ceil(HEADER_PAGE_FRACTION * pages))

    counts: dict[str, int] = {}
    for line in lines:
        if line and len(line) <= MAX_HEADER_CHARS:
            counts[line] = counts.get(line, 0) + 1
    headers = {
        line for line, n in counts.items()
        if n >= threshold and not RE_BARE_NUMBER_LINE.match(line)
    }

    kept: list[str] = []
    numbered = 0
    for line in lines:
        if not line or line in headers:
            continue
        if RE_BARE_NUMBER_LINE.match(line):
            numbered += 1
            continue
        kept.append(line)
    return " ".join(kept), sorted(headers), threshold, numbered


def _split_sentences(text: str) -> list[str]:
    """Split on terminal punctuation and bullets, never on an abbreviation."""
    protected = RE_INITIALISM.sub(lambda m: m.group(0).replace(".", DOT), text)
    for abbreviation in ABBREVIATIONS:
        protected = protected.replace(
            abbreviation, abbreviation.replace(".", DOT))
        protected = RE_ITEM_REF.sub(lambda m: m.group(0).replace(".", DOT), protected)
    return [part.replace(DOT, ".").strip().lstrip(BULLETS).strip()
            for part in RE_SENTENCE.split(protected)]


def _word_flags(sentence: str) -> list[bool]:
    return [bool(RE_WORD.match(token.strip(STRIP_CHARS)))
            for token in sentence.split()]


def _trim_leading_debris(sentence: str) -> str:
    """Cut a table block off the front of the sentence it glued itself to.

    A table cannot fake a long run of ordinary words, so the sentence is taken
    to start at the first token that opens one. The cut is made only if what
    precedes it is figure-dense enough to be a table: without that condition
    the rule mutilates ordinary sentences, turning "We ended the year with
    $7.6 billion in unrestricted cash" into "billion in unrestricted cash".
    """
    tokens = sentence.split()
    flags = _word_flags(sentence)
    for start in range(len(tokens)):
        if len(flags) - start < TRIM_PROSE_RUN:
            break
        if not all(flags[start:start + TRIM_PROSE_RUN]):
            continue
        if start < MIN_DEBRIS_TOKENS:
            return sentence
        if sum(flags[:start]) / start >= MIN_WORD_RATIO:
            return sentence
        return " ".join(tokens[start:])
    return sentence


def _is_prose(sentence: str) -> bool:
    """Reject table rows and footnote markers on word density alone.

    Any test based on runs of consecutive words rejects numeric MD&A prose,
    which is the material this module exists to track.
    """
    flags = _word_flags(sentence)
    if not flags or len(sentence) < MIN_SENTENCE_CHARS:
        return False
    return sum(flags) / len(flags) >= MIN_WORD_RATIO


def _mask(sentence: str) -> str:
    """Reduce a sentence to its language, discarding every figure."""
    masked = RE_YEAR.sub("<YEAR>", sentence)
    masked = RE_MASK_NUMBER.sub("<NUM>", masked)
    return normalise(masked)


def _prepare(raw: str) -> _Prepared:
    text, headers, threshold, numbered = _strip_page_furniture(raw)
    keys: list[str] = []
    originals: list[str] = []
    discarded: list[str] = []
    for sentence in _split_sentences(text):
        sentence = _trim_leading_debris(sentence)
        if not sentence:
            continue
        if not _is_prose(sentence):
            discarded.append(sentence)
            continue
        keys.append(_mask(sentence))
        originals.append(sentence)
    return _Prepared(
        keys=keys,
        originals=originals,
        discarded=discarded,
        headers=headers,
        header_threshold=threshold,
        numbered_lines=numbered,
        chars=len(text),
        masked_text=_mask(text),
    )


def _dropped_phrases(before: str, after: str, later_masked: str) -> list[str]:
    """Contiguous phrases present in the earlier sentence and gone from the later.

    This is where most omission actually lives. A sentence that survives with
    one clause removed reads as a rewrite at the sentence level and as a
    deletion at the phrase level, and only the second reading is useful.
    """
    old_words = before.split()
    new_words = after.split()
    matcher = SequenceMatcher(
        None,
        [w.lower().strip(STRIP_CHARS) for w in old_words],
        [w.lower().strip(STRIP_CHARS) for w in new_words],
        autojunk=False,
    )
    phrases: list[str] = []
    for tag, i1, i2, _, _ in matcher.get_opcodes():
        if tag not in ("delete", "replace") or i2 - i1 < MIN_DROPPED_PHRASE_WORDS:
            continue
        phrase = " ".join(old_words[i1:i2])
        # A run of figures that moved is arithmetic, not language. Without
        # this the channel fills with entries like "3,639 36 %".
        flags = _word_flags(phrase)
        if not flags or sum(flags) / len(flags) < MIN_WORD_RATIO:
            continue
        # A phrase the later filing still contains was not dropped; it was
        # re-split or relocated. Extraction loses a sentence boundary often
        # enough that without this check the channel reports whole surviving
        # sentences as omissions.
        if _mask(phrase) in later_masked:
            continue
        phrases.append(phrase)
    return phrases


def _pair(
    before: _Prepared,
    after: _Prepared,
    candidates_i: list[int],
    candidates_j: list[int],
    sink: list[Rewrite],
) -> tuple[set[int], set[int]]:
    """Pair each unmatched sentence with its closest counterpart, if any.

    autojunk is disabled deliberately. Above 200 elements difflib treats any
    element occurring in more than 1% of the sequence as junk, which for a
    character string means every letter and every space. Measured on one real
    pair differing by a single word: 0.60 with the heuristic on, 0.93 with it
    off. Left on, it silently refuses to pair long sentences, and a 10-K is
    made of long sentences.

    quick_ratio is an upper bound on ratio, so screening with it changes speed
    and never changes the result.
    """
    used_i: set[int] = set()
    used_j: set[int] = set()
    for i in candidates_i:
        best_j = None
        best_ratio = 0.0
        for j in candidates_j:
            if j in used_j:
                continue
            matcher = SequenceMatcher(
                None, before.keys[i], after.keys[j], autojunk=False)
            if matcher.real_quick_ratio() < REWORD_SIMILARITY:
                continue
            if matcher.quick_ratio() < REWORD_SIMILARITY:
                continue
            ratio = matcher.ratio()
            if ratio > best_ratio:
                best_j = j
                best_ratio = ratio
        if best_j is not None and best_ratio >= REWORD_SIMILARITY:
            old = before.originals[i]
            new = after.originals[best_j]
            sink.append(Rewrite(
                old, new, best_ratio,
                _dropped_phrases(old, new, after.masked_text)))
            used_i.add(i)
            used_j.add(best_j)
    return used_i, used_j


def _classify(before: _Prepared, after: _Prepared,
              rolloff_before_year: int | None):
    """Align the two sentence sequences, then explain what failed to align."""
    matcher = SequenceMatcher(None, before.keys, after.keys, autojunk=False)
    retained = 0
    deleted: list[int] = []
    inserted: list[int] = []
    reworded: list[Rewrite] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            retained += i2 - i1
            continue
        block_deleted = list(range(i1, i2))
        block_inserted = list(range(j1, j2))
        if tag == "replace":
            # A rewrite lands where the original stood, so pairing is tried
            # inside the block before anything is called an omission.
            used_i, used_j = _pair(
                before, after, block_deleted, block_inserted, reworded)
            block_deleted = [i for i in block_deleted if i not in used_i]
            block_inserted = [j for j in block_inserted if j not in used_j]
        deleted.extend(block_deleted)
        inserted.extend(block_inserted)

    # Second pass over the whole section: a sentence that reappears far from
    # where it stood has moved, which is not the same as having been dropped.
    moved: list[Rewrite] = []
    used_i, used_j = _pair(before, after, deleted, inserted, moved)

    removed: list[str] = []
    rolled_off: list[str] = []
    still_present: list[str] = []
    for i in deleted:
        if i in used_i:
            continue
        sentence = before.originals[i]
        # Same check as for phrases: if the later filing still contains the
        # sentence, it failed to align for a reason of layout, not of
        # disclosure.
        if _mask(sentence) in after.masked_text:
            still_present.append(sentence)
            continue
        years = [int(y) for y in RE_YEAR.findall(sentence)]
        # A sentence that discusses only years the later filing no longer
        # presents left with the comparative window, not by decision of the
        # filer. Measured against the fiscal year, not against whether the
        # digits appear somewhere in the later text: one stray mention of the
        # dropped year anywhere in the section disabled an earlier version of
        # this rule for the whole section, and it silently never fired.
        if (rolloff_before_year is not None
                and years and max(years) < rolloff_before_year):
            rolled_off.append(sentence)
        else:
            removed.append(sentence)

    added = [after.originals[j] for j in inserted if j not in used_j]
    return (retained, removed, rolled_off, still_present, added, reworded,
            moved)


def _diff(item: str, earlier_id: str, later_id: str,
          raw_earlier: str, raw_later: str,
          later_fiscal_year: int | None = None) -> SectionDiff:
    before = _prepare(raw_earlier)
    after = _prepare(raw_later)
    # The later filing presents its own fiscal year and the one before it.
    rolloff_before_year = (
        later_fiscal_year - 1
        if later_fiscal_year is not None and item in ROLLOFF_ITEMS
        else None
    )
    (retained, removed, rolled_off, still_present, added, reworded,
     moved) = _classify(before, after, rolloff_before_year)
    return SectionDiff(
        item=item,
        earlier_doc=earlier_id,
        later_doc=later_id,
        earlier_chars=before.chars,
        later_chars=after.chars,
        earlier_sentences=len(before.keys),
        later_sentences=len(after.keys),
        retained_count=retained,
        removed=removed,
        rolled_off=rolled_off,
        still_present=still_present,
        added=added,
        reworded=reworded,
        moved=moved,
        headers_stripped=sorted(set(before.headers) | set(after.headers)),
        header_threshold=max(before.header_threshold, after.header_threshold),
        numbered_lines_dropped=before.numbered_lines + after.numbered_lines,
        discarded_count=len(before.discarded) + len(after.discarded),
        discarded_sample=before.discarded[:DISCARD_SAMPLE_SIZE],
    )


def diff_section(
    earlier: DocumentRecord,
    later: DocumentRecord,
    item: str,
    data_dir: Path | None = None,
) -> SectionDiff:
    """Compare one item across two filings by the same registrant."""
    data_dir = data_dir or Path("data")
    if earlier.ticker != later.ticker:
        raise DocumentError(
            f"language forensics compares one registrant across time; got "
            f"{earlier.ticker} and {later.ticker}"
        )
    if earlier.fiscal_year >= later.fiscal_year:
        raise DocumentError(
            f"{earlier.doc_id} is not earlier than {later.doc_id}")

    raw_earlier = extract_section(
        data_dir / earlier.file_name, earlier.sections, item)
    raw_later = extract_section(
        data_dir / later.file_name, later.sections, item)
    return _diff(item, earlier.doc_id, later.doc_id, raw_earlier, raw_later,
                 int(later.fiscal_year))


def self_diff(
    record: DocumentRecord,
    item: str,
    data_dir: Path | None = None,
) -> SectionDiff:
    """Null control: a document against itself.

    Anything other than zero change is a defect in this module, and until it
    reads zero no result from diff_section means anything.
    """
    data_dir = data_dir or Path("data")
    raw = extract_section(data_dir / record.file_name, record.sections, item)
    return _diff(item, record.doc_id, record.doc_id, raw, raw)