"""Prove on_target fires once per target and DURING the extract loop.

Counting callbacks cannot distinguish the two implementations that matter:
firing inside the loop and collecting everything to fire afterwards produce
the SAME number of calls with the SAME arguments in the SAME order. The
only observable difference is interleaving - whether extraction work for
target N+1 happens before or after target N's callback.

So the assertion is built on a single shared event log that BOTH the
stubbed extractor and the callback append to. During-loop execution
produces strict alternation (extract, callback, extract, callback);
batched execution produces all extractions followed by all callbacks. A
negative control at the bottom runs the same assertion against a
deliberately batched reference implementation and requires it to FAIL,
which is what proves the assertion has teeth rather than passing by
construction.

No API key, no cache and no PDFs: resolve_targets and extract are both
stubbed, so this runs anywhere the package imports.
"""
import sys

import aleph.valuation.pipeline as pipeline
from aleph.valuation.pipeline import TargetResult

# (key, target, question, required) - the shape resolve_targets returns.
# One skipped target in the middle, deliberately: a skipped target must
# still report, and must NOT reach the extractor.
FAKE_TARGETS = [
    ("cash_flows", "statement:cash_flows", "q1", True),
    ("segments", "UNRESOLVED:0", "q2", False),
    ("taxes", "note:11", "q3", True),
]

FAKE_FACTS = {
    "statement:cash_flows": (["f1", "f2", "f3"], ["r1"]),
    "note:11": (["f4", "f5"], []),
}


def install_stubs(events):
    """Point pipeline at fake targets and a spy extractor sharing one log."""
    def fake_resolve_targets(record):
        return list(FAKE_TARGETS)

    def fake_extract(record, target, question, target_key=""):
        events.append(f"extract:{target_key}")
        accepted, rejected = FAKE_FACTS[target]
        return accepted, rejected, True

    pipeline.resolve_targets = fake_resolve_targets
    pipeline.extract = fake_extract


def assert_interleaved(events):
    """Require extract and callback to alternate, per target, in order.

    This is the assertion that separates during-loop from batched. It reads
    the log as pairs and requires each extraction to be followed immediately
    by ITS OWN callback - not merely by some callback, and not by the next
    target's extraction.
    """
    expected = [
        "extract:cash_flows", "callback:cash_flows",
        "callback:segments",                     # skipped: reports, never extracts
        "extract:taxes", "callback:taxes",
    ]
    if events != expected:
        raise AssertionError(
            f"event order differs\n  expected: {expected}\n  actual:   {events}"
        )


def test_callback_fires_during_the_loop():
    events = []
    install_stubs(events)
    seen = []

    def on_target(target_result):
        events.append(f"callback:{target_result.key}")
        seen.append(target_result)

    facts, rejected = pipeline.extract_facts(object(), on_target=on_target)

    assert_interleaved(events)
    assert len(seen) == 3, seen
    assert [t.key for t in seen] == ["cash_flows", "segments", "taxes"], seen
    assert facts == ["f1", "f2", "f3", "f4", "f5"], facts
    assert rejected == ["r1"], rejected
    print("PASS test_callback_fires_during_the_loop")


def test_skipped_target_reports_but_does_not_extract():
    events = []
    install_stubs(events)
    seen = []
    pipeline.extract_facts(object(), on_target=seen.append)

    skipped = [t for t in seen if t.skipped]
    assert len(skipped) == 1, seen
    assert skipped[0].key == "segments", skipped
    assert skipped[0].accepted == 0 and skipped[0].rejected == 0, skipped
    assert "extract:segments" not in events, events
    print("PASS test_skipped_target_reports_but_does_not_extract")


def test_counts_reach_the_callback():
    seen = []
    install_stubs([])
    pipeline.extract_facts(object(), on_target=seen.append)

    by_key = {t.key: t for t in seen}
    assert (by_key["cash_flows"].accepted, by_key["cash_flows"].rejected) == (3, 1)
    assert (by_key["taxes"].accepted, by_key["taxes"].rejected) == (2, 0)
    print("PASS test_counts_reach_the_callback")


def test_no_callback_is_not_an_error():
    install_stubs([])
    facts, rejected = pipeline.extract_facts(object())
    assert facts == ["f1", "f2", "f3", "f4", "f5"], facts
    assert rejected == ["r1"], rejected
    print("PASS test_no_callback_is_not_an_error")


def test_rejections_are_returned_not_dropped():
    """A rejection the caller never sees is a gate that fired invisibly.

    The stub rejects exactly one fact, on one target. Returning [] here
    would still pass every other test in this file, because nothing else
    reads the second return value.
    """
    install_stubs([])
    facts, rejected = pipeline.extract_facts(object())
    assert rejected == ["r1"], rejected
    assert "r1" not in facts, facts     # rejected facts never reach a derivation
    print("PASS test_rejections_are_returned_not_dropped")


def test_batched_implementation_fails_this_assertion():
    """Negative control: the assertion must REJECT a batched implementation.

    Without this, assert_interleaved could be passing because it is weak
    rather than because the code is right. This reproduces the exact
    mistake the callback exists to prevent - collect every target, then
    report - and requires the assertion to catch it.
    """
    events = []
    install_stubs(events)
    collected = []

    def batched_extract_facts(record, on_target=None):
        facts, rejected_all, results = [], [], []
        for key, target, question, required in pipeline.resolve_targets(record):
            if target.startswith("UNRESOLVED"):
                results.append(TargetResult(key=key, target=target, skipped=True))
                continue
            accepted, rejected, _ = pipeline.extract(
                record, target, question, target_key=key
            )
            results.append(TargetResult(
                key=key, target=target, skipped=False,
                accepted=len(accepted), rejected=len(rejected),
            ))
            facts.extend(accepted)
            rejected_all.extend(rejected)
        for target_result in results:      # the bug: reporting after the loop
            if on_target:
                on_target(target_result)
        return facts, rejected_all

    def on_target(target_result):
        events.append(f"callback:{target_result.key}")
        collected.append(target_result)

    batched_extract_facts(object(), on_target=on_target)

    # Same call count, same arguments, same relative order of each kind -
    # and still wrong, which is the whole point.
    assert len(collected) == 3, collected
    assert [t.key for t in collected] == ["cash_flows", "segments", "taxes"]

    try:
        assert_interleaved(events)
    except AssertionError:
        print("PASS test_batched_implementation_fails_this_assertion")
        return
    raise AssertionError(
        "assert_interleaved accepted a batched implementation; the "
        "during-loop assertion proves nothing"
    )


if __name__ == "__main__":
    test_callback_fires_during_the_loop()
    test_skipped_target_reports_but_does_not_extract()
    test_counts_reach_the_callback()
    test_no_callback_is_not_an_error()
    test_rejections_are_returned_not_dropped()
    test_batched_implementation_fails_this_assertion()
    print("\nAll tests passed.")
