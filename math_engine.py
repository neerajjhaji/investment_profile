"""
math_engine.py
==============
Pure-Python financial modelling engine for ArthaLab.

Design principles
-----------------
* Deterministic, side-effect-free functions. No I/O, no globals mutated.
* Every rate/limit is a *parameter with a documented statutory default* so the
  UI can expose it as a slider. Statutory numbers change; never hard-code them
  as immutable truth.
* Nothing here recommends anything. These functions answer "given THESE
  assumptions, what does the arithmetic produce?" -- that is all.

All monetary values are in INR unless otherwise noted.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional

import numpy as np

# ---------------------------------------------------------------------------
# Statutory / conventional defaults (July 2025). Editable via the UI.
# These are DEFAULTS for a simulator, not advice and not guaranteed to be
# current -- users must verify against official sources.
# ---------------------------------------------------------------------------

POMIS_LIMIT_SINGLE = 900_000      # Rs 9 lakh, single holding
POMIS_LIMIT_JOINT = 1_500_000     # Rs 15 lakh, joint holding
POMIS_RATE = 0.074                # ~7.4% p.a., paid monthly

SCSS_LIMIT = 3_000_000            # Rs 30 lakh
SCSS_RATE = 0.082                 # ~8.2% p.a., paid quarterly
SCSS_MIN_AGE = 60

FRSB_RATE = 0.0805                # ~8.05% p.a. (NSC + 0.35%), paid half-yearly
FRSB_LOCKIN_YEARS = 7

FD_RATE = 0.070                   # ~7.0% p.a., illustrative
ARBITRAGE_RATE = 0.065            # ~6.5% p.a., illustrative, equity-taxed
LOW_DURATION_RATE = 0.068         # ~6.8% p.a., illustrative, slab-taxed

# Equity capital-gains rules (FY24-25 onward)
EQUITY_LTCG_RATE = 0.125          # 12.5% above the annual exemption
EQUITY_LTCG_EXEMPTION = 125_000   # Rs 1.25 lakh per year
EQUITY_STCG_RATE = 0.20           # 20% if held < 12 months


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------

@dataclass
class InstrumentResult:
    """One fixed-income instrument's contribution to the scenario."""
    name: str
    principal: float
    gross_rate: float
    annual_interest: float
    monthly_interest: float          # gross, averaged to a monthly figure
    post_tax_annual_interest: float
    post_tax_monthly_interest: float
    risk_level: str
    liquidity: str
    notes: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class SWPResult:
    """Outcome of a single deterministic SWP path."""
    label: str
    monthly_withdrawal: float
    annual_return_assumed: float
    months: int
    ending_corpus: float
    corpus_depleted: bool
    depletion_month: Optional[int]
    total_withdrawn: float
    balance_path: list = field(default_factory=list)   # month-end balances


@dataclass
class MonteCarloResult:
    years: int
    n_paths: int
    percentile_5: float
    percentile_25: float
    percentile_50: float
    percentile_75: float
    percentile_95: float
    prob_depletion: float
    sample_paths: list = field(default_factory=list)   # a handful for plotting


# ---------------------------------------------------------------------------
# Tax helpers
# ---------------------------------------------------------------------------

def slab_tax(amount: float, slab_rate: float) -> float:
    """Tax on `amount` of income taxed at the investor's marginal slab."""
    return max(0.0, amount) * slab_rate


def equity_gains_tax(gain: float, held_long_term: bool = True) -> float:
    """
    Approximate capital-gains tax on realised equity gains.

    This is a simplification: it applies the annual LTCG exemption to the
    full year's gain in aggregate. Real filings net gains/losses across
    instruments -- treat this as an estimate for scenario comparison only.
    """
    gain = max(0.0, gain)
    if held_long_term:
        taxable = max(0.0, gain - EQUITY_LTCG_EXEMPTION)
        return taxable * EQUITY_LTCG_RATE
    return gain * EQUITY_STCG_RATE


# ---------------------------------------------------------------------------
# Fixed-income instruments
# ---------------------------------------------------------------------------

