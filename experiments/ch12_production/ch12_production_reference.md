# Aleph · Chapter 12 Reference — Production Engineering

> Fixed reference format. One per chapter. English. Read in 5 minutes, use forever.

---

## TL;DR

Course 1 was scripts; this is a system. Four things separate them: **async** (stop blocking on network waits — 4 concurrent calls finish in the time of the slowest, not the sum), **caching** (whose real value isn't cost but **reproducibility** — the same inputs must produce the same output, or a track record is just noise with dates on it), **graceful degradation** (a partial result that says what's missing beats a complete-looking result that silently isn't), and **cost as a design constraint** (a $2.50 analysis × 411 tickers is $1,027 — that's a business model, not a line item). All four are the same principle in different clothes: **contain the probabilistic part, make everything around it deterministic and observable.**

---

## Core concepts

**Async — what it actually does.** When code calls an API, it sits **blocked**, doing nothing, for 2–30 seconds while the network responds. Async releases the processor to start the next call instead of waiting; results are collected as they arrive. For a pipeline with 40 API calls at 3s each, that's 2 minutes of pure waiting versus a few seconds. (Analogy: a synchronous waiter takes table 1's order, stands in the kitchen until the food is ready, serves it, and only then goes to table 2. An async waiter takes every table's order, passes them all to the kitchen, and collects each dish when it's done — same waiter, same kitchen, ten times the throughput.)

**The distinction that matters: I/O-bound vs CPU-bound.** Async helps *only* when you're waiting on something else — network, disk, database. It does **nothing** for computation. Don't ask "is this operation heavy?" — ask **"who is doing the work: my processor, or another machine?"** If another machine, you're waiting, and async helps. If yours, it's busy, and there's nothing to release.

Applied to Aleph:
- **Benefits:** Claude API calls (extractor, analyst, critic) — pure network waiting.
- **No benefit:** DCF engine, M-Score, trend detection — pure Python computation.
- **Borderline (depends on implementation):** PDF extraction is disk read (I/O) plus parsing (CPU); locally the CPU dominates, but with OCR or an S3-hosted file it becomes I/O-bound. **Embeddings are the subtler case** — `all-MiniLM-L6-v2` running locally is CPU-bound and async gains nothing; the same logical operation via an OpenAI/Voyage API is I/O-bound and gains a lot. The right accelerator for local embeddings is **batching**, not async: `encode(list_of_chunks)` processes them in parallel internally, which Ch1 already did without framing it as an optimization.

**Caching — the reason is reproducibility, not cost.** Run an analysis in January, get a fair value of $420. Run it again in March on the *same filing with the same parameters*, get $395. The LLM is probabilistic; identical input doesn't guarantee identical output. **That destroys a track record** — you can't tell whether the thesis changed because reality moved or because the system is noisy, which makes learning from your own mistakes impossible. Caching makes the *pipeline* deterministic even though a component inside it isn't: the probabilistic step is confined to the first call, and everything after is replay. This is the same move as Ch9 (deterministic computation) and Ch8 (deterministic checks), now applied to the whole pipeline.

**The cache key must contain every input that affects the output** — model, prompt, temperature, max_tokens, document hash, parameters. **A partial key is worse than no cache**, because it returns stale answers confidently. Forget `temperature` and changing it won't invalidate; forget `document_hash` and an updated filing goes unnoticed.

**Graceful degradation.** When one of four companies fails mid-run, there are three possible behaviours and only one is right:
1. **Crash** — three minutes of work lost. Bad, but at least honest.
2. **Continue silently** — returns a "four-company analysis" built on three. **Fatal** — this is exactly the complete-looking-but-incomplete answer identified in Ch5 as the most dangerous failure.
3. **Partial result, marked** — "3 of 4 analyzed; GAMMA failed: rate limit; conclusions exclude it." **Correct.**

A production system doesn't promise to always succeed — it promises to **know what succeeded and say so**, the same contract as Ch8's `escalated` outcome.

**Retry with exponential backoff**, and the critical distinction of *what* to retry: `429` / `500` / timeout / connection errors are **transient** → retry. `401` (bad key) / `400` (malformed request) are **terminal** → five retries fail identically and only waste time. Delays double (1s, 2s, 4s) because if a server is overloaded, fifty clients retrying immediately make it worse; growing waits spread them out. **Circuit breaker**: after N consecutive failures, stop trying for a while — like an electrical breaker, disconnect to prevent damage rather than forcing current through a short. **Timeout every call** — without one, a hung request hangs the entire pipeline forever.

**Cost as a design constraint.** Three levers, in order of impact:
1. **Model routing (largest).** Structured tasks — schema extraction, classification, parsing — go to a small model; judgment tasks — criticism, inference, composition — go to a strong one. **The role separation done in Ch8 for quality reasons is what makes this saving possible.**
2. **Prompt caching** — sending the same 10-K as context ten times means paying for it ten times. Put the fixed part (the document) first and the variable part (the question) last.
3. **Batching** — non-urgent work (a nightly watchlist scan) runs at roughly half price via the Batch API.

