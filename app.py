"""
app.py
======
ArthaLab: Investment Strategy & Portfolio Simulator (Streamlit frontend).

An educational, interactive *mathematical modelling tool*. It does not give
investment advice, does not act as a SEBI RIA, and clearly separates
guaranteed fixed-income yields from market-linked (SWP) projections whose
outcomes are uncertain.

Run:
    streamlit run app.py
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st

import math_engine as me
from gemini_service import get_service_or_error, GeminiCallError

# ---------------------------------------------------------------------------
# Page config & global styling
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="ArthaLab — Investment Strategy & Portfolio Simulator",
    page_icon="🧮",
    layout="wide",
)

DISCLAIMER = (
    "**Educational simulation only — not investment advice.** ArthaLab is a "
    "mathematical modelling tool. It is **not** a SEBI Registered Investment "
    "Adviser and does not recommend any security, scheme, or allocation. All "
    "figures are hypothetical outputs of *your* assumptions and may be wrong. "
    "Statutory rates, limits, and tax rules change — verify against official "
    "sources. Market-linked returns (SWP, funds) are **not guaranteed** and "
    "can result in loss of capital. Consult a SEBI-registered adviser and a "
    "qualified tax professional before acting."
)


def inr(x: float) -> str:
    """Format a number as INR with Indian-ish grouping (lakh/crore aware)."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return "—"
    return f"₹{x:,.0f}"


def render_footer():
    st.markdown("---")
    st.caption(DISCLAIMER)


# ---------------------------------------------------------------------------
# Sidebar — control panel
# ---------------------------------------------------------------------------

def sidebar_inputs() -> dict:
    st.sidebar.title("🧮 ArthaLab Control Panel")
    st.sidebar.caption("Configure a hypothetical scenario. Nothing here is a "
                       "recommendation.")

    st.sidebar.subheader("Investor profile")
    corpus = st.sidebar.number_input(
        "Total corpus (₹)", min_value=0, value=0, step=100_000,
        help="Total amount you want to model. No default is assumed.",
    )
    age = st.sidebar.number_input("Age", min_value=18, max_value=100, value=45,
                                  help="Used only to test SCSS eligibility (>=60).")
    holding = st.sidebar.radio("POMIS holding type", ["Single", "Joint"],
                               horizontal=True)
    tax_slab = st.sidebar.selectbox(
        "Marginal tax slab", ["10%", "20%", "30%"], index=2,
        help="Applied to slab-taxed interest (POMIS, SCSS, FRSB, FD, debt).",
    )
    slab_rate = {"10%": 0.10, "20%": 0.20, "30%": 0.30}[tax_slab]

    st.sidebar.subheader("Target")
    target_monthly = st.sidebar.number_input(
        "Target monthly cash flow (₹)", min_value=0, value=0, step=5_000,
        help="Your goal, for comparison against modelled output.",
    )

    st.sidebar.subheader("Allocation (% of corpus)")
    st.sidebar.caption("You choose the split. These are inputs, not advice.")
    pct_pomis = st.sidebar.slider("POMIS %", 0, 100, 15)
    pct_scss = st.sidebar.slider("SCSS %", 0, 100, 15)
    pct_frsb = st.sidebar.slider("RBI FRSB %", 0, 100, 10)
    pct_fd = st.sidebar.slider("Bank/Corporate FD %", 0, 100, 10)
    pct_debt = st.sidebar.slider("Low-duration debt fund %", 0, 100, 10)
    pct_swp = st.sidebar.slider("Equity (SWP bucket) %", 0, 100, 40)

    total_pct = pct_pomis + pct_scss + pct_frsb + pct_fd + pct_debt + pct_swp

    st.sidebar.subheader("Rate & risk assumptions")
    st.sidebar.caption("Override statutory defaults to stress-test.")
    pomis_rate = st.sidebar.slider("POMIS rate %", 5.0, 9.0, me.POMIS_RATE * 100, 0.05) / 100
    scss_rate = st.sidebar.slider("SCSS rate %", 6.0, 9.5, me.SCSS_RATE * 100, 0.05) / 100
    frsb_rate = st.sidebar.slider("FRSB rate %", 6.0, 9.5, me.FRSB_RATE * 100, 0.05) / 100
    fd_rate = st.sidebar.slider("FD rate %", 4.0, 9.0, me.FD_RATE * 100, 0.05) / 100
    debt_rate = st.sidebar.slider("Debt fund rate %", 4.0, 9.0, me.LOW_DURATION_RATE * 100, 0.05) / 100

    st.sidebar.subheader("Equity / SWP assumptions")
    equity_return = st.sidebar.slider("Assumed equity return % p.a.", 0.0, 20.0, 12.0, 0.5) / 100
    equity_vol = st.sidebar.slider("Equity volatility % p.a.", 5.0, 40.0, 18.0, 1.0) / 100
    swp_rate = st.sidebar.slider("SWP withdrawal rate % p.a.", 0.0, 12.0, 6.0, 0.25) / 100
    horizon = st.sidebar.slider("Projection horizon (years)", 5, 25, 15)
    mc_paths = st.sidebar.select_slider("Monte Carlo paths",
                                        options=[500, 1000, 2000, 5000],
                                        value=2000)

    return dict(
        corpus=corpus, age=age, joint=(holding == "Joint"),
        slab_rate=slab_rate, tax_slab=tax_slab, target_monthly=target_monthly,
        pct=dict(pomis=pct_pomis, scss=pct_scss, frsb=pct_frsb, fd=pct_fd,
                 debt=pct_debt, swp=pct_swp),
        total_pct=total_pct,
        rates=dict(pomis=pomis_rate, scss=scss_rate, frsb=frsb_rate,
                   fd=fd_rate, debt=debt_rate),
        equity_return=equity_return, equity_vol=equity_vol, swp_rate=swp_rate,
        horizon=horizon, mc_paths=mc_paths,
    )


