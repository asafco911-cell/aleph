# Aleph · Chapter 5 Reference — RAG Evaluation

> Fixed reference format. One per chapter. English. Read in 5 minutes, use forever.

---

## TL;DR

You can't improve what you can't measure. Testing a RAG system with one hand-picked question is an anecdote, not a measurement — the same way one winning trade doesn't validate a strategy. Evaluation is the backtest of a RAG system: a golden dataset of verified Q&A, numeric metrics, and A/B comparison. A RAG answer can fail in two independent places — **retrieval** (wrong chunks came back) or **generation** (right chunks, bad answer) — so you measure each separately. RAGAS splits "is the answer good?" into four 0–1 scores: two for retrieval (Context Precision, Context Recall), two for generation (Faithfulness, Answer Relevancy). This is what separates an engineer ("Recall went 0.64 → 0.85 on 30 questions") from an amateur ("feels better").

---

## Core concepts

**Why one question isn't enough — three problems:** (1) a sample of one is an anecdote — you might have picked a question the weak system happens to answer well; (2) "good" in free-form text is subjective — a human has a vague feeling, a computer needs a number; (3) the invisible failure — an answer can *sound* perfect while the number is fabricated, and you'll never catch it without systematic checking. (Analogy: validating a trading strategy on one trade vs a backtest over hundreds, with win rate / profit factor / drawdown.)

**Two failure locations, measured separately:**
- **Retrieval failed** — wrong chunks retrieved. Even a perfect LLM can't answer from irrelevant material (garbage in, garbage out). Fix: chunking / hybrid.
- **Generation failed** — right chunks, but the LLM ignored them, hallucinated, or answered the wrong thing. Fix: prompt / grounding.
Knowing *where* it broke is essential because the fix is completely different. One combined "is it good?" score can't tell you.

**The four RAGAS metrics (0–1 each):**
- **Context Precision (retrieval)** — of the chunks we retrieved, how many are actually relevant? (Only fish in the net, not seaweed.) Low if we drag in noise.
- **Context Recall (retrieval)** — of what we *needed*, how much did we retrieve? (Did every needed fish get caught?) Low if something important was left out.
- **Faithfulness (generation)** — is every claim in the answer supported by the retrieved context, or invented? This is the hallucination metric — turns "I think it made that up" into a *number*. Most critical for Aleph.
- **Answer Relevancy (generation)** — does the answer actually address the question? An answer can be faithful (no hallucination) yet off-topic.

**Precision ↔ Recall tension** = the top-k dilemma (Ch4): raise recall by retrieving *more* chunks (better coverage) but precision drops (more noise enters). RAGAS lets you measure both sides.

**The most dangerous failure: high Context Recall + low Faithfulness.** We gave the LLM all the right info and it hallucinated anyway. It's the worst because it's *invisible* — retrieval failures and irrelevant answers look wrong and get discarded; a confident, focused, numeric answer with a fabricated number looks exactly like a great answer, and an analyst puts money on it. This is why every number in Aleph needs a page citation — Faithfulness is what turns that principle from a wish into a measurement.

**Golden dataset** — the answer key. Each entry: the question, a manually verified `ground_truth`, the `source_pages` (correct context), and a `question_type` tag. It's the anchor of all measurement — if it's wrong, every score is wrong, so verify each answer against the actual filing. Quality > quantity (30 precise > 100 sloppy). Cover types: direct_lookup, reasoning ("why"), comparative (needs decomposition), and **trap** questions (answer not in the doc). The trap is the cleanest hallucination detector: there's no "right number" it could give, so *any* numeric answer is a fail — it tests whether the system invents to satisfy at all costs, without you needing to know the answer in advance.

**LLM-as-a-Judge** — score free-form answers by giving a strong LLM the question, answer, and ground_truth and asking it to grade. The obvious worry — "if LLMs hallucinate, why trust an LLM judge?" — is answered by: **verifying is easier than generating.** Checking whether a given answer is supported by given context is a focused verification task, not open creation, so it's far more reliable (like checking a solution vs solving from scratch). Not perfect, but it makes measurement possible and reliable enough. Pitfalls: the judge is strict about what's *literally* in the context, and the bar is a decision you set.

