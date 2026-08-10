"""Language forensics: detect tone and content shifts in MD&A between years.
Deterministic text analysis first; LLM only for interpreting what changed."""
import re
from collections import Counter
from typing import Dict, List

# Words that signal reduced commitment or increased uncertainty
HEDGE_WORDS = [
    "may", "might", "could", "possibly", "potentially", "uncertain",
    "we believe", "we expect", "approximately", "substantially",
    "no assurance", "cannot guarantee", "subject to",
]

# Words that signal deterioration
NEGATIVE_WORDS = [
    "decline", "decrease", "loss", "impairment", "adverse", "weakness",
    "challenging", "headwind", "unfavorable", "shortfall", "litigation",
]

# Words that signal confidence
POSITIVE_WORDS = [
    "growth", "increase", "strong", "improvement", "expansion",
    "record", "favorable", "momentum", "opportunity",
]


def normalize(text: str) -> str:
    """Lowercase and collapse whitespace so counts are comparable."""
    return " ".join(text.lower().split())


def count_phrases(text: str, phrases: List[str]) -> Dict[str, int]:
    """Count occurrences of each phrase. Multi-word phrases handled correctly."""
    norm = normalize(text)
    return {p: len(re.findall(r"\b" + re.escape(p) + r"\b", norm)) for p in phrases}


def per_1000_words(count: int, text: str) -> float:
    """Normalize by document length - a longer MD&A naturally has more of everything."""
    words = len(normalize(text).split())
    return (count / words * 1000) if words else 0.0

def tone_comparison(prev_text: str, curr_text: str) -> dict:
    """Compare hedging and sentiment density between two years."""
    result = {}
    for label, word_list in (("hedging", HEDGE_WORDS),
                             ("negative", NEGATIVE_WORDS),
                             ("positive", POSITIVE_WORDS)):
        prev_total = sum(count_phrases(prev_text, word_list).values())
        curr_total = sum(count_phrases(curr_text, word_list).values())
        prev_density = per_1000_words(prev_total, prev_text)
        curr_density = per_1000_words(curr_total, curr_text)
        change = ((curr_density - prev_density) / prev_density * 100) if prev_density else 0.0
        result[label] = {"prev_per_1k": prev_density, "curr_per_1k": curr_density,
                         "change_pct": change}
    return result


def content_diff(prev_text: str, curr_text: str, min_length: int = 4) -> dict:
    """Find terms that appeared or disappeared between years.
    Omissions are the hardest signal to spot by hand and often the most telling."""
    stop = {"that", "with", "this", "from", "have", "were", "been", "which",
            "their", "would", "there", "these", "than", "when", "will", "also",
            "such", "into", "under", "over", "other", "more", "some", "they"}

    def significant_terms(text):
        words = [w for w in re.findall(r"[a-z]{%d,}" % min_length, normalize(text))
                 if w not in stop]
        return Counter(words)

    prev_terms = significant_terms(prev_text)
    curr_terms = significant_terms(curr_text)

    # Terms that were meaningfully present before and are now gone
    disappeared = {w: c for w, c in prev_terms.items() if c >= 3 and curr_terms.get(w, 0) == 0}
    # Terms that are meaningfully present now and were absent before
    appeared = {w: c for w, c in curr_terms.items() if c >= 3 and prev_terms.get(w, 0) == 0}

    return {
        "disappeared": dict(sorted(disappeared.items(), key=lambda x: -x[1])[:15]),
        "appeared": dict(sorted(appeared.items(), key=lambda x: -x[1])[:15]),
    }

if __name__ == "__main__":
    from pypdf import PdfReader

    # Two MD&A-ish sections from the same filing, as a mechanism demo.
    # For real forensics these must come from TWO SEPARATE filings (2024 10-K vs 2025 10-K).
    reader = PdfReader("../../data/uber_10k.pdf")
    section_a = "\n".join(reader.pages[p].extract_text() or "" for p in range(50, 55))
    section_b = "\n".join(reader.pages[p].extract_text() or "" for p in range(55, 60))

    print("=" * 70)
    print("TONE COMPARISON (per 1000 words)")
    print("=" * 70)
    tone = tone_comparison(section_a, section_b)
    for label, d in tone.items():
        arrow = "UP  " if d["change_pct"] > 10 else ("DOWN" if d["change_pct"] < -10 else "flat")
        print(f"  {label:<10} {d['prev_per_1k']:>6.2f} -> {d['curr_per_1k']:>6.2f}"
              f"   {d['change_pct']:>+7.1f}%  [{arrow}]")

    print("\n" + "=" * 70)
    print("CONTENT DIFF")
    print("=" * 70)
    diff = content_diff(section_a, section_b)
    print("  DISAPPEARED (present before, absent now):")
    for w, c in list(diff["disappeared"].items())[:10]:
        print(f"    {w:<25} was mentioned {c}x")
    print("\n  APPEARED (absent before, present now):")
    for w, c in list(diff["appeared"].items())[:10]:
        print(f"    {w:<25} now mentioned {c}x")