def pomis(principal: float, joint: bool, slab_rate: float,
          rate: float = POMIS_RATE) -> InstrumentResult:
    """
    Post Office Monthly Income Scheme. Interest paid monthly, taxed at slab.
    Statutory ceiling enforced; excess is reported in `notes` (NOT silently
    reallocated -- the caller decides what to do with the overflow).
    """
    limit = POMIS_LIMIT_JOINT if joint else POMIS_LIMIT_SINGLE
    capped = min(principal, limit)
    overflow = principal - capped
    annual = capped * rate
    post_tax_annual = annual - slab_tax(annual, slab_rate)
    notes = ""
    if overflow > 0:
        notes = (f"Requested Rs {principal:,.0f} exceeds the "
                 f"{'joint' if joint else 'single'} POMIS ceiling of "
                 f"Rs {limit:,.0f}. Rs {overflow:,.0f} is not deployable here.")
    return InstrumentResult(
        name="POMIS",
        principal=capped,
        gross_rate=rate,
        annual_interest=annual,
        monthly_interest=annual / 12,
        post_tax_annual_interest=post_tax_annual,
        post_tax_monthly_interest=post_tax_annual / 12,
        risk_level="Sovereign / very low",
        liquidity="5-yr term; premature exit penalty",
        notes=notes,
    )


def scss(principal: float, age: int, slab_rate: float,
         rate: float = SCSS_RATE) -> InstrumentResult:
    """
    Senior Citizen Savings Scheme. Requires age >= 60. Interest paid
    quarterly, taxed at slab. Ceiling Rs 30 lakh.
    """
    eligible = age >= SCSS_MIN_AGE
    if not eligible:
        return InstrumentResult(
            name="SCSS",
            principal=0.0,
            gross_rate=rate,
            annual_interest=0.0,
            monthly_interest=0.0,
            post_tax_annual_interest=0.0,
            post_tax_monthly_interest=0.0,
            risk_level="Sovereign / very low",
            liquidity="5-yr term (extendable 3 yrs)",
            notes=(f"Not eligible: SCSS requires age >= {SCSS_MIN_AGE} "
                   f"(profile age = {age})."),
        )
    capped = min(principal, SCSS_LIMIT)
    overflow = principal - capped
    annual = capped * rate
    post_tax_annual = annual - slab_tax(annual, slab_rate)
    notes = ""
    if overflow > 0:
        notes = (f"Requested Rs {principal:,.0f} exceeds the SCSS ceiling of "
                 f"Rs {SCSS_LIMIT:,.0f}. Rs {overflow:,.0f} not deployable here.")
    return InstrumentResult(
        name="SCSS",
        principal=capped,
        gross_rate=rate,
        annual_interest=annual,
        monthly_interest=annual / 12,
        post_tax_annual_interest=post_tax_annual,
        post_tax_monthly_interest=post_tax_annual / 12,
        risk_level="Sovereign / very low",
        liquidity="5-yr term (extendable 3 yrs)",
        notes=notes,
    )


def frsb(principal: float, slab_rate: float,
         rate: float = FRSB_RATE) -> InstrumentResult:
    """
    RBI Floating Rate Savings Bonds. 7-yr lock-in, non-tradable, floating
    coupon reset half-yearly, interest fully taxable at slab. No cumulative
    option (income only).
    """
    annual = principal * rate
    post_tax_annual = annual - slab_tax(annual, slab_rate)
    return InstrumentResult(
        name="RBI FRSB",
        principal=principal,
        gross_rate=rate,
        annual_interest=annual,
        monthly_interest=annual / 12,
        post_tax_annual_interest=post_tax_annual,
        post_tax_monthly_interest=post_tax_annual / 12,
        risk_level="Sovereign / very low",
        liquidity=f"{FRSB_LOCKIN_YEARS}-yr lock-in; non-tradable",
        notes="Coupon floats (NSC + 0.35%); rate can move at each reset.",
    )


def fixed_deposit(principal: float, slab_rate: float,
                  rate: float = FD_RATE,
                  label: str = "Bank FD") -> InstrumentResult:
    """Bank / corporate FD. Interest accrues and is taxed at slab."""
    annual = principal * rate
    post_tax_annual = annual - slab_tax(annual, slab_rate)
    return InstrumentResult(
        name=label,
        principal=principal,
        gross_rate=rate,
        annual_interest=annual,
        monthly_interest=annual / 12,
        post_tax_annual_interest=post_tax_annual,
        post_tax_monthly_interest=post_tax_annual / 12,
        risk_level="Low (bank) / moderate (corporate)",
        liquidity="Breakable with penalty; corporate FDs less liquid",
        notes="TDS applies above threshold; interest taxed at slab.",
    )


def arbitrage_fund(principal: float,
                   rate: float = ARBITRAGE_RATE) -> InstrumentResult:
    """
    Arbitrage fund: taxed as EQUITY despite bond-like returns. Interest shown
    here is pre-tax growth; realised-gain tax is handled at withdrawal, not
    accrual, so post-tax == pre-tax on an accrual view.
    """
    annual = principal * rate
    return InstrumentResult(
        name="Arbitrage Fund",
        principal=principal,
        gross_rate=rate,
        annual_interest=annual,
        monthly_interest=annual / 12,
        post_tax_annual_interest=annual,   # tax realised on redemption
        post_tax_monthly_interest=annual / 12,
        risk_level="Low-moderate (market-neutral)",
        liquidity="High (open-ended)",
        notes="Equity taxation; returns not guaranteed and can vary.",
    )


