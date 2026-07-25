# ArthaLab — Investment Strategy & Portfolio Simulator

An **educational, interactive mathematical modelling tool** for the Indian
financial ecosystem. You configure a hypothetical corpus and allocation;
ArthaLab does the arithmetic, separates *guaranteed fixed-income yields* from
*market-linked (SWP) projections*, and shows the trade-offs and risks.

> ### ⚠️ Not investment advice
> ArthaLab is **not** a SEBI Registered Investment Adviser (RIA) and does not
> recommend any scheme, security, or allocation. Every figure is a hypothetical
> output of *your* assumptions and may be wrong. Statutory rates, limits, and
> tax rules change — verify against official sources. Market-linked returns
> (SWP, mutual funds) are **not guaranteed** and can result in loss of capital.
> Consult a SEBI-registered adviser and a qualified tax professional before
> acting on anything.

---

## What it does

- **Fixed-income modelling** with statutory limits and eligibility enforced:
  POMIS (₹9L single / ₹15L joint), SCSS (age ≥ 60, ₹30L), RBI FRSB (7-yr
  lock-in), bank/corporate FDs, and low-duration debt funds — each with
  slab-based post-tax cash flow.
- **Equity SWP simulator** that treats a Systematic Withdrawal Plan as what it
  is — a redemption of capital + growth, **not** interest income.
- **Sequence-of-returns stress test** showing how an early −15% / −20% market
  fall can permanently impair the corpus, even when the *average* return is
  unchanged.
- **Monte Carlo** distribution of SWP outcomes (percentiles + probability of
  depletion) under your mean/volatility assumptions.
- **Gemini-powered explanations** (via the official `google-genai` SDK) that
  describe the mechanics, taxation, and risks of *your* scenario — framed as
  education, never as a recommendation.

## File structure

| File | Purpose |
|------|---------|
| `app.py` | Streamlit dashboard (inputs, KPI cards, Plotly charts, AI panel). |
| `math_engine.py` | Pure-Python financial math, tax logic, SWP stress-testing, Monte Carlo. No I/O, fully testable. |
| `gemini_service.py` | `google-genai` integration — key + model chain read from `.env`; env-configurable models (default `gemini-2.5-flash` → `gemini-2.5-pro`). |
| `api.py` | *Optional* FastAPI backend exposing the same models as JSON. |
| `test_math_engine.py` | Pytest suite locking in the arithmetic and statutory rules. |
| `.env.example` | Template for the `.env` config file (copy to `.env`). |
| `GUIDE.md` | Complete key / code / parameter reference. |
| `requirements.txt` | Dependencies. |

## Setup

```bash
# 1. (Recommended) create a virtual environment
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure your Gemini API key via a .env file (NEVER put keys in code)
cp .env.example .env          # Windows: copy .env.example .env
#    then edit .env and set:  GEMINI_API_KEY=your-key-here
#    get a key at https://aistudio.google.com/apikey
```

The key is loaded from `.env` at startup (via `python-dotenv`) and is never
hard-coded or committed — `.env` is git-ignored. To switch models, set
`GEMINI_MODELS` in `.env` (no code change). See **[GUIDE.md](GUIDE.md)** for the
full key / code / parameter reference.

The app runs **without** a key — you just won't get the AI insights panel; it
shows a clear, actionable error instead of crashing.

## Run

### Streamlit dashboard (primary)

```bash
streamlit run app.py
```

Open the URL Streamlit prints (default http://localhost:8501). Enter a corpus
and adjust the allocation/assumption sliders — every chart recomputes live.

### Optional JSON API

```bash
uvicorn api:app --reload --port 8000
```

```bash
curl -X POST localhost:8000/simulate \
  -H 'Content-Type: application/json' \
  -d '{"corpus": 10000000, "age": 62, "joint": true, "slab_rate": 0.30}'
```

Interactive docs at http://localhost:8000/docs.

### Tests

```bash
pytest -q
```

## Design notes

- **Every statutory number is a parameter with a documented default.** The UI
  exposes rates as sliders so you can stress-test, and the defaults (July 2025)
  are clearly marked as *not guaranteed to be current*.
- **Nothing is silently reallocated.** If your POMIS input exceeds the ceiling,
  the engine caps it and *tells you* about the overflow rather than quietly
  moving money — the user decides.
- **SWP is never labelled "income."** The UI and AI prompt consistently frame it
  as a capital redemption subject to sequence-of-returns risk.
- **The math engine has no external dependencies beyond NumPy** and no I/O, so
  it is fully unit-testable and reusable by both the Streamlit app and the API.

## Assumptions & limitations

- Tax handling is simplified for scenario comparison (e.g. the equity LTCG
  exemption is applied in aggregate). It is **not** a substitute for a tax
  filing or professional advice.
- Rates and statutory limits are illustrative defaults and change over time.
- Monte Carlo uses lognormal monthly returns; real markets have fat tails,
  autocorrelation, and regime changes this model does not capture. Treat the
  distribution as a *teaching aid*, not a forecast.
