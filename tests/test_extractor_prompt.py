"""The two things extractor.py must refuse to do quietly.

1. Serve a cached answer against a prompt that no longer produced it. The
   cache key is built from PROMPT_VERSION - a hand-maintained string - and not
   from the prompt itself, because hashing the prompt would force a paid
   re-extraction of all six filings on every wording change. The price of that
   choice is that forgetting to bump PROMPT_VERSION is invisible. The
   import-time fingerprint is what makes it visible.

2. Turn a reply that is not JSON into a bare json.JSONDecodeError, which names
   a character offset in a string the reader never sees and says nothing about
   which filing or which target produced it.

Neither test needs a filing: the first reads source, the second replaces both
the document and the model with fakes.
"""
import json
import types
from pathlib import Path

import pytest

from aleph.extraction import extractor
from aleph.extraction.extractor import (
    PROMPT_FINGERPRINT,
    ExtractionError,
    extract,
    prompt_fingerprint,
)
from aleph.infra.cache import Cache
from aleph.schemas.evidence import FactSource


class TestPromptFingerprint:
    def test_the_recorded_fingerprint_matches_the_live_prompt(self):
        """The positive control. If this fails the module will not import at
        all, so reaching this assertion already proves most of it - it is here
        so the failure has a name in a test report rather than a collection
        error."""
        assert prompt_fingerprint() == PROMPT_FINGERPRINT

    def test_the_fingerprint_covers_the_system_prompt(self, monkeypatch):
        """Negative control: a fingerprint that never moves guards nothing."""
        monkeypatch.setattr(
            extractor, "SYSTEM_PROMPT", extractor.SYSTEM_PROMPT + "\n- One more rule.")
        assert prompt_fingerprint() != PROMPT_FINGERPRINT

    def test_the_fingerprint_covers_the_json_schema(self, monkeypatch):
        """The schema is pasted into the user message, so it is prompt too.
        This is the half that can move without anyone editing this file - a
        pydantic upgrade changes model_json_schema()'s rendering."""
        monkeypatch.setattr(
            extractor, "SCHEMA_JSON", extractor.SCHEMA_JSON + " ")
        assert prompt_fingerprint() != PROMPT_FINGERPRINT

    def test_importing_with_a_stale_fingerprint_raises(self):
        """The guard itself, exercised the way it actually fires: at import.

        The module source is re-executed with the recorded constant tampered
        with, which is precisely the state of an editor who changed the prompt
        and did not bump PROMPT_VERSION.
        """
        source = Path(extractor.__file__).read_text(encoding="utf-8")
        tampered = source.replace(PROMPT_FINGERPRINT, "0" * 64)
        assert tampered != source, "the recorded fingerprint is not in the source"

        probe = types.ModuleType("aleph.extraction._fingerprint_probe")
        probe.__file__ = extractor.__file__
        probe.__package__ = "aleph.extraction"  # relative imports resolve from this

        # RuntimeError, not ExtractionError: re-executing the source defines a
        # SECOND ExtractionError class in the probe's namespace, and it is not
        # the imported one. Matching on the base class and then on the name is
        # the honest way to say "the same error, from a re-executed module".
        with pytest.raises(RuntimeError) as caught:
            exec(compile(tampered, extractor.__file__, "exec"), probe.__dict__)

        assert type(caught.value).__name__ == "ExtractionError"
        message = str(caught.value)
        assert "PROMPT_VERSION" in message, message
        assert extractor.PROMPT_VERSION in message, message


class FakeBlock:
    type = "text"

    def __init__(self, text: str) -> None:
        self.text = text


class FakeResponse:
    stop_reason = "end_turn"

    def __init__(self, text: str) -> None:
        self.content = [FakeBlock(text)]


def fake_anthropic(reply: str):
    """An Anthropic client that answers one thing, whatever it is asked."""
    class Messages:
        def create(self, **kwargs):
            return FakeResponse(reply)

    class Client:
        def __init__(self, **kwargs):
            self.messages = Messages()

    return Client


class TestMalformedReply:
    REPLY = "I'm sorry, I can't find that table. " + "Here is some prose. " * 20

    def _run(self, monkeypatch, tmp_path, reply):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "not-used-by-the-fake")
        monkeypatch.setattr(extractor, "Anthropic", fake_anthropic(reply))
        monkeypatch.setattr(
            extractor, "resolve_target",
            lambda record, target, target_key="": (
                "SOURCE TEXT", FactSource(
                    doc_id="UBER_FY2024", kind="statement", ref="cash_flows",
                    target_key=target_key, pages=[1]),
            ),
        )
        cache = Cache(path=tmp_path / "probe_cache.db")
        record = types.SimpleNamespace(sha256="a" * 64, doc_id="UBER_FY2024")
        return cache, record

    def test_a_reply_that_is_not_json_is_named_not_left_to_the_parser(
            self, monkeypatch, tmp_path):
        cache, record = self._run(monkeypatch, tmp_path, self.REPLY)

        with pytest.raises(ExtractionError) as caught:
            extract(record, "statement:cash_flows", "what is CFO?", cache=cache)

        message = str(caught.value)
        assert "UBER_FY2024" in message, message
        assert "statement:cash_flows" in message, message
        # The reply itself, bounded. Enough to see WHAT came back, not so much
        # that a 16,000-token non-answer floods the terminal.
        assert self.REPLY[:60] in message, message
        assert len(self.REPLY) > 200
        assert self.REPLY[:201] not in message, "the reply is not truncated at 200"

    def test_nothing_malformed_is_cached(self, monkeypatch, tmp_path):
        """Same treatment as the max_tokens truncation. A cached non-answer is
        served silently forever after, and the second run looks like a cache
        hit rather than a failure."""
        cache, record = self._run(monkeypatch, tmp_path, self.REPLY)

        with pytest.raises(ExtractionError):
            extract(record, "statement:cash_flows", "what is CFO?", cache=cache)

        key = Cache.key(
            sha256=record.sha256,
            prompt_version=extractor.PROMPT_VERSION,
            model=extractor.DEFAULT_MODEL,
            target="statement:cash_flows",
            question="what is CFO?",
        )
        assert cache.get(key) is None

    def test_the_positive_control_still_parses(self, monkeypatch, tmp_path):
        """Without this, a wrapper that rejected EVERY reply would pass the
        two tests above."""
        good = json.dumps({"facts": [{
            "name": "Net cash provided by operating activities FY2024",
            "value": 7137.0,
            "unit": "USD millions",
            "period": "FY2024",
            "quote": "Net cash provided by operating activities 7,137",
        }]})
        cache, record = self._run(monkeypatch, tmp_path, good)

        accepted, rejected, cache_hit = extract(
            record, "statement:cash_flows", "what is CFO?", cache=cache)

        assert cache_hit is False
        assert len(accepted) + len(rejected) == 1
