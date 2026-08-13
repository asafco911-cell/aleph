"""Resilient, cached, cost-tracked wrapper around the Anthropic API."""
import asyncio
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional, List
from dotenv import load_dotenv
from anthropic import AsyncAnthropic

from cache_layer import make_key, cache_get, cache_set, log_cost, cost_report

load_dotenv()
client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Errors worth retrying vs errors that will fail identically every time
RETRYABLE = ("rate_limit", "overloaded", "timeout", "connection", "500", "529")


class BudgetExceeded(RuntimeError):
    """Hard stop - a runaway loop must not silently spend hundreds of dollars."""


@dataclass
class RunContext:
    """Tracks one analysis run: its id, budget, and what failed along the way."""
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    budget_usd: float = 1.00
    spent_usd: float = 0.0
    failures: List[dict] = field(default_factory=list)

    def charge(self, amount: float):
        self.spent_usd += amount
        if self.spent_usd > self.budget_usd:
            raise BudgetExceeded(
                f"run {self.run_id} spent ${self.spent_usd:.4f}, budget ${self.budget_usd:.2f}")

    def record_failure(self, stage: str, error: str):
        """Partial results are fine. Silent partial results are not."""
        self.failures.append({"stage": stage, "error": error})


def is_retryable(err: Exception) -> bool:
    msg = str(err).lower()
    return any(token in msg for token in RETRYABLE)

async def call_claude(ctx: RunContext, stage: str, prompt: str,
                      model: str = "claude-sonnet-4-5",
                      max_tokens: int = 1000,
                      max_retries: int = 3,
                      timeout_s: float = 60.0) -> Optional[str]:
    """One resilient call. Returns None on unrecoverable failure - never raises
    for a single stage, so the pipeline can degrade gracefully."""

    # Every input that affects the output must be in the key
    key = make_key(model=model, prompt=prompt, max_tokens=max_tokens, temperature=0)

    cached = cache_get(key)
    if cached is not None:
        log_cost(ctx.run_id, stage, model, 0, 0, was_cached=True)
        return cached["text"]

    delay = 1.0
    for attempt in range(1, max_retries + 1):
        try:
            resp = await asyncio.wait_for(
                client.messages.create(
                    model=model, max_tokens=max_tokens, temperature=0,
                    messages=[{"role": "user", "content": prompt}],
                ),
                timeout=timeout_s,
            )
            text = resp.content[0].text
            cost = log_cost(ctx.run_id, stage, model,
                            resp.usage.input_tokens, resp.usage.output_tokens,
                            was_cached=False)
            ctx.charge(cost)                      # may raise BudgetExceeded
            cache_set(key, {"text": text})
            return text

        except BudgetExceeded:
            raise                                  # budget is a hard stop, never swallowed
        except Exception as e:
            if not is_retryable(e) or attempt == max_retries:
                ctx.record_failure(stage, f"{type(e).__name__}: {str(e)[:120]}")
                return None
            await asyncio.sleep(delay)
            delay *= 2                             # exponential backoff spreads retries out
    return None

async def analyze_companies(companies: List[str], budget: float = 1.00) -> dict:
    """Run several companies CONCURRENTLY. Failures are recorded, not fatal."""
    ctx = RunContext(budget_usd=budget)
    t0 = time.time()

    async def one(name: str):
        prompt = (f"In one sentence, what is the main business risk facing "
                  f"a ride-hailing company named {name}? Answer generically.")
        text = await call_claude(ctx, stage=f"analyze:{name}", prompt=prompt,
                                 model="claude-haiku-4-5", max_tokens=150)
        return name, text

    # gather runs them all at once instead of one after another
    results = await asyncio.gather(*[one(c) for c in companies], return_exceptions=True)

    succeeded, failed = {}, []
    for r in results:
        if isinstance(r, Exception):
            failed.append(str(r)[:120])
            continue
        name, text = r
        if text is None:
            failed.append(name)
        else:
            succeeded[name] = text

    return {"run_id": ctx.run_id, "elapsed_s": time.time() - t0,
            "spent_usd": ctx.spent_usd, "succeeded": succeeded,
            "failed": failed, "failures": ctx.failures}

if __name__ == "__main__":
    companies = ["ALPHA", "BETA", "GAMMA", "DELTA"]

    print("=" * 70)
    print("RUN 1 - cold cache")
    print("=" * 70)
    r1 = asyncio.run(analyze_companies(companies))
    print(f"  run_id   : {r1['run_id']}")
    print(f"  elapsed  : {r1['elapsed_s']:.2f}s")
    print(f"  spent    : ${r1['spent_usd']:.5f}")
    print(f"  succeeded: {len(r1['succeeded'])}/{len(companies)}")
    if r1["failed"]:
        print(f"  FAILED   : {r1['failed']}   <-- reported, not hidden")

    print("\n" + "=" * 70)
    print("RUN 2 - warm cache (identical inputs)")
    print("=" * 70)
    r2 = asyncio.run(analyze_companies(companies))
    print(f"  elapsed  : {r2['elapsed_s']:.2f}s")
    print(f"  spent    : ${r2['spent_usd']:.5f}")

    identical = all(r1["succeeded"].get(c) == r2["succeeded"].get(c) for c in companies)
    print(f"  outputs identical to run 1: {identical}   <-- reproducibility")

    print("\n" + "=" * 70)
    print("COST REPORT (all runs)")
    print("=" * 70)
    rep = cost_report()
    print(f"  total spend: ${rep['total_usd']:.5f}")
    for row in rep["by_stage"][:6]:
        print(f"    {row['stage']:<20} calls={row['calls']:<3} "
              f"cost=${row['cost']:.5f}  cached={row['cached']}")