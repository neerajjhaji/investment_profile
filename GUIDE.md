# ArthaLab — Complete Guide (Key · Code · Parameters)

A single reference for **configuring the Gemini API key**, understanding the
**code architecture**, and every **parameter** the system accepts.

> ⚠️ **Educational simulator, not advice.** ArthaLab is a mathematical modelling
> tool. It is **not** a SEBI Registered Investment Adviser and recommends
> nothing. Every figure is a hypothetical output of *your* assumptions.

---

## Table of contents

1. [Part A — The API Key (`.env` configuration)](#part-a--the-api-key-env-configuration)
2. [Part B — The Code (architecture & modules)](#part-b--the-code-architecture--modules)
3. [Part C — Parameter Reference](#part-c--parameter-reference)
   - [C.1 Environment variables](#c1-environment-variables)
   - [C.2 `math_engine.py` function parameters](#c2-math_enginepy-function-parameters)
   - [C.3 FastAPI request fields (`/simulate`)](#c3-fastapi-request-fields-simulate)
   - [C.4 Streamlit UI inputs](#c4-streamlit-ui-inputs)
4. [Part D — Run & verify](#part-d--run--verify)

---

## Part A — The API Key (`.env` configuration)

**The key is never written in code.** It is read at startup from a local
`.env` file (loaded by `python-dotenv`) or from a shell environment variable.
`.env` is git-ignored, so the secret cannot be committed.

### Step-by-step

```bash
# 1. Copy the template
cp .env.example .env          # Windows: copy .env.example .env

# 2. Get a key (free tier available)
#    https://aistudio.google.com/apikey

# 3. Edit .env and paste your key
#    GEMINI_API_KEY=AIza...your-real-key...
```

That's it. Launch the app and the key is picked up automatically.

### How the key flows through the code

```
.env  ──load_dotenv()──►  os.environ["GEMINI_API_KEY"]
                                    │
                          _require_api_key()   ← raises a friendly error if blank
                                    │
                          genai.Client(api_key=...)   ← the only place the key is used
```

- If the key is missing, the UI shows a clear message telling you to create
  `.env` — it does **not** crash.
- The key is only ever passed to `genai.Client(...)`; it is never logged,
  printed, or written back to disk.

### Security guarantees

| Guarantee | How it's enforced |
|-----------|-------------------|
| Key never in source | Read from env only; no default value in code |
| Key never committed | `.gitignore` blocks `.env` and `.env.*` (except `.env.example`) |
| Key never leaked to the model | Only the scenario numbers are sent as prompt text |
| Clear failure, not a crash | `GeminiConfigError` → friendly UI message |

---

## Part B — The Code (architecture & modules)

```
                ┌──────────────────────────────┐
                │            .env               │  GEMINI_API_KEY, models, temp
                └──────────────┬───────────────┘
                               │ load_dotenv()
      ┌────────────────────────▼─────────────────────────┐
      │                gemini_service.py                  │  AI explanations
      │  GeminiService · model chain · typed errors       │
      └────────────────────────▲─────────────────────────┘
                               │ scenario summary (text)
   ┌──────────────┐    ┌───────┴────────┐    ┌──────────────────┐
   │   app.py     │    │  math_engine.py │    │     api.py        │
   │  Streamlit   │───►│  pure functions │◄───│  FastAPI (JSON)   │
   │  dashboard   │    │  (no I/O)       │    │  optional backend │
   └──────────────┘    └────────────────┘    └──────────────────┘
```

| File | Role | Depends on |
|------|------|-----------|
| **`math_engine.py`** | Pure-Python financial math. No I/O, no network, no globals mutated — fully unit-testable. Statutory limits & eligibility enforced. | `numpy` |
| **`gemini_service.py`** | Wraps the `google-genai` SDK. Loads config from `.env`, tries an ordered model chain, raises typed errors. | `google-genai`, `python-dotenv` |
| **`app.py`** | Streamlit dashboard: sidebar inputs → `compute_scenario()` → KPI cards + Plotly charts + AI panel. | `streamlit`, `plotly`, `pandas`, the two modules above |
| **`api.py`** | *Optional* FastAPI backend exposing the same math as JSON `/simulate`. The Streamlit app does not need it. | `fastapi`, `pydantic`, `math_engine` |
| **`test_math_engine.py`** | Pytest suite locking in the arithmetic and statutory rules (8 tests). | `pytest` |

### Key functions at a glance

- `math_engine.pomis / scss / frsb / fixed_deposit / arbitrage_fund / low_duration_fund`
  → each returns an `InstrumentResult` (principal, gross/post-tax cash flow, risk, notes).
- `math_engine.simulate_swp` → one deterministic SWP path.
- `math_engine.sequence_of_returns_stress_test` → compares early vs late crashes.
- `math_engine.monte_carlo_swp` → probabilistic distribution of SWP outcomes.
- `gemini_service.GeminiService.explain_scenario` → AI explanation of a scenario.

---

## Part C — Parameter Reference

### C.1 Environment variables

Set these in `.env` (see `.env.example`). Only the first is required.

| Variable | Required | Default | Description |
|----------|:--------:|---------|-------------|
| `GEMINI_API_KEY` | ✅ | — | Your Google Gemini API key. The app errors clearly if unset. |
| `GEMINI_MODELS` | ➖ | *(unset)* | Comma-separated fallback chain, tried left→right. **Highest priority** — overrides the pair below. e.g. `gemini-2.5-flash,gemini-2.5-pro`. Set newer ids here (e.g. a gemini-3.x family) with **no code change**. |
| `GEMINI_PRIMARY_MODEL` | ➖ | `gemini-2.5-flash` | Primary model, used if `GEMINI_MODELS` is unset. |
| `GEMINI_FALLBACK_MODEL` | ➖ | `gemini-2.5-pro` | Fallback model, used if the primary fails. |
| `GEMINI_TEMPERATURE` | ➖ | `0.4` | Generation temperature, `0.0` (deterministic) → `1.0` (creative). |

**Resolution order for models:** `GEMINI_MODELS` → (`GEMINI_PRIMARY_MODEL` +
`GEMINI_FALLBACK_MODEL`) → built-in defaults. Blanks and duplicates are removed
while preserving order.

> **On model ids:** the defaults (`gemini-2.5-*`) are verified working ids.
> Google's catalogue changes over time; before setting a newer id, confirm it
> is available to your key at <https://ai.google.dev/gemini-api/docs/models>.

### C.2 `math_engine.py` function parameters

All monetary values are in **INR**. All rates are **decimals** (`0.074` = 7.4%).

#### Statutory default constants (editable at call sites / via UI sliders)

| Constant | Value | Meaning |
|----------|-------|---------|
| `POMIS_LIMIT_SINGLE` | `900000` | ₹9L POMIS ceiling, single holding |
| `POMIS_LIMIT_JOINT` | `1500000` | ₹15L POMIS ceiling, joint holding |
| `POMIS_RATE` | `0.074` | ~7.4% p.a., monthly payout |
| `SCSS_LIMIT` | `3000000` | ₹30L SCSS ceiling |
| `SCSS_RATE` | `0.082` | ~8.2% p.a. |
| `SCSS_MIN_AGE` | `60` | Minimum age for SCSS eligibility |
| `FRSB_RATE` | `0.0805` | ~8.05% p.a. (NSC + 0.35%) |
| `FRSB_LOCKIN_YEARS` | `7` | RBI FRSB lock-in |
| `FD_RATE` / `ARBITRAGE_RATE` / `LOW_DURATION_RATE` | `0.070` / `0.065` / `0.068` | Illustrative fund/FD rates |
| `EQUITY_LTCG_RATE` / `EQUITY_LTCG_EXEMPTION` | `0.125` / `125000` | Equity LTCG: 12.5% above ₹1.25L/yr |
| `EQUITY_STCG_RATE` | `0.20` | Equity STCG (held < 12 months) |

#### Fixed-income instrument functions

Each returns an `InstrumentResult`.

| Function | Parameters | Notes |
|----------|-----------|-------|
| `pomis(principal, joint, slab_rate, rate=POMIS_RATE)` | `joint: bool` selects the ceiling | Caps at limit; reports overflow in `.notes` (never silently reallocates) |
| `scss(principal, age, slab_rate, rate=SCSS_RATE)` | `age: int` | Returns zero principal + reason if `age < 60` |
| `frsb(principal, slab_rate, rate=FRSB_RATE)` | — | 7-yr lock-in; taxable at slab |
| `fixed_deposit(principal, slab_rate, rate=FD_RATE, label="Bank FD")` | `label` for bank vs corporate | Taxed at slab |
| `arbitrage_fund(principal, rate=ARBITRAGE_RATE)` | — | Equity taxation (on redemption) |
| `low_duration_fund(principal, slab_rate, rate=LOW_DURATION_RATE)` | — | Debt taxation at slab (post-Apr-2023) |

Common parameters: `principal` (₹), `slab_rate` (marginal tax as decimal, e.g.
`0.30`), `rate` (annual yield as decimal).

#### SWP & simulation functions

| Function | Parameters | Returns |
|----------|-----------|---------|
| `simulate_swp(corpus, monthly_withdrawal, annual_return, years, label="Base case", shock_schedule=None)` | `shock_schedule`: `{year_index: annual_return_override}` to force bad years | `SWPResult` (ending corpus, depletion month, month-end balance path) |
| `sequence_of_returns_stress_test(corpus, monthly_withdrawal, annual_return, years)` | — | `dict` of 4 `SWPResult`s: smooth / −15% Yr1 / −15%+−20% early / same shocks late |
| `sequence_sensitivity_score(stress)` | output of the stress test | `float` 0–100 (higher = outcome depends more on the *order* of returns) |
| `monte_carlo_swp(corpus, monthly_withdrawal, mean_annual_return, annual_volatility, years, n_paths=2000, seed=42, n_sample_paths=25)` | `seed` makes runs reproducible | `MonteCarloResult` (5/25/50/75/95 percentiles, `prob_depletion`, sample paths) |
| `build_fixed_income_book(allocations)` | list of `InstrumentResult` | portfolio totals + blended yield (sums only — no allocation decisions) |
| `compound_projection(principal, annual_rate, years_list)` | — | `{year: value}` snapshots |

### C.3 FastAPI request fields (`/simulate`)

`POST /simulate` with a JSON body (`SimulationRequest`):

| Field | Type | Default | Constraints |
|-------|------|---------|-------------|
| `corpus` | float | — (required) | `> 0`, total INR |
| `age` | int | `45` | 18–100 (drives SCSS eligibility) |
| `joint` | bool | `false` | POMIS joint holding |
| `slab_rate` | float | `0.30` | 0–0.45 marginal tax |
| `allocation` | object | `{pomis:15, scss:15, frsb:10, fd:10, debt:10, swp:40}` | each `≥ 0`, **percentages** of corpus |
| `equity_return` | float | `0.12` | assumed equity CAGR |
| `equity_vol` | float | `0.18` | annualised volatility |
| `swp_rate` | float | `0.06` | SWP withdrawal rate p.a. |
| `horizon_years` | int | `15` | 1–40 |
| `mc_paths` | int | `2000` | 100–20000 Monte Carlo paths |
| `seed` | int? | `42` | reproducibility |

Example:

```bash
curl -X POST localhost:8000/simulate \
  -H 'Content-Type: application/json' \
  -d '{"corpus": 10000000, "age": 62, "joint": true, "slab_rate": 0.30}'
```

The response always includes a `disclaimer` field and separates `fixed_income`
(guaranteed-style) from `swp` (market-linked, not guaranteed).

### C.4 Streamlit UI inputs

Rendered in the sidebar (`app.py::sidebar_inputs`):

| Control | Maps to |
|---------|---------|
| Total corpus (₹) | `corpus` — no default; simulation waits until > 0 |
| Age | SCSS eligibility check |
| POMIS holding (Single/Joint) | POMIS ceiling |
| Marginal tax slab (10/20/30%) | `slab_rate` on all slab-taxed interest |
| Target monthly cash flow (₹) | Comparison only (surplus/shortfall) |
| Allocation % sliders (6 buckets) | Percentages; app warns if they ≠ 100% |
| Rate sliders (POMIS/SCSS/FRSB/FD/debt) | Override statutory defaults to stress-test |
| Equity return / volatility / SWP rate | Feed the SWP simulator & Monte Carlo |
| Projection horizon (years) | Stress-test & Monte Carlo horizon |
| Monte Carlo paths | `n_paths` |

---

## Part D — Run & verify

```bash
# Install everything
pip install -r requirements.txt

# Configure the key
cp .env.example .env    # then edit .env and paste GEMINI_API_KEY

# Run the dashboard
streamlit run app.py

# (Optional) run the JSON API
uvicorn api:app --reload --port 8000     # docs at /docs

# Run the tests
pytest -q                                # expect: 8 passed
```

**The app runs without a key** — you just won't get the AI insights panel; it
shows a clear, actionable message instead of crashing.
