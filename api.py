"""
api.py
======
Optional FastAPI backend for ArthaLab.

The Streamlit app (`app.py`) calls the math engine directly and does not
require this service. This backend is provided so the same deterministic
models can be consumed as a JSON API (e.g. by another frontend or for
automated scenario testing).

Run:
    uvicorn api:app --reload --port 8000

Then, e.g.:
    curl -X POST localhost:8000/simulate -H 'Content-Type: application/json' \
         -d '{"corpus": 10000000, "age": 62, "joint": true, "slab_rate": 0.30}'

NOTE: This service performs arithmetic on user-supplied assumptions. It does
not provide investment advice and is not a SEBI RIA.
"""

from __future__ import annotations

from typing import Optional

from fastapi import FastAPI
from pydantic import BaseModel, Field

import math_engine as me

app = FastAPI(
    title="ArthaLab API",
    description="Educational financial scenario simulator. Not investment "
                "advice; not a SEBI Registered Investment Adviser.",
    version="1.0.0",
)

DISCLAIMER = (
    "Educational simulation only. Outputs are arithmetic on user-supplied "
    "assumptions, not investment advice, and market-linked figures are not "
    "guaranteed. Not a SEBI Registered Investment Adviser."
)


class Allocation(BaseModel):
    pomis: float = Field(0, ge=0)
    scss: float = Field(0, ge=0)
    frsb: float = Field(0, ge=0)
    fd: float = Field(0, ge=0)
    debt: float = Field(0, ge=0)
    swp: float = Field(0, ge=0)


class SimulationRequest(BaseModel):
    corpus: float = Field(..., gt=0, description="Total corpus in INR")
    age: int = Field(45, ge=18, le=100)
    joint: bool = Field(False, description="POMIS joint holding")
    slab_rate: float = Field(0.30, ge=0, le=0.45, description="Marginal slab")
    allocation: Allocation = Allocation(
        pomis=15, scss=15, frsb=10, fd=10, debt=10, swp=40)
    equity_return: float = Field(0.12, description="Assumed equity CAGR")
    equity_vol: float = Field(0.18, description="Annualised volatility")
    swp_rate: float = Field(0.06, description="SWP withdrawal rate p.a.")
    horizon_years: int = Field(15, ge=1, le=40)
    mc_paths: int = Field(2000, ge=100, le=20000)
    seed: Optional[int] = 42


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "disclaimer": DISCLAIMER}


@app.post("/simulate")
def simulate(req: SimulationRequest) -> dict:
    a = req.allocation
    amt = {k: req.corpus * getattr(a, k) / 100.0
           for k in ("pomis", "scss", "frsb", "fd", "debt", "swp")}

    instruments = [
        me.pomis(amt["pomis"], joint=req.joint, slab_rate=req.slab_rate),
        me.scss(amt["scss"], age=req.age, slab_rate=req.slab_rate),
        me.frsb(amt["frsb"], slab_rate=req.slab_rate),
        me.fixed_deposit(amt["fd"], slab_rate=req.slab_rate),
        me.low_duration_fund(amt["debt"], slab_rate=req.slab_rate),
    ]
    book = me.build_fixed_income_book(instruments)

    swp_corpus = amt["swp"]
    monthly_withdrawal = swp_corpus * req.swp_rate / 12.0

    stress = me.sequence_of_returns_stress_test(
        swp_corpus, monthly_withdrawal, req.equity_return, req.horizon_years)
    sensitivity = me.sequence_sensitivity_score(stress)
    mc = me.monte_carlo_swp(
        swp_corpus, monthly_withdrawal, req.equity_return, req.equity_vol,
        req.horizon_years, n_paths=req.mc_paths, seed=req.seed)

    return {
        "disclaimer": DISCLAIMER,
        "allocation_inr": {k: round(v, 2) for k, v in amt.items()},
        "fixed_income": {
            "blended_gross_yield": book["blended_gross_yield"],
            "post_tax_monthly_income": book["post_tax_monthly_income"],
            "post_tax_annual_income": book["post_tax_annual_income"],
            "instruments": [i.as_dict() for i in instruments],
        },
        "swp": {
            "bucket_corpus": round(swp_corpus, 2),
            "monthly_withdrawal": round(monthly_withdrawal, 2),
            "sequence_sensitivity_score": sensitivity,
            "stress_test": {
                key: {
                    "label": r.label,
                    "ending_corpus": r.ending_corpus,
                    "corpus_depleted": r.corpus_depleted,
                    "depletion_month": r.depletion_month,
                    "total_withdrawn": r.total_withdrawn,
                } for key, r in stress.items()
            },
            "monte_carlo": {
                "n_paths": mc.n_paths,
                "percentile_5": mc.percentile_5,
                "percentile_50": mc.percentile_50,
                "percentile_95": mc.percentile_95,
                "prob_depletion": mc.prob_depletion,
            },
        },
        "total_modelled_monthly_cash_flow": round(
            book["post_tax_monthly_income"] + monthly_withdrawal, 2),
    }
