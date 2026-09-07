"""Extract facts from one bounded region of a filing.

Python selects the region; the model only reads it. The model never searches,
navigates, computes, or chooses a source.
"""
import json
import os
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

from ..documents import extract_note, extract_statement
from ..documents.errors import DocumentError
from ..infra.cache import Cache
from ..schemas.documents import DocumentRecord
from ..schemas.evidence import ExtractedFacts, Fact, FactSource
from .gates import Rejection, validate

PROMPT_VERSION = "extract-v3"
DEFAULT_MODEL = "claude-sonnet-5"

# Output ceiling for one bounded call. Raised from 4,000 when the cash-flow
# target began asking for every line of the CFO reconciliation across three
# periods: the answer overran and arrived truncated. Raising the ceiling does
# not remove that failure mode, it moves it, which is why the truncation is
# now detected and named rather than left to surface as a JSON parse error.
MAX_OUTPUT_TOKENS = 16000


class ExtractionError(RuntimeError):
    """The model's answer cannot be trusted, for a reason worth naming."""

SYSTEM_PROMPT = """You extract financial data points from SEC filings.

RULES:
- Every fact must include a VERBATIM quote from the source. Never paraphrase.
- Only extract what is actually present. Do not infer or compute anything.
- Use precise names that include the period, e.g. 'Freight revenue FY2024'.
- value must be the number as reported, in the unit stated by the document.
- If a figure is shown in parentheses, it is negative.
- Set period to the fiscal year the value belongs to, e.g. 'FY2024'.
- Return JSON only. No prose, no markdown fences."""


def resolve_target(
    record: DocumentRecord, target: str, target_key: str = ""
) -> tuple[str, FactSource]:
    """Turn 'statement:cash_flows' or 'note:11' into text plus provenance."""
    kind, _, ref = target.partition(":")
    path = Path("data") / record.file_name

    if kind == "statement":
        row = next((s for s in record.statements if s.name == ref), None)
        if row is None:
            raise DocumentError(f"{record.doc_id}: no statement '{ref}'")
        text = extract_statement(path, record.statements, ref)
        pages = list(range(row.pdf_page, row.end_page + 1))
    elif kind == "note":
        number = int(ref)
        row = next((n for n in record.notes if n.number == number), None)
        if row is None:
            raise DocumentError(f"{record.doc_id}: no note {number}")
        text = extract_note(path, record.notes, number)
        pages = list(range(row.pdf_page, row.end_page + 1))
    else:
        raise DocumentError(f"unknown target kind '{kind}' (use statement: or note:)")

    return text, FactSource(
        doc_id=record.doc_id, kind=kind, ref=ref,
        target_key=target_key, pages=pages,
    )


def extract(
    record: DocumentRecord,
    target: str,
    question: str,
    model: str = DEFAULT_MODEL,
    cache: Cache | None = None,
    target_key: str = "",
) -> tuple[list[Fact], list[Rejection], bool]:
    """Return (accepted, rejected, cache_hit).

    target_key is provenance only and is deliberately NOT part of the cache
    key: the same note asked the same question returns the same answer whoever
    asked, and including the key would fragment the cache without changing any
    input the model sees.
    """
    cache = cache or Cache()
    source_text, source = resolve_target(record, target, target_key)

    key = Cache.key(
        sha256=record.sha256,
        prompt_version=PROMPT_VERSION,
        model=model,
        target=target,
        question=question,
    )
    payload = cache.get(key)
    cache_hit = payload is not None

    if not cache_hit:
        # anthropic SDK 1.0 removed temperature/top_p/top_k from Messages
        # methods; passing them raises TypeError. This costs nothing here:
        # temperature=0 never guaranteed determinism, so reproducibility has
        # always rested on the content-addressed cache, not on sampling.
        load_dotenv()
        client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        schema = json.dumps(ExtractedFacts.model_json_schema())
        response = client.messages.create(
            model=model,
            max_tokens=MAX_OUTPUT_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": (
                    f"QUESTION: {question}\n\n"
                    f"Return JSON matching this schema (omit the 'source' field, "
                    f"it is filled in by the caller):\n{schema}\n\n"
                    f"SOURCE TEXT:\n{source_text}"
                ),
            }],
        )
        # A truncated answer is a TRUNCATION, not malformed JSON. Without this
        # it surfaces as json.JSONDecodeError "Unterminated string", which
        # sends the reader hunting a parser bug that does not exist. Measured:
        # asking for every line of Uber's CFO reconciliation across three
        # periods overran the old 4,000-token ceiling and failed exactly that
        # way. Nothing truncated is parsed, and nothing truncated is cached -
        # a cached half-answer would be served silently forever after.
        if response.stop_reason == "max_tokens":
            raise ExtractionError(
                f"{source.doc_id} {source.kind}:{source.ref}: the model hit the "
                f"{MAX_OUTPUT_TOKENS}-token output limit and its answer is cut "
                "off. Nothing was parsed and nothing was cached. Ask this "
                "target's question for fewer quantities, or split the target - "
                "raising the ceiling only moves the overrun to the next question."
            )

        raw = "".join(
            block.text for block in response.content if block.type == "text"
        ).strip()
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        payload = json.loads(raw)
        cache.put(key, payload)

    facts = ExtractedFacts(**payload).facts
    for fact in facts:
        fact.source = source

    accepted, rejected = validate(facts, source_text)
    return accepted, rejected, cache_hit