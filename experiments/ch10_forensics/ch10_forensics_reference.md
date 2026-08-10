# Aleph · Chapter 10 Reference — Forensic Accounting

> Fixed reference format. One per chapter. English. Read in 5 minutes, use forever.

---

## TL;DR

Chapter 9 built an engine that values a company *assuming the numbers are real*. This chapter asks the prior question: **are they?** A precise DCF on fabricated earnings is a precise wrong answer. The foundation is one line — **profit is an opinion, cash is a fact** — and the primary signal is the gap between them. On top of it sit three scores that answer three *different* questions (manipulation, bankruptcy, improvement), reported separately because merging them destroys the information in their combination. Language forensics adds a fourth angle: management can't lie in the numbers, but it can quietly change the wording.

---

## Core concepts

**Why profit ≠ cash, and why that's the opening for manipulation.** Accrual accounting records a December sale in December even if payment arrives in March — economically correct, since it reflects the period's actual activity. But the gap between "when recorded" and "when paid" (**accruals**) rests entirely on management *estimates*: when to recognize revenue, how much of receivables will go bad, over how many years to depreciate, how much to reserve for litigation. Each is a judgment call, and that's where manipulation lives. Revenue can be recognized early, depreciation stretched, reserves released — but **the cash in the bank can't be invented.**

**Accrual ratio — the core signal:**
```
accruals = (net income - operating cash flow) / total assets
```
Near zero = profit backed by cash. Large positive = reported profit didn't arrive as cash → red flag. Negative = usually healthy. Always **normalize by total assets** — a 500M gap is trivial at 200B and enormous at 2B. (Analogy: a friend who says he earns 500k a year but keeps asking for small loans — the reported figure doesn't match the behaviour.)

**Why it works over time:** accruals must **reverse**. Recognizing revenue early this year leaves next year short, so the manipulation must grow to sustain itself — until it breaks. **Large positive accruals several years running is one of the strongest signals there is.**

**Distinguishing a red flag from a business explanation.** A forensic analyst doesn't shout "fraud" at every anomaly:

| Explanation | Legitimate? | The deciding test |
|---|---|---|
| Rapid growth (cash tied up in receivables/inventory ahead of collection) | Yes | Do receivables grow *proportionally* to revenue? |
| Change in credit terms | Yes, once | Does the gap **stabilize** after a year? |
| Long-cycle business model (construction, enterprise software, defense) | Yes | Was it **always** this way, or did it **change**? |
| Non-cash charges (SBC, depreciation) push accruals negative | Yes | If accruals are still large positive despite these, the problem is worse than it looks |
| Early revenue recognition | **No** | Does DSO jump without explanation? |
| Deferred expenses / aggressive reserves | **No** | Did expenses fall with no operational change? |

The key word in the right column is ***change***. A stable anomaly is usually a business model; **a sudden one is what matters.** This is exactly why every tool in this chapter measures **year-over-year deltas, not absolute levels.**

**The three scores answer three different questions:**

| Score | Question | Direction | Threshold |
|---|---|---|---|
| **Beneish M** | Is management **inflating** the statements? | high = bad | `M > -1.78` flags |
| **Altman Z** | Is the company at risk of **bankruptcy**? | low = bad | `< 1.8` distress, `> 3.0` safe |
| **Piotroski F** | Is the financial position **improving**? | low = bad | `>= 7` strong, `<= 3` weak |

**Beneish M** is 8 indices, each a *ratio between two years* (1.0 = no change). Key ones: **DSRI** (receivables growing faster than sales — the "pushed sales" test), **AQI** (rising share of soft assets — a place to hide expenses), **DEPI** (depreciation slowing — stretched asset lives inflate profit), **TATA** (the accrual ratio). **TATA carries the largest coefficient (4.679) — the model itself says the accrual ratio is the strongest signal.**

**Piotroski embeds earnings quality:** one of its nine tests is `operating cash flow > net income`. Improvement not backed by cash isn't improvement — the same principle in a different tool.

**Why report them separately — never merge into one "quality score."** The three measure fundamentally different things, so their *combination* carries information a weighted average destroys. Low M + low Z is an honest company in trouble; high M + high Z is a stable company dressing up its numbers — an average would give both the same figure. **The most dangerous combination is high F + flagged M:** strong apparent improvement alongside manipulation signals suggests the improvement itself is accounting rather than operational — a buy signal that is actually a warning, with no external red flag. Correct output: **scores separately, plus a layer that interprets the combination** (and names which M component drove the flag).

**Language forensics.** Management doesn't rewrite MD&A each year — it edits last year's. Most text is identical, so **every change is deliberate.** And the asymmetry matters: **numbers must be accurate (legally), but language is free.** A management aware of an approaching problem can't lie in the figures, but it *can* quietly hedge the wording to cover itself. Three patterns:
- **Hedging** — rising "may / could / we believe / no assurance" → falling confidence.
- **Omission** — a topic that was central and vanished. **The strongest signal, because it's hardest to spot by hand — you don't notice what isn't written.**
- **Addition** — a new risk that wasn't there before.

Always normalize per 1000 words: a longer MD&A naturally contains more of everything, so raw counts manufacture false "increases."

---

## Code patterns learned

