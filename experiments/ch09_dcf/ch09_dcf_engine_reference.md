# Aleph · Chapter 9 Reference — A Real DCF Engine

> Fixed reference format. One per chapter. English. Read in 5 minutes, use forever.

---

## TL;DR

A DCF engine fails silently: it runs, returns a clean number, and is wrong by 30%. The three classic silent killers are **numerator/denominator mismatch** (discounting FCFE at WACC, or bridging FCFE to equity — both double-count debt), **lazy WACC** (regression beta, book-value weights, country risk assigned by domicile rather than revenue exposure), and **terminal value** carrying most of the valuation on two assumptions. The fix is architectural: a deterministic, modular, *tested* engine where consistency guards make those errors raise exceptions instead of returning numbers. On top of it, a **sensitivity tornado** shows which assumption actually moves the answer, and a **reverse DCF** converts an estimation problem into a business-judgment one.

---

## Core concepts

**Numerator/denominator consistency.** The cash flow you discount must match who is entitled to it, and the discount rate must reflect *that* claimant's risk.

| | **FCFF** (Firm) | **FCFE** (Equity) |
|---|---|---|
| Belongs to | all capital providers (debt + equity) | shareholders only |
| Discount at | **WACC** | **Cost of Equity** |
| Yields | Enterprise Value | Equity Value directly |
| Bridge to equity | subtract net debt | already there |

FCFF is computed *before* interest, so discounting it at cost of equity understates the cost of debt; discounting FCFE (already net of interest) at WACC charges the debt cost **twice**. (Analogy: a rental property yielding 100k with a 30k mortgage — the 100k belongs to you *and* the bank (FCFF), the 70k belongs only to you (FCFE). Discounting the 70k at a rate that already prices the mortgage penalizes you twice for the same mortgage.) Default to FCFF — it's immune to capital-structure changes; use FCFE for banks and financials, where debt is raw material rather than financing.

**WACC — where it silently breaks:**
- **Regression beta is a trap** — noisy, reflects *historical* capital structure, meaningless for short histories or illiquid names. Use **bottom-up beta**: take the industry average, unlever `βU = βL / (1 + (1−t)·D/E)`, then relever to *this company's* structure. (Beta measures how sensitive the *business* is to the economy; leverage only amplifies it. Unlever = "how risky is the business itself"; relever = "now add this specific leverage.")
- **Country Risk Premium follows revenue, not domicile.** The question is "where does revenue come from?" not "where is it registered?" An Israeli defense company selling 70% to the US and Europe is mostly exposed to *those* markets. Weight CRP by revenue exposure. (Directly relevant for Israeli-market analysis.)
- **Use market-value weights, not book.** A company with 10B book debt and 200B market cap is barely levered; using 30B *book* equity gives D/E of 0.33 instead of 0.05 — inflating the debt weight sevenfold from one wrong line.

**Terminal value.** In a typical DCF, TV is 60–80% of total value — meaning the detailed forecast work drives only a third of the answer and two assumptions drive the rest. `g < 3%` is sacred because a terminal growth above long-run economy growth mathematically claims the company eventually *becomes* the economy — not optimistic, impossible. The danger is the **denominator** in `TV = FCF·(1+g)/(WACC−g)`: at WACC 8%, moving g from 2% → 4% halves the denominator and lifts value ~50%; 4% → 6% doubles it again. A two-point change in a seemingly innocent assumption can double the valuation.
**Forecast length is itself an assumption:** a longer, growth-heavy explicit period captures more value inside the forecast and pushes less into TV (this run: 10 years → TV was 57%, below the 60–80% rule of thumb; a 5-year forecast would push it past 75%). A longer forecast isn't necessarily more accurate, but it shifts weight to the part you actually reasoned about.
**Exit multiple** as an alternative is anchored to the market but assumes today's multiple holds in ten years — importing current market pricing into an intrinsic-value estimate. That's circular. Use it as a sanity check against Gordon, never as the primary method.

**Sensitivity tornado — and its trap.** Move one assumption at a time to its bounds, sort by swing width. It tells the analyst *which two* assumptions to argue about instead of debating eight. **But the result depends entirely on the ranges you set** — give a wide range to an unimportant assumption and it will look dominant. In this run `discount_rate` (7%→11%, a 4-point range) dominated while `terminal_growth` (1.5%→3%, a 1.5-point range) came last — the opposite of the theoretical sensitivity, purely because of range width. The reconciliation: **g is the most mathematically sensitive assumption (the denominator), but WACC carries the most practical uncertainty because it has no natural ceiling.** The tornado measures the second. Ranges must reflect genuine uncertainty, not convenience.

**Where ranges must come from.** If an LLM *picks* the ranges by judgment, the whole deterministic chain is fed by invention — an authoritative-looking tornado resting on made-up bounds (the Ch5 failure mode again). Ranges must be **derived**:

| Assumption | Range derived from | Source |
|---|---|---|
| `discount_rate` | bottom-up WACC across the industry beta 25th–75th percentile | computed |
| `terminal_growth` | capped by long-run nominal GDP, floored by inflation | economic constraint |
| `growth_rates` | the company's own historical growth dispersion (5–10y stdev) | filings |
| `base_cash_flow` | reported FCF → owner earnings adjusted for SBC and maintenance capex | filing |

The LLM's role is **extraction and selection, not invention**: which industry, which geographies (for CRP), what effective tax rate, which one-time items to normalize — all *text interpretation*. Python computes the ranges from those. Short form: **the LLM chooses what to measure; Python measures; the range comes from the data, not the model.** When no data supports a range, mark it `source: "analyst_judgment"` explicitly — transparent guessing beats a guess disguised as a calculation.