# ---------------------------------------------------------------------------
# Computation
# ---------------------------------------------------------------------------

def compute_scenario(cfg: dict) -> dict:
    corpus = cfg["corpus"]
    p = cfg["pct"]
    r = cfg["rates"]
    slab = cfg["slab_rate"]

    amt = {k: corpus * v / 100.0 for k, v in p.items()}

    instruments = [
        me.pomis(amt["pomis"], joint=cfg["joint"], slab_rate=slab, rate=r["pomis"]),
        me.scss(amt["scss"], age=cfg["age"], slab_rate=slab, rate=r["scss"]),
        me.frsb(amt["frsb"], slab_rate=slab, rate=r["frsb"]),
        me.fixed_deposit(amt["fd"], slab_rate=slab, rate=r["fd"]),
        me.low_duration_fund(amt["debt"], slab_rate=slab, rate=r["debt"]),
    ]
    book = me.build_fixed_income_book(instruments)

    swp_corpus = amt["swp"]
    monthly_withdrawal = swp_corpus * cfg["swp_rate"] / 12.0

    stress = me.sequence_of_returns_stress_test(
        swp_corpus, monthly_withdrawal, cfg["equity_return"], cfg["horizon"],
    )
    sensitivity = me.sequence_sensitivity_score(stress)

    mc = me.monte_carlo_swp(
        swp_corpus, monthly_withdrawal, cfg["equity_return"],
        cfg["equity_vol"], cfg["horizon"], n_paths=cfg["mc_paths"],
    )

    return dict(
        amounts=amt, instruments=instruments, book=book,
        swp_corpus=swp_corpus, monthly_withdrawal=monthly_withdrawal,
        stress=stress, sensitivity=sensitivity, mc=mc,
    )


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

def donut_allocation(amounts: dict) -> go.Figure:
    labels = {
        "pomis": "POMIS", "scss": "SCSS", "frsb": "RBI FRSB",
        "fd": "FD", "debt": "Debt fund", "swp": "Equity (SWP)",
    }
    df = pd.DataFrame({
        "Instrument": [labels[k] for k in amounts],
        "Amount": [amounts[k] for k in amounts],
    })
    df = df[df["Amount"] > 0]
    fig = px.pie(df, names="Instrument", values="Amount", hole=0.55)
    fig.update_traces(textposition="inside", textinfo="percent+label")
    fig.update_layout(title="Asset allocation (your configured split)",
                      showlegend=True, margin=dict(t=50, b=10))
    return fig


def waterfall_payout(instruments: list, swp_monthly: float) -> go.Figure:
    names = [i.name for i in instruments] + ["Equity SWP draw"]
    values = [i.post_tax_monthly_interest for i in instruments] + [swp_monthly]
    measures = ["relative"] * len(names) + ["total"]
    names.append("Total monthly cash flow")
    values.append(0)
    fig = go.Figure(go.Waterfall(
        orientation="v", measure=measures, x=names, y=values,
        connector={"line": {"color": "rgb(120,120,120)"}},
    ))
    fig.update_layout(
        title="Monthly cash flow build-up (post-tax fixed income + SWP draw)",
        margin=dict(t=50, b=10),
    )
    return fig