def low_duration_fund(principal: float, slab_rate: float,
                      rate: float = LOW_DURATION_RATE) -> InstrumentResult:
    """
    Low-duration / debt fund. Post-Apr-2023 units: gains taxed at slab with
    no indexation. Modelled here on an accrual view for the cash-flow table.
    """
    annual = principal * rate
    post_tax_annual = annual - slab_tax(annual, slab_rate)
    return InstrumentResult(
        name="Low-Duration Debt Fund",
        principal=principal,
        gross_rate=rate,
        annual_interest=annual,
        monthly_interest=annual / 12,
        post_tax_annual_interest=post_tax_annual,
        post_tax_monthly_interest=post_tax_annual / 12,
        risk_level="Low-moderate (interest-rate + credit)",
        liquidity="High (open-ended)",
        notes="Debt taxation at slab (post Apr-2023); NAV can fluctuate.",
    )


# ---------------------------------------------------------------------------
# SWP simulation (the part people most often misunderstand)
# ---------------------------------------------------------------------------

def simulate_swp(corpus: float,
                 monthly_withdrawal: float,
                 annual_return: float,
                 years: int,
                 label: str = "Base case",
                 shock_schedule: Optional[dict] = None) -> SWPResult:
    """
    Deterministic monthly SWP simulation.

    A Systematic Withdrawal Plan is NOT yield. Each month you redeem units;
    in a down month you redeem MORE units to fund the same rupee amount,
    which can permanently impair the corpus (sequence-of-returns risk). This
    function makes that visible.

    Parameters
    ----------
    corpus : starting value of the equity bucket.
    monthly_withdrawal : fixed rupee draw each month.
    annual_return : assumed *average* annual return (compounded monthly).
    years : horizon.
    shock_schedule : optional {year_index (1-based): annual_return_override}
        to force a bad-returns sequence, e.g. {1: -0.15, 2: -0.20}.
    """
    months = years * 12
    base_monthly_growth = (1 + annual_return) ** (1 / 12) - 1
    shock_schedule = shock_schedule or {}

    balance = corpus
    path = []
    total_withdrawn = 0.0
    depletion_month = None

    for m in range(1, months + 1):
        year_idx = (m - 1) // 12 + 1
        if year_idx in shock_schedule:
            g = (1 + shock_schedule[year_idx]) ** (1 / 12) - 1
        else:
            g = base_monthly_growth

        # Grow first, then withdraw at month end.
        balance *= (1 + g)
        if balance >= monthly_withdrawal:
            balance -= monthly_withdrawal
            total_withdrawn += monthly_withdrawal
        else:
            total_withdrawn += balance
            balance = 0.0
        # Mark depletion the first time the bucket cannot fund a full draw
        # (a balance that lands on exactly zero counts as depleted).
        if balance <= 0.0 and depletion_month is None:
            depletion_month = m
        path.append(round(balance, 2))
        if balance <= 0.0:
            break

    # Pad the path if depleted early so charts stay aligned.
    while len(path) < months:
        path.append(0.0)

    return SWPResult(
        label=label,
        monthly_withdrawal=monthly_withdrawal,
        annual_return_assumed=annual_return,
        months=months,
        ending_corpus=round(balance, 2),
        corpus_depleted=depletion_month is not None,
        depletion_month=depletion_month,
        total_withdrawn=round(total_withdrawn, 2),
        balance_path=path,
    )


def sequence_of_returns_stress_test(corpus: float,
                                    monthly_withdrawal: float,
                                    annual_return: float,
                                    years: int) -> dict:
    """
    Compare a smooth-return SWP against paths where the market falls early.

    Returns a dict of SWPResult objects: 'base', 'crash_-15_y1',
    'crash_-20_y1_2', and 'good_first' (the same bad years, reordered to the
    end) to illustrate that *order* of returns matters, not just the average.
    """
    base = simulate_swp(corpus, monthly_withdrawal, annual_return, years,
                        label="Smooth average return")

    crash_15 = simulate_swp(
        corpus, monthly_withdrawal, annual_return, years,
        label="-15% shock in Year 1",
        shock_schedule={1: -0.15},
    )

    crash_20 = simulate_swp(
        corpus, monthly_withdrawal, annual_return, years,
        label="-15% Yr1 then -20% Yr2",
        shock_schedule={1: -0.15, 2: -0.20},
    )

    # Same two bad years, but pushed to the end of the horizon.
    good_first = simulate_swp(
        corpus, monthly_withdrawal, annual_return, years,
        label="Same shocks, but late (Yrs N-1, N)",
        shock_schedule={max(1, years - 1): -0.15, years: -0.20},
    )

    return {
        "base": base,
        "crash_-15_y1": crash_15,
        "crash_-20_y1_2": crash_20,
        "good_first": good_first,
    }


