"""Single source of truth for text comparison across Aleph.

Normalisation is for MATCHING ONLY. Never store or send normalised text to an
LLM: citations must quote the source verbatim, or provenance breaks.
"""
import re
import unicodedata

# Printable Unicode look-alikes. repr() does NOT escape these, so they stay
# invisible during debugging and silently break equality checks.
LOOKALIKES = {
    "\u2018": "'",   # left single quotation mark
    "\u2019": "'",   # right single quotation mark
    "\u201c": '"',   # left double quotation mark
    "\u201d": '"',   # right double quotation mark
    "\u2013": "-",   # en dash
    "\u2014": "-",   # em dash
    "\u2212": "-",   # minus sign
    "\u00a0": " ",   # non-breaking space
    "\u2009": " ",   # thin space
    "\u200b": "",    # zero-width space
    "\ufeff": "",    # byte order mark
}

_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_WHITESPACE = re.compile(r"\s+")


def normalise(text: str, fold_case: bool = True) -> str:
    """Return a comparison-safe form of text.

    NFKC first, so composed and decomposed forms of the same character agree.
    """
    text = unicodedata.normalize("NFKC", text)
    for source, target in LOOKALIKES.items():
        text = text.replace(source, target)
    text = _CONTROL.sub(" ", text)
    text = _WHITESPACE.sub(" ", text).strip()
    return text.lower() if fold_case else text


def contains(haystack: str, needle: str) -> bool:
    """Substring test that survives typographic and whitespace differences."""
    return normalise(needle) in normalise(haystack)