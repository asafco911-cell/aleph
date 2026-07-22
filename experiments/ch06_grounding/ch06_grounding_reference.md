# Aleph · Chapter 6 Reference — Structured Generation & Advanced Grounding

> Fixed reference format. One per chapter. English. Read in 5 minutes, use forever.

---

## TL;DR

Course 1 said "use Pydantic and tell it to answer only from the source." That's *asking*. This chapter is about *forcing*. Constrained decoding makes malformed output mechanically impossible instead of merely discouraged. Citation-first generation exploits the left-to-right nature of LLMs: put the evidence *before* the claim in the output schema, so the source shapes the claim instead of the claim shopping for a source. Self-consistency and chain-of-verification then attack what grounding alone can't catch — a real quote followed by an invalid inference. And any actual arithmetic leaves the model entirely and runs in Python, because verification techniques are probabilistic while Python is deterministic.

---

## Core concepts

**Asking vs forcing.** A prompt instruction ("Return JSON") is a *soft* constraint — the model is probabilistic, so it complies almost always, not always (see Ch4's `JSONDecodeError`). A *hard* constraint changes the generation mechanics so violation is impossible. (Analogy: a "don't cross on red" sign vs a physical barrier.)

**How constrained decoding works.** An LLM emits one token at a time, assigning a probability to every token in its vocabulary at each step. Constrained decoding **zeroes out the probability of any token that would break the target structure** at that position — after `{"score":` only a number or space is legal, so letters become unselectable. The model *physically cannot* emit broken JSON. Contrast with Ch4's fix, which sliced valid JSON out of the output *after* the model already erred: that's a bandage, this is prevention.
- **Why the Ch4 fix is weaker:** it assumes intact JSON exists somewhere in the output. If the model never closed the bracket (e.g. hit `max_tokens`), `find` returns −1 and there's nothing to salvage. Worse, it can *silently succeed on garbage* — output like `"I'm not sure, but [1,2] might help — ignore that"` slices cleanly to `[1,2]`, parses fine, and the pipeline proceeds on data the model itself disclaimed. **Silent failures are more dangerous than loud ones** (same lesson as Ch5's faithfulness).

**Citation-first generation.** Why "answer only from the source" fails: in the layout `Claim … [Source: p60]`, the model writes the claim *first*, so the citation is post-hoc justification — it hunts for a source that fits what it already said, and invents a page number if none fits. Reversing the order (`Evidence: "<exact quote>" [c29]` → `Claim: …`) means the exact source sits in the context *while the claim tokens are being generated*. The mechanism is the same in both directions — **whatever comes first shapes what comes after** — we just choose which one comes first. Output order is an engineering decision, not a formatting one.

**Enforcing it with a schema.** Pydantic field order = generation order. Declaring `evidence_quote` before `claim` forces citation-first structurally rather than asking for it in the prompt. `instructor` wraps the API call, translates the Pydantic model into an enforced tool schema, validates the response, and auto-retries on violation. Not token-level constrained decoding (that needs local model access) but API-level enforcement — less hermetic, fully practical.

**What grounding still can't prevent — the quote→claim gap.** Citation-first guarantees the *evidence is real* (and verbatim quoting means you can verify it programmatically with a substring check), but not that the *inference is valid*. Three leaks:
- **Bad interpretation** — quote says "decreased 1%", claim says "collapsed, signaling structural decline."
- **Bad arithmetic** — quote gives $25,111M and $21,002M, claim says "grew 30%" (actually ~19.6%). The model did mental math and got it wrong.
- **Irrelevant-but-real quote** — a genuine sentence that merely *looks* related, decoration disguised as evidence.

**Self-consistency.** Run the same query N times; the model is probabilistic, so answers vary. High agreement (5/5 say "1%") → likely read from the material. Disagreement (1%, 15%, "collapsed") → red flag, the model is guessing. Beyond filtering errors, this yields a **confidence measure** — "answer X, 5/5 agreement" vs "3/5, treat with caution" — which for an analyst is worth nearly as much as the answer. (Analogy: polling five analysts independently.)
- **Its blind spot:** the model can be *consistently wrong*. If it's convinced the growth is 30%, all five runs say 30% — 5/5 agreement on a wrong number. **Consistency is not correctness.**

**Chain-of-verification.** Four steps: (1) generate the grounded answer; (2) plan verification questions ("does this quote exist in the chunk? is 19.6% correct? is 'collapsed' justified for 1%?"); (3) execute each check separately against the source; (4) revise. It works for the Ch5 reason — **verifying is easier than generating**: producing an answer juggles relevance, phrasing, and completeness at once, while checking one claim against one source is narrow and easy. The gain comes from *separating the roles*, not from the model getting smarter. Same judge idea as Ch5, different use: there it *measured* faithfulness, here it *corrects* inline.

**The two are complementary:** self-consistency catches *wobbling* (a sign of guessing); chain-of-verification catches *confidently wrong*.

**The hard boundary — arithmetic leaves the model.** Every verification technique above (self-consistency, CoVe, LLM-as-judge) is *probabilistic*: it raises the catch rate from 70% to 95% to 99%, but a tail always remains. `(25111 - 21002) / 21002` in Python is *deterministic* — same input, same output, always. You don't reduce computational hallucination risk, you **eliminate** it, by taking the computation out of the model's hands. This is Ch3's boundary again: approximate is fine for *finding*, forbidden for *computing*. Retrieval may be probabilistic; generation may be probabilistic-with-verification; the moment there's a number, it runs in Python.

---

## Code patterns learned

```python
import instructor
from pydantic import BaseModel, Field
from typing import List

client = instructor.from_anthropic(Anthropic(api_key=...))

class GroundedClaim(BaseModel):
    # Field ORDER is the enforcement: evidence is generated before the claim
    evidence_quote: str = Field(description="Exact sentence copied verbatim from the source context.")
    source_chunk_id: str = Field(description="Id of the chunk the evidence came from, e.g. 'c29'.")
    claim: str = Field(description="Claim derived ONLY from the evidence quote above.")

class GroundedAnswer(BaseModel):
    claims: List[GroundedClaim]     # claims before summary — summary derives from them
    summary: str

result = client.messages.create(
    model="claude-sonnet-4-5", max_tokens=1000,
    response_model=GroundedAnswer,       # <-- schema enforcement; no json.loads, no slicing
    messages=[{"role": "user", "content": prompt}],
)
```

Programmatic verification the schema enables:
```python
assert claim.evidence_quote in chunks[claim.source_chunk_id]   # quote must literally exist
```

---

## Evidence from the experiment (Uber, 2 chunks, "What happened to Freight revenue and profitability?")

- Both claims cited `[c29]` with the quote copied **verbatim** — not paraphrased, so it's substring-verifiable.
- Every number in the claims ($42M, 1%, $41M, 55%) appears in the quote. Nothing materialized from nowhere.
- The model produced **atomic claims** (one on revenue, one on profitability) from the same chunk rather than one vague blended claim — atomic claims are independently verifiable, which is what makes per-claim faithfulness scoring possible.
- `c21` (the Mobility table) was supplied but **never used** — no padding with irrelevant numbers to look thorough. Healthy grounding. (Note this means Context Precision was low — an unneeded chunk was retrieved — while generation handled it correctly: the Ch5 retrieval/generation separation in action.)
- No `json.loads`, no slicing, no post-hoc cleanup: all Ch4 bandages became unnecessary because the structure was enforced up front.

---

## Gotchas / failure patterns

- **`instructor` installs a `rich` version bump** and warns about `instructor.exe` not on PATH — cosmetic, ignore.
- **Verbatim ≠ paraphrase.** Demand exact copying in the field description; paraphrase reopens the distortion door and breaks substring verification.
- **A schema guarantees structure, not truth.** Perfect JSON with a fabricated number is still a hallucination — structure and grounding are separate problems.
- **Don't read high self-consistency as correctness.** Consistent-and-wrong is a real failure mode.

---

## What this means for Aleph

Aleph's generation layer now *forces* grounding rather than requesting it: every claim carries a verbatim quote and a chunk id, so every number traces to a specific sentence on a specific page — the grounding an analyst actually needs. Next layer: add programmatic quote verification (substring assert), self-consistency for a confidence score, and chain-of-verification for the inference step. And the standing rule that outranks all of them — **any arithmetic runs in Python, never in the model's head.**

---

## 60-second self-test

1. What's the mechanical difference between constrained decoding and Ch4's "slice from `[` to `]`" fix?
2. Why is a citation placed *after* a claim effectively decoration? Answer in terms of token-by-token generation.
3. Citation-first guarantees the evidence is real. Name two things it still doesn't guarantee.
4. What does self-consistency measure, and what's its blind spot?
5. Why is running the math in Python categorically better than any LLM verification technique?

<details>
<summary>Answers</summary>

1. Constrained decoding zeroes the probability of structure-breaking tokens *during* generation, so malformed output can't be produced; the Ch4 fix repairs output *after* the error, assumes intact JSON exists, and can silently succeed on garbage.
2. The model generates left to right, so each token is conditioned on what precedes it. With the claim first, the citation is conditioned on the claim — chosen to fit it. With evidence first, the claim is conditioned on the real source.
3. That the inference from quote to claim is valid (interpretation can be exaggerated) and that any arithmetic derived from the quote is correct.
4. Agreement across repeated runs — a confidence signal. Blind spot: the model can be consistently wrong, giving 5/5 agreement on a false answer.
5. All LLM verification is probabilistic (a tail of missed errors always remains); Python arithmetic is deterministic, eliminating computational hallucination rather than reducing it.
</details>
