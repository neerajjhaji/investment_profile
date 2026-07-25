"""
Smoke + correctness tests for math_engine. Run: pytest -q
These lock in the arithmetic and the statutory-limit / eligibility behaviour.
"""

import math_engine as me


def test_pomis_caps_at_single_limit():
    r = me.pomis(2_000_000, joint=False, slab_rate=0.30)
    assert r.principal == me.POMIS_LIMIT_SINGLE
    assert "exceeds" in r.notes
    # Monthly gross interest = principal * rate / 12
    assert round(r.monthly_interest, 2) == round(
        me.POMIS_LIMIT_SINGLE * me.POMIS_RATE / 12, 2)


def test_pomis_joint_limit_higher():
    r = me.pomis(2_000_000, joint=True, slab_rate=0.30)
    assert r.principal == me.POMIS_LIMIT_JOINT


def test_scss_requires_age_60():
    young = me.scss(1_000_000, age=45, slab_rate=0.20)
    assert young.principal == 0
    assert "Not eligible" in young.notes

    ok = me.scss(1_000_000, age=65, slab_rate=0.20)
    assert ok.principal == 1_000_000
    assert ok.annual_interest > 0


def test_post_tax_less_than_gross_for_slab_instruments():
    r = me.fixed_deposit(1_000_000, slab_rate=0.30)
    assert r.post_tax_annual_interest < r.annual_interest


def test_swp_depletes_when_withdrawal_exceeds_growth():
    # Withdraw aggressively from a tiny corpus with zero growth -> depletes.
    res = me.simulate_swp(120_000, monthly_withdrawal=20_000,
                          annual_return=0.0, years=5)
    assert res.corpus_depleted
    assert res.depletion_month is not None and res.depletion_month <= 6


def test_sequence_of_returns_order_matters():
    stress = me.sequence_of_returns_stress_test(
        10_000_000, monthly_withdrawal=60_000, annual_return=0.12, years=15)
    # An early crash should leave <= corpus of the same shocks applied late.
    assert stress["crash_-20_y1_2"].ending_corpus <= stress["good_first"].ending_corpus
    score = me.sequence_sensitivity_score(stress)
    assert 0 <= score <= 100


def test_monte_carlo_deterministic_with_seed():
    a = me.monte_carlo_swp(5_000_000, 25_000, 0.12, 0.18, 10, n_paths=500, seed=7)
    b = me.monte_carlo_swp(5_000_000, 25_000, 0.12, 0.18, 10, n_paths=500, seed=7)
    assert a.percentile_50 == b.percentile_50
    assert 0.0 <= a.prob_depletion <= 1.0


def test_build_book_sums_correctly():
    instruments = [
        me.pomis(900_000, joint=False, slab_rate=0.30),
        me.fixed_deposit(1_000_000, slab_rate=0.30),
    ]
    book = me.build_fixed_income_book(instruments)
    assert book["total_principal"] == 1_900_000
    assert book["gross_annual_income"] > book["post_tax_annual_income"]
