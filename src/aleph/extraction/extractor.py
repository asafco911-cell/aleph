"""Extract facts from one bounded region of a filing.

Python selects the region; the model only reads it. The model never searches,
navigates, computes, or chooses a source.
"""
import hashlib
import json
import os

from anthropic import Anthropic
from dotenv import load_dotenv

from ..documents import extract_note, extract_statement
from ..documents.errors import DocumentError
from ..infra.cache import Cache
from ..infra.paths import DATA_DIR
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

# The exact schema string sent to the model, computed once. It is a module
# constant rather than a local inside extract() so that the fingerprint below
# is provably over the same bytes the model receives, not over a second
# rendering that could drift from the first.
SCHEMA_JSON = json.dumps(ExtractedFacts.model_json_schema())

# The cache key includes PROMPT_VERSION, not the prompt itself, and that is
# deliberate: hashing the prompt into the key would change every key on every
# wording change and force a paid re-extraction of all six filings. The cost of
# that choice is that PROMPT_VERSION is maintained by hand: forget to bump it
# after editing the prompt and every cached answer is served against a prompt
# that no longer produced it - silently, with no red flag, which is this
# project's named worst failure mode.
#
# So the prompt is not in the key, but it IS fingerprinted, and the fingerprint
# is checked at import. Both halves of what the model sees are covered: the
# system prompt and the JSON schema pasted into the user message.
#
# `raise`, not `assert`: `python -O` strips assert statements, and a guard that
# disappears under a flag is not a guard.
#
# This is coupled to pydantic's schema rendering on purpose. If a pydantic
# upgrade changes model_json_schema()'s output, the text sent to the model
# changes, so the cached answers really were produced under a different prompt
# and the fingerprint SHOULD fire. It is not a false alarm; it is the one case
# where the staleness would otherwise be invisible.
PROMPT_FINGERPRINT = (
    "2377308fe04a7392a6369a72ab5486bd728badb9ec0e35ea678c6a16de47116d"
)


def prompt_fingerprint() -> str:
    """sha256 over everything that reaches the model except the source text."""
    return hashlib.sha256(
        (SYSTEM_PROMPT + SCHEMA_JSON).encode("utf-8")
    ).hexdigest()


if prompt_fingerprint() != PROMPT_FINGERPRINT:
    raise ExtractionError(
        "the extraction prompt has changed but PROMPT_VERSION has not.\n"
        f"  recorded: {PROMPT_FINGERPRINT}\n"
        f"  computed: {prompt_fingerprint()}\n"
        "Either SYSTEM_PROMPT or the ExtractedFacts schema was edited (a "
        "pydantic upgrade counts - the schema is pasted into the prompt). The "
        "cache key is built from PROMPT_VERSION, so every cached answer would "
        "now be served against a prompt that no longer produced it. Bump "
        f"PROMPT_VERSION (currently {PROMPT_VERSION!r}) and record the new "
        "fingerprint in PROMPT_FINGERPRINT."
    )


def resolve_target(
    record: DocumentRecord, target: str, target_key: str = ""
) -> tuple[str, FactSource]:
    """Turn 'statement:cash_flows' or 'note:11' into text plus provenance."""
    kind, _, ref = target.partition(":")
    path = DATA_DIR / record.file_name

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
        response = client.messages.create(
            model=model,
            max_tokens=MAX_OUTPUT_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": (
                    f"QUESTION: {question}\n\n"
                    f"Return JSON matching this schema (omit the 'source' field, "
                    f"it is filled in by the caller):\n{SCHEMA_JSON}\n\n"
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
        # Same treatment as the truncation above, for the same reason: a bare
        # json.JSONDecodeError names a column offset in a string the reader
        # cannot see, and says nothing about which filing or which target
        # produced it. Nothing malformed is parsed and nothing malformed is
        # cached - a cached non-answer would be served silently forever after.
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ExtractionError(
                f"{source.doc_id} {target}: the model's reply is not JSON "
                f"({error}). Nothing was parsed and nothing was cached. "
                f"First 200 characters of the reply: {raw[:200]!r}"
            ) from error
        cache.put(key, payload)

    facts = ExtractedFacts(**payload).facts
    for fact in facts:
        fact.source = source

    accepted, rejected = validate(facts, source_text)
    return accepted, rejected, cache_hit