```python
def accrual_ratio(f) -> float:
    return (f.net_income - f.operating_cash_flow) / f.total_assets   # normalize by size

# Beneish indices are all curr/prev ratios - 1.0 means no year-over-year change
dsri = (curr.receivables / curr.revenue) / (prev.receivables / prev.revenue)
depi = dep_rate_prev / dep_rate_curr          # >1 means depreciation slowed
tata = (curr.net_income - curr.operating_cash_flow) / curr.total_assets
m = -4.84 + 0.920*dsri + 0.528*gmi + 0.404*aqi + 0.892*sgi + 0.115*depi \
    - 0.172*sgai + 4.679*tata - 0.327*lvgi

# Return components, not just the score - "which index drove it" is the actionable part
worst = max(components.items(), key=lambda kv: abs(kv[1] - 1.0))
```

Language forensics:
```python
def per_1000_words(count, text):      # normalize before comparing, always
    return count / len(normalize(text).split()) * 1000

# A term must appear >=3 times to count as "meaningfully present"
disappeared = {w: c for w, c in prev_terms.items() if c >= 3 and curr_terms.get(w, 0) == 0}
```

Test against synthetic companies with *known* profiles — a clean one must not flag, a manipulator must:
```python
assert not beneish_m_score(*clean_company())["flagged"]
assert beneish_m_score(*manipulator_company())["flagged"]
assert accrual_ratio(clean_curr) < 0 and accrual_ratio(manip_curr) > 0.05
```

---

## Evidence from the experiment (synthetic clean vs manipulator)

| | Clean | Manipulator |
|---|---|---|
| Accrual ratio | −0.029 (ok) | **+0.116 (red flag)** |
| Beneish M | −2.52 (clean) | **−0.75 (FLAGGED)** |
| Altman Z | 6.85 (safe) | **5.78 (safe)** |
| Piotroski F | 9/9 | 4/9 |

- The manipulator was built by changing only *deltas*: receivables 1200→2400 on 10% sales growth, cash flow 1100→300 while profit rose, depreciation 400→200. **All three were caught** — DSRI 1.818, AQI 1.628, DEPI 1.941 — while every clean-company component sat near 1.00.
- **The most instructive result: Altman Z rated the manipulator "safe" (5.78).** Z asks whether the company is going bankrupt, and it isn't — Z simply doesn't ask the relevant question. Looking at Z alone would have cleared it. This is the empirical case for keeping the scores separate: a merged score would have shown two nearly identical Z values and diluted the M signal. It's also the realistic profile of most known manipulations: large, stable companies trying to meet analyst expectations, not firms on the brink.
- Piotroski caught it too (4/9) — because of its `OCF > net income` test.

**Language forensics run:** the mechanism worked (hedging −62%, positive +316%, `cash`/`compensation` disappeared, `segment`/`adjustedebitda`/`headcount` appeared) — but the comparison was between **two sections of the same filing**, so the output has no forensic meaning. It detected a shift from accounting-policy prose to segment-performance prose. **A forensic tool always returns numbers; the validity of the comparison is the analyst's responsibility, not the tool's.**

---

## Gotchas / failure patterns

- **Always normalize before comparing** — accruals by total assets, word counts per 1000 words. Otherwise size differences masquerade as findings.
- **Comparing the wrong things still produces confident output.** Same-filing section comparison generated a dramatic-looking +316% that means nothing.
- **Never merge the three scores** into one number — it destroys the diagnostic value of their combination.
- **Absolute levels mislead; deltas inform.** A permanently high accrual ratio may be the business model; a sudden jump is the signal.
- **Beneish's threshold (−1.78) is statistical**, derived from the original sample — a flag is elevated *risk*, not proof.

---

## What this means for Aleph

Aleph gains a forensics layer that runs before valuation: every company gets an accrual ratio, three separately-reported scores, the M-Score component breakdown, and an interpretation of the combination. Wiring it up requires the Ch8 extractor to pull ~14 fields for two consecutive years (some scattered across pages), and language forensics requires the previous year's 10-K so the *same* section can be compared across filings. The ordering principle matters: **forensics gates valuation** — if earnings quality fails, the DCF is a precise answer to the wrong input.

---

## 60-second self-test

1. Why does accrual accounting create the opening for manipulation, and what's the single strongest signal?
2. Company shows rising profit with flat operating cash flow for three years. Give one legitimate explanation and the test that distinguishes it from manipulation.
3. Why do all Beneish indices measure ratios *between years* rather than levels?
4. The manipulator scored a "safe" Altman Z. What does that prove about reporting the scores separately?
5. Why is omission the strongest language-forensics signal, and what must be normalized before comparing MD&A across years?

<details>
<summary>Answers</summary>

1. Accruals rest on management estimates (revenue timing, bad-debt provisions, depreciation lives, reserves), all of which are judgment calls. The strongest signal is the accrual ratio — net income minus operating cash flow, normalized by total assets — because cash can't be invented.
2. Rapid growth ties up cash in receivables and inventory ahead of collection. The test: do receivables grow *proportionally* to revenue? Revenue +30% with receivables +30% is normal; revenue +10% with receivables +45% is a red flag.
3. Because a stable anomaly is usually the business model, while a sudden change is the actual signal. A ratio of 1.0 means no year-over-year change.
4. Z asks about bankruptcy risk, not honesty — it simply doesn't ask the relevant question. A merged score would have diluted the M-Score flag with two near-identical Z values, hiding the finding.
5. Because you don't notice what isn't written — a topic that was central and vanished is a deliberate decision that's nearly impossible to spot by hand. Normalize word counts per 1000 words, since a longer MD&A naturally contains more of everything.
</details>