**Reverse DCF — the strongest tool in the chapter.** Instead of "what is it worth?" (which requires guessing g, the weakest input), ask **"what growth rate does the market price imply?"** You guess nothing; you extract the market's embedded assumption and then answer a far easier question: *is that expectation plausible?* This converts a valuation problem into a **business-judgment problem** — not "the value is 85" but "at this price the market prices 22% growth for a decade; has a company this size ever done that?" That's how Buffett and Munger actually think.

---

## Code patterns learned

Assumptions carry provenance — no bare numbers enter the engine (Ch6 grounding, applied to inputs):
```python
@dataclass
class Assumption:
    name: str; value: float
    source: Literal["filing", "market", "peer_group", "analyst_judgment"]
    rationale: str
```

Consistency guards turn the classic errors into exceptions:
```python
if inputs.terminal_growth >= inputs.discount_rate:   raise DCFConsistencyError(...)  # Gordon breaks
if inputs.terminal_growth > 0.03:                    raise DCFConsistencyError(...)  # exceeds the economy
if cash_flow_type == "FCFE" and net_debt != 0:       raise DCFConsistencyError(...)  # double counts debt
```

Report how much rests on the terminal value:
```python
terminal_pct = pv_terminal / total     # if this is 85%, the model is a guess about g with 10 years of decoration
equity = total - net_debt if cash_flow_type == "FCFF" else total
```

Reverse DCF by binary search — deterministic, no optimizer:
```python
low, high = -0.50, 1.00
for _ in range(max_iter):
    mid = (low + high) / 2
    v = value_at(mid)                                  # rebuild with uniform growth = mid
    if abs(v - market_price) < tolerance * market_price: return mid
    low, high = (mid, high) if v < market_price else (low, mid)
```

Test against closed-form cases whose answer is known in advance:
```python
# A flat no-growth perpetuity MUST equal CF / r
result = run_dcf(DCFInputs("FCFF", 100, [0.0], 0.0, 0.10, 0, 1))
assert abs(result.enterprise_or_equity_value - 1000) < 0.01
```

---

## Evidence from the experiment (illustrative inputs, 10-year forecast)

- **Terminal value = 57% of total** — below the 60–80% rule of thumb, because the explicit period was long and front-loaded with growth.
- **Tornado:** `discount_rate` swing 57.49 (73% of base) > `growth_rates_shift` 36.04 (46%) > `base_cash_flow` 23.02 (29%) > `terminal_growth` 10.62 (13%). The ordering is an artifact of range width, not of intrinsic sensitivity — the lesson of the chapter.
- **Reverse DCF:** at $75/share the model implies **7.5% annual growth for 10 years**, versus the 15%-declining path assumed in the forward run (which produced $79.13). Consistent, and it reframes the whole exercise: the question is no longer "is my WACC right?" but "is 7.5% sustained growth plausible for this business?"
- All three engine tests passed, including rejection of `g ≥ r` and of FCFE-plus-net-debt.

---

## Gotchas / failure patterns

- **The two-error compound.** Discounting post-interest cash flow at WACC *and* then subtracting net debt pushes value **down twice** — the errors don't offset. A great company gets flagged as expensive: a silent hallucination that makes you miss an opportunity, with no red flag. Guard 3 makes it impossible.
- **`deepcopy` in sensitivity loops.** Without it, one trial's mutation leaks into the next — a classic silent bug in sensitivity code.
- **Bounds that violate guards** should be *reported*, not crashed on — the tornado catches `DCFConsistencyError` and flags that row.
- **`eval` on model-supplied expressions** must be restricted (`{"__builtins__": {}}`); a real system uses a dedicated expression parser.
- **Illustrative ≠ valuation.** The demo inputs were not derived from the filing and were labelled as such in the code. An engine that runs is not a valuation; that requires the extractor feeding it verified figures.

---

## What this means for Aleph

The engine is deterministic, modular, and tested — the exact kind of tool Ch8 established as superior to free-form LLM reasoning. The next step closes the loop: the Ch8 extractor supplies verified, quoted figures (normalized owner earnings, diluted share count, effective tax rate, revenue geography), Python derives the assumption *ranges* from industry and company data, the engine runs, and the output is a **range plus a tornado plus the implied growth rate** — never a single authoritative-looking number. Every assumption carries its `source` and `rationale`, so an analyst can dispute one input specifically rather than rejecting the whole model.

---

## 60-second self-test

1. Why does discounting FCFE at WACC understate value, and why does also subtracting net debt make it worse rather than cancelling out?
2. What's wrong with regression beta, and what are the three steps of bottom-up beta?
3. Should an Israeli company with 70% US revenue carry Israel's country risk premium? Why?
4. Why did `terminal_growth` rank *last* in the tornado when theory says it's the most sensitive assumption?
5. Why is reverse DCF a better question than "what is it worth?"

<details>
<summary>Answers</summary>

1. FCFE is already net of interest, so WACC charges the debt cost a second time (value down). Subtracting net debt then removes debt a third time from what is already an equity value — both errors push the same direction, so they compound instead of offsetting.
2. It's noisy, reflects historical rather than current capital structure, and is meaningless for short histories. Bottom-up: industry average beta → unlever → relever to this company's D/E.
3. No — weight CRP by *revenue exposure*, not domicile. Most of its risk is US and European market risk.
4. Because the tornado measures swing across the ranges *you supply*, and terminal growth was given a 1.5-point range (it's capped at 3% by economic constraint) versus 4 points for WACC. g is the most mathematically sensitive; WACC has the most practical uncertainty because it has no natural ceiling.
5. It requires guessing nothing — it extracts the growth the market already prices, converting a valuation estimate into a business-judgment question you can actually answer from knowing the company.
</details>