def sequence_sensitivity_score(stress: dict) -> float:
    """
    A 0-100 'how much does timing hurt' score.

    0  => early crashes barely change the ending corpus (robust).
    100 => an early crash wipes the corpus while a late one does not.
    Computed from the spread between the best and worst ending corpus
    relative to the smooth-return base.
    """
    base_end = max(stress["base"].ending_corpus, 1.0)
    endings = [r.ending_corpus for r in stress.values()]
    spread = max(endings) - min(endings)
    score = min(100.0, (spread / base_end) * 100.0)
    return round(score, 1)


# ---------------------------------------------------------------------------
# Monte Carlo
# ---------------------------------------------------------------------------

def monte_carlo_swp(corpus: float,
                    monthly_withdrawal: float,
                    mean_annual_return: float,
                    annual_volatility: float,
                    years: int,
                    n_paths: int = 2000,
                    seed: Optional[int] = 42,
                    n_sample_paths: int = 25) -> MonteCarloResult:
    """
    Monte Carlo of an equity SWP using lognormal monthly returns.

    This is a *probabilistic scenario tool*, not a forecast. The distribution
    of outcomes depends entirely on the mean/volatility assumptions the user
    feeds in. Garbage in, garbage out -- by design, so users can see it.
    """
    rng = np.random.default_rng(seed)
    months = years * 12

    mu_m = (1 + mean_annual_return) ** (1 / 12) - 1
    sigma_m = annual_volatility / np.sqrt(12)

    # Draw all shocks at once: shape (n_paths, months)
    monthly_returns = rng.normal(loc=mu_m, scale=sigma_m,
                                 size=(n_paths, months))

    balances = np.full(n_paths, float(corpus))
    depleted = np.zeros(n_paths, dtype=bool)
    sample_paths = [[] for _ in range(min(n_sample_paths, n_paths))]

    for m in range(months):
        balances *= (1 + monthly_returns[:, m])
        balances -= monthly_withdrawal
        newly_depleted = balances <= 0
        balances[newly_depleted] = 0.0
        depleted |= newly_depleted
        for i in range(len(sample_paths)):
            sample_paths[i].append(round(float(balances[i]), 2))

    pct = np.percentile(balances, [5, 25, 50, 75, 95])
    return MonteCarloResult(
        years=years,
        n_paths=n_paths,
        percentile_5=round(float(pct[0]), 2),
        percentile_25=round(float(pct[1]), 2),
        percentile_50=round(float(pct[2]), 2),
        percentile_75=round(float(pct[3]), 2),
        percentile_95=round(float(pct[4]), 2),
        prob_depletion=round(float(depleted.mean()), 4),
        sample_paths=sample_paths,
    )


# ---------------------------------------------------------------------------
# Portfolio aggregation
# ---------------------------------------------------------------------------

def build_fixed_income_book(allocations: list) -> dict:
    """
    Aggregate a list of InstrumentResult objects into portfolio totals.

    `allocations` is a list of InstrumentResult (already computed by the
    caller). This function only sums -- it makes no allocation decisions.
    """
    total_principal = sum(a.principal for a in allocations)
    gross_annual = sum(a.annual_interest for a in allocations)
    post_tax_annual = sum(a.post_tax_annual_interest for a in allocations)
    blended_yield = (gross_annual / total_principal) if total_principal else 0.0

    return {
        "instruments": allocations,
        "total_principal": round(total_principal, 2),
        "gross_annual_income": round(gross_annual, 2),
        "gross_monthly_income": round(gross_annual / 12, 2),
        "post_tax_annual_income": round(post_tax_annual, 2),
        "post_tax_monthly_income": round(post_tax_annual / 12, 2),
        "blended_gross_yield": round(blended_yield, 4),
    }


def compound_projection(principal: float, annual_rate: float,
                        years_list: list) -> dict:
    """Simple deterministic compounding snapshots for a fixed-income bucket."""
    return {
        y: round(principal * (1 + annual_rate) ** y, 2)
        for y in years_list
    }