**Budget as a hard stop, not a metric.** A loop bug that calls the API 10,000 times instead of 100 costs hundreds of dollars before anyone notices. `if run_cost > budget: raise BudgetExceeded` is a **safety breaker** — the same role as Ch8's hard revision ceiling.

---

## Code patterns learned

Cache key covering every output-affecting input:
```python
key = make_key(model=model, prompt=prompt, max_tokens=max_tokens, temperature=0)
canonical = json.dumps(components, sort_keys=True, default=str)   # stable ordering
return hashlib.sha256(canonical.encode()).hexdigest()
```

Resilient call — returns `None` on failure so one stage can't kill the pipeline, but budget always raises:
```python
except BudgetExceeded:
    raise                                     # hard stop, never swallowed
except Exception as e:
    if not is_retryable(e) or attempt == max_retries:
        ctx.record_failure(stage, str(e)[:120])
        return None                           # degrade, don't crash
    await asyncio.sleep(delay); delay *= 2    # exponential backoff
```

Concurrency plus failure isolation:
```python
results = await asyncio.gather(*[one(c) for c in companies], return_exceptions=True)
# gather fires all calls at once; return_exceptions keeps one failure from killing the rest
```

Log cached calls at zero cost so the saving is *measurable*, not assumed:
```python
log_cost(run_id, stage, model, 0, 0, was_cached=True)
```

---

## Evidence from the experiment (4 companies, Haiku, cold vs warm cache)

| | Run 1 (cold) | Run 2 (warm) |
|---|---|---|
| Elapsed | 3.52s | **0.06s** (59× faster) |
| Spend | $0.00069 | **$0.00000** |
| Succeeded | 4/4 | 4/4 |

- **Async proof:** four calls at roughly 3s each finished in 3.52s total. Serial execution would have taken ~12s — total time equals the *slowest* call, not the sum.
- **Reproducibility proof:** `outputs identical to run 1: True`. A probabilistic model would normally phrase run 2 differently; the cache made the pipeline deterministic. This is what lets a January-vs-March difference be attributed to *reality* rather than system noise.
- **Cost report by stage** showed `calls=2, cached=1` per company — the saving is measured, not assumed.
- Degradation never fired (4/4 succeeded), which means it's **untested**. A safety mechanism that hasn't been exercised is an assumption: force it with a tiny budget (`budget=0.0001`) and confirm `BudgetExceeded` stops everything.

---

## Gotchas / failure patterns

- **Async on CPU-bound work gains nothing.** Making the DCF engine `async` adds complexity and zero speed.
- **A partial cache key returns wrong answers confidently** — worse than having no cache at all.
- **Retrying terminal errors** (401, 400) wastes time and money; they fail identically every time.
- **Untested safety mechanisms are assumptions.** Deliberately trigger the budget breaker and the retry path.
- **SQLite chosen over Redis here** — it persists to disk with no server, which suits reproducibility (the cache survives restarts and can be backed up as a file). Redis is the upgrade for a distributed setup. *(Open issue.)*
- **`temperature=0` belongs in both the call and the key** — maximum determinism makes the cache meaningful.

---

## What this means for Aleph

Aleph is now production-shaped: concurrent where it waits, cached where it repeats, resilient where it can fail, and accounted for where it spends. The reproducibility guarantee is the piece that matters most for the long game — it's what makes a documented track record trustworthy, and what the Post-Mortem Engine needs to distinguish a changed thesis from a noisy system. Next steps: route structured stages (extractor) to Haiku and judgment stages (critic) to Sonnet, add prompt caching for the repeated filing context, and add LangSmith tracing so a failed run can be inspected step by step rather than guessed at.

---

## 60-second self-test

1. What question determines whether async will help a given stage — and why is "is it heavy?" the wrong question?
2. Local `all-MiniLM` embeddings: async or batching? Why?
3. What's the *primary* reason to cache in Aleph, and what does a missing key component cause?
4. Three ways a system can respond when one of four companies fails. Which is most dangerous, and why?
5. Why route the extractor and the critic to different models — and which earlier chapter made that possible?

<details>
<summary>Answers</summary>

1. "Who does the work — my processor or another machine?" If another machine, you're waiting and async helps; if yours, it's busy and there's nothing to release. Heaviness is irrelevant — a heavy local computation gains nothing.
2. Batching. Running locally makes it CPU-bound, so async gains nothing; `encode(list_of_chunks)` parallelizes internally.
3. Reproducibility — identical inputs must give identical outputs, or you can't tell a changed thesis from a noisy system, and the track record is worthless. A missing key component returns stale answers confidently.
4. Crash, continue silently, or return a marked partial result. Continuing silently is most dangerous: it produces a complete-looking analysis that is quietly incomplete — the Ch5 failure mode.
5. Structured extraction needs no judgment and runs fine on a small, cheap model, while criticism does. Ch8's role separation — built for quality — is what makes the cost saving possible.
</details>