**A/B test — the payoff.** Run the whole golden dataset through System A (dense only, Ch3) and System B (hybrid + rerank, Ch4); compare metric averages. "Recall 0.64 → 0.85, Faithfulness 0.71 → 0.89 over 30 questions" *proves* the improvement. Good measurement isn't one number — it's a breakdown by `question_type` (like a backtest split by market regime), so you know *where* B wins. From here, every pipeline change (chunk size, embedding model, k, prompt) is measured against the golden dataset: change → measure → compare → decide. Development becomes a measured improvement loop, not guessing in the dark.

---

## Code patterns learned

```python
# LLM-as-a-judge for faithfulness: give question context + answer, get a 0-1 score
def judge_faithfulness(answer, context):
    prompt = f"""Score whether every claim in the ANSWER is supported by the CONTEXT.
CONTEXT:\n{context}\nANSWER:\n{answer}
Return ONLY JSON: {{"score": <0.0-1.0>, "reason": "<short>"}}. Start with {{ end with }}."""
    raw = client.messages.create(model="claude-sonnet-4-5", max_tokens=300,
              messages=[{"role": "user", "content": prompt}]).content[0].text.strip()
    start, end = raw.find("{"), raw.rfind("}")          # Ch4 robustness layer
    return json.loads(raw[start:end+1])
```

Golden dataset entry shape:
```json
{ "question": "...", "ground_truth": "...", "source_pages": [60], "question_type": "direct_lookup" }
```

---

## Gotchas / failure patterns

- **Faithfulness measures loyalty to the context you gave, not absolute truth.** A factually correct answer ("Uber Freight...") scored 0.5 because the context passed to the judge said only "Freight revenue..." without "Uber" — the judge was *right* to flag an unsupported leap. This is a feature: a thin context penalizes even a true answer, which forces retrieval to supply *complete* context (directly linking to Context Recall). Fix: give the judge richer context → score rose to ~1.0.
- **Reading a score is a skill.** A low score can mean (a) the system is bad, (b) the context you fed was thin, or (c) the judge is being correctly strict. Don't conclude "system bad" — ask *why* the score is what it is.
- **The judge's bar is your decision.** Tighten or loosen the definition in the prompt to match how much reasonable inference you want to allow.
- **LLM judge output** still needs the Ch4 parse-defense (extract JSON from `{` to `}`).

---

## What this means for Aleph

Aleph now has the beginning of an automatic evaluation harness: a golden dataset and a working numeric hallucination detector. Extend it to all four metrics (one judge each) and wire the A/B test. From now on, no pipeline change ships on vibes — it ships because the metric moved the right way on the golden set, broken down by question type. This is the layer that makes every later improvement provable, and it's the discipline that turns Aleph from a demo into an engineered system.

---

## 60-second self-test

1. Why is testing with one question an anecdote, not a measurement? (Trading analogy.)
2. Name the two independent failure locations in a RAG answer and one metric for each.
3. Why is high-Recall + low-Faithfulness the most dangerous failure of all four?
4. Why is a trap question (answer not in the doc) the cleanest hallucination test?
5. Why can we trust an LLM to judge answers when LLMs hallucinate?

<details>
<summary>Answers</summary>

1. A single question might be one the weak system happens to handle well (luck/specific setup); only a broad sample shows average, consistent performance — like backtesting a strategy over hundreds of trades, not one.
2. Retrieval (Context Precision / Context Recall) and generation (Faithfulness / Answer Relevancy).
3. It's invisible: the answer sounds confident, focused, and numeric — looks like a great answer — but the number is fabricated, so an analyst acts on it. Other failures look wrong and get discarded.
4. There's no correct number it could give, so any numeric answer is automatically a fail; it tests the invent-to-please tendency without needing to know the answer in advance.
5. Verifying (checking whether an answer is supported by given context) is an easier, focused task than generating — so the judge is far more reliable at grading than at authoring.
</details>
