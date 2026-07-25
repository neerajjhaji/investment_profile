# ArthaLab — Complete Application Documentation

A full user + developer manual for the **ArthaLab Investment Strategy &
Portfolio Simulator**, with runnable code examples and real output.

> ⚠️ **Educational tool, not advice.** ArthaLab is a mathematical modelling and
> scenario-simulation tool for the Indian financial ecosystem. It is **not** a
> SEBI Registered Investment Adviser and recommends nothing. Every number below
> is a hypothetical result of user-supplied assumptions.

Companion docs: **[README.md](README.md)** (quick start) ·
**[GUIDE.md](GUIDE.md)** (key/code/parameter reference).

---

## Table of contents

1. [What ArthaLab does](#1-what-arthalab-does)
2. [Core concepts (read this first)](#2-core-concepts-read-this-first)
3. [Installation & configuration](#3-installation--configuration)
4. [Using the Streamlit app (walkthrough)](#4-using-the-streamlit-app-walkthrough)
5. [Using the math engine in code](#5-using-the-math-engine-in-code)
6. [Using the Gemini AI service in code](#6-using-the-gemini-ai-service-in-code)
7. [Using the FastAPI backend](#7-using-the-fastapi-backend)
8. [End-to-end worked example](#8-end-to-end-worked-example)
9. [Extending the application](#9-extending-the-application)
10. [Testing](#10-testing)
11. [Troubleshooting](#11-troubleshooting)
12. [Glossary](#12-glossary)

---

## 1. What ArthaLab does

ArthaLab lets you build a **hypothetical Indian retirement/income portfolio**
and see the arithmetic and risks, cleanly separating two very different things:

| Bucket | Instruments | Nature |
|--------|-------------|--------|
| **Fixed income** | POMIS, SCSS, RBI FRSB, bank/corporate FDs, low-duration debt funds | Guaranteed-style, slab-taxed interest |
| **Market-linked** | Equity via a Systematic Withdrawal Plan (SWP) | **Not** guaranteed; subject to sequence-of-returns risk |

It computes post-tax monthly cash flow, runs a **sequence-of-returns stress
test** and a **Monte Carlo** simulation on the SWP bucket, and can ask Google
Gemini to *explain* (never recommend) the mechanics, taxation, and risks.

---

## 2. Core concepts (read this first)

- **SWP is not income.** A Systematic Withdrawal Plan redeems fund units each
  month. In a down month you sell *more* units for the same rupees, which can
  permanently shrink the corpus. ArthaLab never labels this "yield."
- **Sequence-of-returns risk.** Two portfolios with the *same average* return
  can end very differently depending on *when* the bad years hit. Early crashes
  hurt far more when you are withdrawing. The stress test makes this visible.
- **Statutory limits are enforced, not silently worked around.** If you request
  more POMIS than the ceiling, the engine caps it and *tells you* about the
  overflow — it never quietly moves your money elsewhere.
- **Every rate is an assumption you control.** Defaults are documented but
  editable; garbage-in produces garbage-out *on purpose*, so you can see how
  sensitive the outcome is to your inputs.

---

## 3. Installation & configuration

```bash
# 1. Clone
git clone https://github.com/neerajjhaji/investment_profile.git
cd investment_profile

# 2. Virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Dependencies
pip install -r requirements.txt

# 4. Configure the Gemini key (never hard-coded)
cp .env.example .env             # Windows: copy .env.example .env
#    edit .env -> GEMINI_API_KEY=your-key-here
```

Minimum `.env`:

```dotenv
GEMINI_API_KEY=AIza...your-real-key...
# optional:
GEMINI_MODELS=gemini-2.5-flash,gemini-2.5-pro
GEMINI_TEMPERATURE=0.4
```

The math engine and charts work **without** a key; only the AI panel needs one.

---

## 4. Using the Streamlit app (walkthrough)

```bash
streamlit run app.py
```

Open the printed URL (default <http://localhost:8501>).

**Sidebar — Control Panel** (left):

1. **Total corpus (₹)** — enter your amount. The simulation stays idle until
   this is > 0.
2. **Age** — used only to test SCSS eligibility (≥ 60).
3. **POMIS holding** — Single (₹9L ceiling) vs Joint (₹15L).
4. **Marginal tax slab** — 10/20/30%, applied to slab-taxed interest.
5. **Target monthly cash flow (₹)** — optional, for a surplus/shortfall
   comparison.
6. **Allocation % sliders** — POMIS / SCSS / FRSB / FD / debt / equity-SWP. The
   app warns if they don't sum to 100%.
7. **Rate sliders** — override statutory/illustrative rates to stress-test.
8. **Equity assumptions** — return %, volatility %, SWP withdrawal %, horizon,
   Monte Carlo paths.

**Main panel** (right):

- **KPI cards** — blended fixed-income yield, post-tax fixed-income/month,
  equity SWP draw/month, sequence-of-returns sensitivity score.
- **Charts** — allocation donut, monthly cash-flow waterfall, sequence-of-returns
  stress chart, Monte Carlo path cloud.
- **Monte Carlo summary** — 5th/median/95th percentile ending values and
  probability of depletion.
- **Instrument table** — per-instrument principal, yield, post-tax monthly cash
  flow, risk, liquidity, and any statutory notes.
- **🤖 ArthaLab AI insights** — click to have Gemini explain the scenario.
- **Disclaimer** — persistent banner + footer on every screen.

Everything recomputes live as you move the sliders.

---

## 5. Using the math engine in code

`math_engine.py` is pure Python (only `numpy`), with no I/O — import and call it
directly. All amounts are INR; all rates are decimals (`0.074` = 7.4%).

### 5.1 A single instrument (with statutory cap)

```python
import math_engine as me

r = me.pomis(2_000_000, joint=False, slab_rate=0.30)
print(r.name, r.principal, round(r.post_tax_monthly_interest), r.notes)
```

Real output — note the cap and the *reported* overflow:

```
POMIS 900000 3885 Requested Rs 2,000,000 exceeds the single POMIS ceiling of Rs 900,000. Rs 1,100,000 is not deployable here.
```

### 5.2 Eligibility handling (SCSS under 60)

```python
y = me.scss(1_000_000, age=45, slab_rate=0.20)
print(y.principal, y.notes)
# -> 0  Not eligible: SCSS requires age >= 60 (profile age = 45).
```

### 5.3 Aggregating a fixed-income book

```python
book = me.build_fixed_income_book([
    me.pomis(900_000, joint=False, slab_rate=0.30),
    me.scss(3_000_000, age=65, slab_rate=0.30),
    me.frsb(1_000_000, slab_rate=0.30),
])
print(book["total_principal"],
      round(book["blended_gross_yield"], 4),
      round(book["post_tax_monthly_income"]))
# -> 4900000  0.0802  22931
```

### 5.4 A single SWP path

```python
s = me.simulate_swp(4_000_000, monthly_withdrawal=20_000,
                    annual_return=0.12, years=15)
print(round(s.ending_corpus), s.corpus_depleted)
# -> 12465106  False
```

### 5.5 Sequence-of-returns stress test

```python
st = me.sequence_of_returns_stress_test(4_000_000, 20_000, 0.12, 15)
print(round(st["crash_-20_y1_2"].ending_corpus),   # bad years EARLY
      round(st["good_first"].ending_corpus),         # same bad years LATE
      me.sequence_sensitivity_score(st))
# -> 3053420  6652381  75.5
```

The identical shocks leave **₹3.05M** when they hit early vs **₹6.65M** when
late — the whole point about *timing*, not just average return.

### 5.6 Monte Carlo

```python
mc = me.monte_carlo_swp(4_000_000, 20_000,
                        mean_annual_return=0.12, annual_volatility=0.18,
                        years=15, n_paths=2000, seed=42)
print(round(mc.percentile_5), round(mc.percentile_50),
      round(mc.percentile_95), mc.prob_depletion)
# -> 949552  8930277  36458471  0.018
```

`seed` makes runs reproducible. `prob_depletion` is the share of paths where the
SWP bucket hit zero before the horizon **under your assumptions**.

### 5.7 Return objects (fields)

| Object | Key fields |
|--------|-----------|
| `InstrumentResult` | `name, principal, gross_rate, annual_interest, monthly_interest, post_tax_annual_interest, post_tax_monthly_interest, risk_level, liquidity, notes`; `.as_dict()` |
| `SWPResult` | `label, monthly_withdrawal, annual_return_assumed, months, ending_corpus, corpus_depleted, depletion_month, total_withdrawn, balance_path` |
| `MonteCarloResult` | `years, n_paths, percentile_5/25/50/75/95, prob_depletion, sample_paths` |

---

## 6. Using the Gemini AI service in code

`gemini_service.py` reads all config from the environment (`.env`) and enforces
the educational system prompt.

```python
from gemini_service import GeminiService, get_service_or_error

# Safe constructor for UIs — never raises:
service, error = get_service_or_error()
if error:
    print("Cannot use AI:", error)      # e.g. missing GEMINI_API_KEY
else:
    print("Model chain:", service.models)   # ['gemini-2.5-flash', 'gemini-2.5-pro']
    resp = service.explain_scenario(
        "Corpus Rs 1,00,00,000; POMIS Rs 15L joint @7.4%; "
        "equity SWP Rs 40L withdrawing 6% p.a., assumed 12% return."
    )
    print(resp.model_used, resp.fell_back)
    print(resp.text)
```

- `GeminiService.generate(prompt, temperature=None)` — raw call over the model
  chain; returns a `GeminiResponse(text, model_used, fell_back)`.
- The service tries each model left→right and returns the first success;
  `fell_back=True` means a non-primary model answered.
- Raises `GeminiConfigError` (key/SDK issues) or `GeminiCallError` (all models
  failed). Use `get_service_or_error()` in UI code to avoid try/except.

---

## 7. Using the FastAPI backend

The Streamlit app doesn't need it, but the same math is available as JSON.

```bash
uvicorn api:app --reload --port 8000
# interactive docs: http://localhost:8000/docs
```

### Request

```bash
curl -X POST localhost:8000/simulate \
  -H 'Content-Type: application/json' \
  -d '{"corpus": 10000000, "age": 62, "joint": true, "slab_rate": 0.30}'
```

### Response (compact excerpt of real output)

```json
{
  "total_modelled_monthly_cash_flow": 46395.83,
  "fixed_income": {
    "blended_gross_yield": 0.0754,
    "post_tax_monthly_income": 26395.83
  },
  "swp": {
    "monthly_withdrawal": 20000.0,
    "sequence_sensitivity_score": 75.5,
    "monte_carlo": {
      "n_paths": 2000,
      "percentile_5": 949552.31,
      "percentile_50": 8930277.25,
      "percentile_95": 36458471.41,
      "prob_depletion": 0.018
    }
  }
}
```

The full response also includes a `disclaimer` field, per-instrument detail, and
the four-scenario stress test. Request fields and defaults are documented in
[GUIDE.md §C.3](GUIDE.md#c3-fastapi-request-fields-simulate). `GET /health`
returns a status + disclaimer.

---

## 8. End-to-end worked example

Model a ₹1 crore corpus for a 62-year-old (joint POMIS, 30% slab), split
40% fixed income / 40% equity SWP / 20% liquidity, and print a summary:

```python
import math_engine as me

CORPUS = 10_000_000
slab = 0.30
alloc = {"pomis": 0.15, "scss": 0.15, "frsb": 0.10,
         "fd": 0.10, "debt": 0.10, "swp": 0.40}
amt = {k: CORPUS * v for k, v in alloc.items()}

book = me.build_fixed_income_book([
    me.pomis(amt["pomis"], joint=True, slab_rate=slab),
    me.scss(amt["scss"], age=62, slab_rate=slab),
    me.frsb(amt["frsb"], slab_rate=slab),
    me.fixed_deposit(amt["fd"], slab_rate=slab),
    me.low_duration_fund(amt["debt"], slab_rate=slab),
])

swp_monthly = amt["swp"] * 0.06 / 12          # 6% p.a. withdrawal
stress = me.sequence_of_returns_stress_test(amt["swp"], swp_monthly, 0.12, 15)
mc = me.monte_carlo_swp(amt["swp"], swp_monthly, 0.12, 0.18, 15, seed=42)

print(f"Post-tax fixed income:  Rs {book['post_tax_monthly_income']:,.0f}/mo")
print(f"Equity SWP draw:        Rs {swp_monthly:,.0f}/mo (NOT guaranteed)")
print(f"Total modelled cashflow: Rs "
      f"{book['post_tax_monthly_income'] + swp_monthly:,.0f}/mo")
print(f"Sensitivity score:      {me.sequence_sensitivity_score(stress)}/100")
print(f"MC median / depletion:  Rs {mc.percentile_50:,.0f} / "
      f"{mc.prob_depletion*100:.1f}%")
```

Produces (verified):

```
Post-tax fixed income:  Rs 26,396/mo
Equity SWP draw:        Rs 20,000/mo (NOT guaranteed)
Total modelled cashflow: Rs 46,396/mo
Sensitivity score:      75.5/100
MC median / depletion:  Rs 8,930,277 / 1.8%
```

Read this correctly: **₹26,396/mo is guaranteed-style; ₹20,000/mo is not** — it
depends on markets, and the 75.5 sensitivity score warns that the outcome hinges
heavily on the *order* of returns.

---

## 9. Extending the application

### Add a new fixed-income instrument

1. In `math_engine.py`, add a function returning an `InstrumentResult` (copy the
   shape of `fixed_deposit`). Enforce any statutory limit in `.notes`.
2. Add a matching allocation slider in `app.py::sidebar_inputs` and include the
   instrument in `compute_scenario`.
3. Add a unit test to `test_math_engine.py`.

### Add a chart

Add a builder function in `app.py` (see `donut_allocation` / `stress_chart`) and
render it with `st.plotly_chart(...)` in `main()`.

### Change models

No code change — edit `GEMINI_MODELS` in `.env`.

---

## 10. Testing

```bash
pytest -q          # expect: 8 passed
```

The suite (`test_math_engine.py`) locks in the arithmetic and the statutory
rules: POMIS/SCSS caps, eligibility, post-tax < gross, SWP depletion,
sequence-of-returns ordering, Monte Carlo reproducibility, and book aggregation.
CI runs it on every push (see `.github/workflows/tests.yml`).

---

## 11. Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| "GEMINI_API_KEY is not set" | Create `.env` from `.env.example` and add your key, or export it in the shell. |
| AI panel: "All models in the chain failed" | Bad/expired key, no network, or an invalid model id in `GEMINI_MODELS`. Verify ids at <https://ai.google.dev/gemini-api/docs/models>. |
| `ModuleNotFoundError: google` | `pip install google-genai` (or `pip install -r requirements.txt`). |
| Charts blank / allocation warning | Your allocation sliders don't sum to 100%. Adjust them. |
| Numbers look "too good" | Lower the assumed equity return/volatility. The model is only as good as your inputs. |
| `UnicodeDecodeError` reading files on Windows | Files are UTF-8; open with `encoding="utf-8"`. |

---

## 12. Glossary

| Term | Meaning |
|------|---------|
| **POMIS** | Post Office Monthly Income Scheme — monthly interest, ₹9L/₹15L ceilings. |
| **SCSS** | Senior Citizen Savings Scheme — age ≥ 60, ₹30L ceiling. |
| **RBI FRSB** | RBI Floating Rate Savings Bonds — 7-yr lock-in, floating coupon, taxable. |
| **SWP** | Systematic Withdrawal Plan — periodic redemption from a fund; **not** interest. |
| **Sequence-of-returns risk** | The risk that *early* poor returns, while withdrawing, permanently impair a corpus even if the average return is fine. |
| **Slab rate** | Your marginal income-tax rate (10/20/30%+). |
| **LTCG / STCG** | Long-/Short-Term Capital Gains tax. |
| **SEBI RIA** | SEBI Registered Investment Adviser — a licensed professional. ArthaLab is **not** one. |

---

*ArthaLab is an educational modelling tool. Consult a SEBI-registered adviser and
a qualified tax professional before making any financial decision.*