def stress_chart(stress: dict, horizon: int) -> go.Figure:
    months = list(range(1, horizon * 12 + 1))
    fig = go.Figure()
    for key, res in stress.items():
        fig.add_trace(go.Scatter(
            x=months, y=res.balance_path, mode="lines", name=res.label,
        ))
    fig.update_layout(
        title="Sequence-of-returns stress test — SWP bucket balance over time",
        xaxis_title="Month", yaxis_title="Bucket balance (₹)",
        margin=dict(t=50, b=10),
    )
    return fig


def monte_carlo_chart(mc: me.MonteCarloResult, horizon: int) -> go.Figure:
    months = list(range(1, horizon * 12 + 1))
    fig = go.Figure()
    for path in mc.sample_paths:
        fig.add_trace(go.Scatter(
            x=months, y=path, mode="lines",
            line=dict(width=1), opacity=0.35, showlegend=False,
            hoverinfo="skip",
        ))
    fig.update_layout(
        title=f"Monte Carlo — {mc.n_paths} simulated SWP paths "
              f"(sample of {len(mc.sample_paths)} shown)",
        xaxis_title="Month", yaxis_title="Bucket balance (₹)",
        margin=dict(t=50, b=10),
    )
    return fig


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    cfg = sidebar_inputs()

    st.title("ArthaLab — Investment Strategy & Portfolio Simulator")
    st.markdown(
        "An **educational scenario simulator** for the Indian financial "
        "ecosystem. You set the assumptions; ArthaLab does the arithmetic and "
        "shows the trade-offs. It does **not** tell you what to buy."
    )

    # Prominent top banner
    st.warning(DISCLAIMER)

    if cfg["corpus"] <= 0:
        st.info("👈 Enter a **total corpus** and an allocation in the control "
                "panel to run the simulation.")
        render_footer()
        return

    if cfg["total_pct"] != 100:
        st.error(
            f"Your allocation sums to **{cfg['total_pct']}%**, not 100%. "
            "Adjust the sliders so the buckets add to 100% for a coherent "
            "scenario. (Showing results scaled to what you entered.)"
        )

    scenario = compute_scenario(cfg)
    book = scenario["book"]
    mc = scenario["mc"]

    # -- KPI cards ------------------------------------------------------
    st.subheader("Key indicators")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Fixed-income blended yield",
              f"{book['blended_gross_yield'] * 100:.2f}%",
              help="Gross, before tax. Weighted across your fixed-income buckets.")
    c2.metric("Post-tax fixed-income / month",
              inr(book["post_tax_monthly_income"]),
              help="Guaranteed-style instruments only, after your slab.")
    c3.metric("Equity SWP draw / month",
              inr(scenario["monthly_withdrawal"]),
              help="A withdrawal, NOT guaranteed income. Depends on markets.")
    c4.metric("Seq-of-returns sensitivity",
              f"{scenario['sensitivity']}/100",
              help="Higher = the SWP outcome depends heavily on the ORDER of "
                   "returns, not just the average.")

    total_month = book["post_tax_monthly_income"] + scenario["monthly_withdrawal"]
    tcol1, tcol2 = st.columns(2)
    tcol1.metric("Total modelled monthly cash flow", inr(total_month))
    if cfg["target_monthly"] > 0:
        gap = total_month - cfg["target_monthly"]
        tcol2.metric("Vs. your target",
                     inr(cfg["target_monthly"]),
                     delta=f"{inr(gap)} {'surplus' if gap >= 0 else 'short'}")

    st.caption("⚠️ The SWP portion is a redemption of capital + growth, not "
               "interest. In a bad market it can shrink your corpus. See the "
               "stress test below.")

    # -- Charts ---------------------------------------------------------
    st.subheader("Visual breakdown")
    g1, g2 = st.columns(2)
    with g1:
        st.plotly_chart(donut_allocation(scenario["amounts"]),
                        use_container_width=True)
    with g2:
        st.plotly_chart(
            waterfall_payout(scenario["instruments"],
                             scenario["monthly_withdrawal"]),
            use_container_width=True)

    st.plotly_chart(stress_chart(scenario["stress"], cfg["horizon"]),
                    use_container_width=True)
    st.plotly_chart(monte_carlo_chart(mc, cfg["horizon"]),
                    use_container_width=True)

    # -- Monte Carlo summary -------------------------------------------
    st.subheader("Monte Carlo outcome distribution (SWP bucket)")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("5th percentile (bad)", inr(mc.percentile_5))
    m2.metric("Median", inr(mc.percentile_50))
    m3.metric("95th percentile (good)", inr(mc.percentile_95))
    m4.metric("Prob. of depletion", f"{mc.prob_depletion * 100:.1f}%",
              help="Share of simulated paths where the SWP bucket hit zero "
                   "before the horizon, under your assumptions.")

    # -- Instrument table ----------------------------------------------
    st.subheader("Instrument-level detail")
    rows = []
    for i in scenario["instruments"]:
        rows.append({
            "Instrument": i.name,
            "Principal": inr(i.principal),
            "Gross yield": f"{i.gross_rate * 100:.2f}%",
            "Annual interest (gross)": inr(i.annual_interest),
            "Monthly (post-tax)": inr(i.post_tax_monthly_interest),
            "Risk": i.risk_level,
            "Liquidity": i.liquidity,
            "Notes": i.notes or "—",
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # Surface any statutory-limit / eligibility warnings prominently.
    warnings = [i.notes for i in scenario["instruments"] if i.notes]
    if warnings:
        st.warning("**Statutory / eligibility notes:**\n\n" +
                   "\n\n".join(f"- {w}" for w in warnings))

    # -- AI insights ----------------------------------------------------
    render_ai_panel(cfg, scenario, total_month)

    render_footer()


def scenario_summary_text(cfg: dict, scenario: dict, total_month: float) -> str:
    lines = [
        f"Corpus: ₹{cfg['corpus']:,.0f}",
        f"Age: {cfg['age']}, POMIS holding: {'joint' if cfg['joint'] else 'single'}, "
        f"tax slab: {cfg['tax_slab']}",
        f"Target monthly cash flow: ₹{cfg['target_monthly']:,.0f}",
        "",
        "Fixed-income instruments (principal @ gross rate -> post-tax monthly):",
    ]
    for i in scenario["instruments"]:
        lines.append(
            f"  - {i.name}: ₹{i.principal:,.0f} @ {i.gross_rate*100:.2f}% "
            f"-> ₹{i.post_tax_monthly_interest:,.0f}/mo post-tax"
            + (f"  [{i.notes}]" if i.notes else "")
        )
    mc = scenario["mc"]
    lines += [
        "",
        f"Equity SWP bucket: ₹{scenario['swp_corpus']:,.0f}, "
        f"withdrawing ₹{scenario['monthly_withdrawal']:,.0f}/mo "
        f"({cfg['swp_rate']*100:.2f}% p.a.), assumed return "
        f"{cfg['equity_return']*100:.1f}% with {cfg['equity_vol']*100:.0f}% vol, "
        f"horizon {cfg['horizon']}y.",
        f"Sequence-of-returns sensitivity score: {scenario['sensitivity']}/100.",
        f"Monte Carlo ({mc.n_paths} paths): median ₹{mc.percentile_50:,.0f}, "
        f"5th pct ₹{mc.percentile_5:,.0f}, 95th pct ₹{mc.percentile_95:,.0f}, "
        f"depletion probability {mc.prob_depletion*100:.1f}%.",
        f"Total modelled monthly cash flow (post-tax FI + SWP draw): "
        f"₹{total_month:,.0f}.",
    ]
    return "\n".join(lines)


def render_ai_panel(cfg: dict, scenario: dict, total_month: float):
    st.subheader("🤖 ArthaLab AI insights")
    st.caption("Gemini explains the mechanics, taxation, and risks of the "
               "scenario YOU configured. It does not recommend allocations.")

    if st.button("Explain this scenario with ArthaLab AI"):
        service, err = get_service_or_error()
        if err:
            st.error(err)
            return
        summary = scenario_summary_text(cfg, scenario, total_month)
        with st.spinner("Asking Gemini…"):
            try:
                resp = service.explain_scenario(summary)
            except GeminiCallError as exc:
                st.error(f"Gemini call failed: {exc}")
                return
        if resp.fell_back:
            st.info(f"Primary model unavailable; used fallback "
                    f"`{resp.model_used}`.")
        else:
            st.caption(f"Model: `{resp.model_used}`")
        st.markdown(resp.text)
        st.caption("AI-generated educational explanation. Verify independently; "
                   "not advice.")


if __name__ == "__main__":
    main()
