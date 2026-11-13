"""
Backtesting Page - walk-forward backtests run by the backend (/api/backtest/run), with honest statistics
"""
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from components import render_header, render_stat_card
from components.job_progress import track_job, render_job_outcome
from utils.api_client import get_api_client, LEAGUES
from utils.charts import create_bankroll_chart, create_calibration_chart

JOB_KEY = "bt_job_id"


def _pct(v, digits=1, signed=False):
    if not isinstance(v, (int, float)):
        return "N/A"
    return f"{v * 100:+.{digits}f}%" if signed else f"{v * 100:.{digits}f}%"


def render_backtesting_page():
    """Render the backtesting page"""

    render_header(
        title="📈 Backtesting",
        subtitle="Walk-forward tests on stored history: every prediction uses only data available before the game"
    )

    tab1, tab2 = st.tabs(["🔬 Run Backtest", "📊 Recent Backtests"])
    with tab1:
        render_backtest_runner()
        job = track_job(JOB_KEY, label="Backtest", getter="get_backtest_results")
        if job and job.get("status") not in ("queued", "running"):
            render_job_outcome(job, "Backtest")
            if job.get("status") == "completed" and job.get("result"):
                render_backtest_report(job)
    with tab2:
        render_backtest_history()


def render_backtest_runner():
    """Backtest configuration form"""
    st.markdown("### Configure Backtest")

    with st.form("bt_form", border=False):
        col1, col2 = st.columns(2)
        with col1:
            league = st.selectbox("League", LEAGUES, key="bt_league")
            start_date = st.date_input("Start Date", value=date.today() - timedelta(days=365), key="bt_start")
            end_date = st.date_input("End Date", value=date.today() - timedelta(days=1), key="bt_end")
            bet_types = st.multiselect("Bet Types", ["moneyline", "spread", "total"],
                                       default=["moneyline", "spread", "total"], key="bt_types")
        with col2:
            min_edge = st.slider("Minimum Edge to Bet", min_value=0.0, max_value=0.20, value=0.03, step=0.005,
                                 format="%.3f", key="bt_edge",
                                 help="Bet only when model probability exceeds the no-vig market probability by this much.")
            stake = st.radio("Staking", ["flat", "kelly"], horizontal=True, key="bt_stake",
                             format_func=lambda s: "Flat units" if s == "flat" else "Quarter Kelly (max 5% of bankroll)")
            c1, c2 = st.columns(2)
            with c1:
                bankroll = st.number_input("Starting bankroll ($)", min_value=100.0, value=10000.0, step=500.0,
                                           key="bt_bankroll")
            with c2:
                unit = st.number_input("Unit size ($)", min_value=1.0, value=100.0, step=10.0, key="bt_unit")
            retrain = st.number_input("Retrain every N days (0 = train once)", min_value=0, max_value=365, value=30,
                                      key="bt_retrain")
        submitted = st.form_submit_button("🚀 Run Backtest", type="primary")

    if submitted:
        if end_date < start_date:
            st.error("End date is before start date.")
            return
        if not bet_types:
            st.error("Pick at least one bet type.")
            return
        body = {"league": league, "start_date": start_date.strftime("%Y%m%d"), "end_date": end_date.strftime("%Y%m%d"),
                "min_edge": float(min_edge), "stake": stake, "unit": float(unit), "bankroll": float(bankroll),
                "bet_types": bet_types, "retrain_every_days": int(retrain)}
        res = get_api_client().run_backtest(body)
        if res.get("success"):
            st.session_state[JOB_KEY] = res["data"]["backtest_id"]
            st.rerun()
        else:
            st.error(f"Could not start backtest: {res.get('error')}")


def _verdict_box(summary: dict):
    verdict = summary.get("verdict", "")
    roi = summary.get("roi")
    ci = summary.get("roi_ci_95")
    p = summary.get("p_value_vs_break_even")
    parts = [f"**Verdict:** {verdict}"] if verdict else []
    if ci and ci[1] < 0:
        parts.append("**The whole 95% CI is below zero: this strategy lost money beyond what chance explains.**")
    if ci:
        parts.append(f"ROI 95% CI: {_pct(ci[0], 2, True)} to {_pct(ci[1], 2, True)}")
    if p is not None:
        parts.append(f"p-value vs break-even hit rate: {p:.4f}")
    if summary.get("break_even_hit_rate") is not None:
        parts.append(f"break-even hit rate {_pct(summary['break_even_hit_rate'])} vs actual {_pct(summary.get('hit_rate'))}")
    text = "  \n".join(parts)
    if ci and ci[0] > 0:
        st.success(text)
    elif roi is not None and roi < 0:
        st.error(text)
    else:
        st.warning(text)


def render_backtest_report(job: dict):
    """Render a finished backtest result"""
    r = job["result"]
    pm = r.get("prediction_metrics", {})
    betting = r.get("betting", {})
    overall = betting.get("overall", {})
    settings = r.get("settings", {})
    bankroll0 = settings.get("bankroll", 10000.0)

    st.markdown(f"### Results: {r.get('league')} {r.get('start_date')} to {r.get('end_date')}")
    src = r.get("model_source") or {}
    if src:
        st.caption("Predictions from: " + ", ".join(f"{k} ({v:,} games)" for k, v in src.items())
                   + f" | {r.get('walk_forward_blocks', 0)} walk-forward blocks")
    if src.get("elo_baseline"):
        st.info("Some games were predicted with the Elo baseline because there was not yet enough earlier history to train.")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        render_stat_card("Games Tested", f"{r.get('games', 0):,}", icon="🎮")
    with col2:
        mb = r.get("market_baseline", {})
        delta = None
        if mb.get("accuracy") is not None and pm.get("accuracy") is not None:
            delta = f"{(pm['accuracy'] - mb['accuracy']) * 100:+.1f} pts vs market"
        render_stat_card("Prediction Accuracy", _pct(pm.get("accuracy")), delta=delta,
                         delta_type="positive" if delta and not delta.startswith("-") else "negative", icon="🎯")
    with col3:
        render_stat_card("Betting ROI", _pct(overall.get("roi"), 2, True), icon="💰")
    with col4:
        render_stat_card("Max Drawdown", _pct(betting.get("max_drawdown_pct")), icon="📉")

    _verdict_box(overall)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Bets", f"{overall.get('bets', 0):,}")
    c2.metric("Record (W-L-P)", f"{overall.get('wins', 0)}-{overall.get('losses', 0)}-{overall.get('pushes', 0)}")
    c3.metric("Profit", f"${overall.get('profit', 0):,.2f}")
    c4.metric("Final Bankroll", f"${betting.get('final_bankroll', bankroll0):,.2f}")

    curve = betting.get("bankroll_curve") or []
    if curve:
        st.plotly_chart(create_bankroll_chart(curve, bankroll0, "Bankroll Curve"), width="stretch",
                        config={'displayModeBar': False}, key="bt_bankroll_chart")
    else:
        st.info("No bets met the minimum edge, so there is no bankroll curve.")

    by_type = betting.get("by_type") or {}
    if by_type:
        st.markdown("**By Bet Type**")
        rows = [{"Bet Type": t, "Bets": s.get("bets"), "Wins": s.get("wins"), "Losses": s.get("losses"),
                 "Pushes": s.get("pushes"), "Hit Rate": s.get("hit_rate"), "Staked": s.get("staked"),
                 "Profit": s.get("profit"), "ROI": s.get("roi"),
                 "ROI 95% CI": (f"{_pct(s['roi_ci_95'][0], 1, True)} to {_pct(s['roi_ci_95'][1], 1, True)}"
                                if s.get("roi_ci_95") else "n/a"),
                 "p-value": s.get("p_value_vs_break_even"), "Verdict": s.get("verdict")}
                for t, s in by_type.items()]
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True, column_config={
            "Hit Rate": st.column_config.NumberColumn(format="percent"),
            "ROI": st.column_config.NumberColumn(format="percent"),
            "Staked": st.column_config.NumberColumn(format="dollar"),
            "Profit": st.column_config.NumberColumn(format="dollar"),
            "p-value": st.column_config.NumberColumn(format="%.4f"),
        })

    col_left, col_right = st.columns(2)
    with col_left:
        st.markdown("**Prediction Quality**")
        rows = [{"Source": "Model", **{k: pm.get(k) for k in ("accuracy", "roc_auc", "brier", "log_loss", "n")}}]
        if r.get("model_on_market_games"):
            rows.append({"Source": "Model (games with odds)", **{k: r["model_on_market_games"].get(k)
                                                               for k in ("accuracy", "roc_auc", "brier", "log_loss", "n")}})
        if r.get("market_baseline"):
            rows.append({"Source": "Market implied odds", **{k: r["market_baseline"].get(k)
                                                           for k in ("accuracy", "roc_auc", "brier", "log_loss", "n")}})
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True, column_config={
            "accuracy": st.column_config.NumberColumn("Accuracy", format="percent"),
            "roc_auc": st.column_config.NumberColumn("ROC-AUC", format="%.3f"),
            "brier": st.column_config.NumberColumn("Brier", format="%.4f"),
            "log_loss": st.column_config.NumberColumn("Log-loss", format="%.4f"),
            "n": st.column_config.NumberColumn("Games"),
        })
    with col_right:
        if r.get("calibration_curve"):
            st.plotly_chart(create_calibration_chart(r["calibration_curve"], "Backtest Calibration"),
                            width="stretch", config={'displayModeBar': False}, key="bt_calibration")

    bets = r.get("bets") or []
    st.markdown(f"**Bets** ({len(bets):,} shown{' (most recent 500)' if overall.get('bets', 0) > len(bets) else ''})")
    if bets:
        st.dataframe(pd.DataFrame(bets), width="stretch", hide_index=True, height=350, column_config={
            "model_probability": st.column_config.NumberColumn("Model Prob", format="percent"),
            "edge": st.column_config.NumberColumn("Edge", format="percent"),
            "stake": st.column_config.NumberColumn("Stake", format="dollar"),
            "pnl": st.column_config.NumberColumn("P&L", format="dollar"),
            "bankroll": st.column_config.NumberColumn("Bankroll", format="dollar"),
        })
        csv = get_api_client().get_backtest_csv(job["job_id"])
        if csv.get("success"):
            st.download_button("📥 Download Bets CSV", data=csv["data"],
                               file_name=csv.get("filename") or f"backtest_{job['job_id'][:8]}.csv",
                               mime="text/csv", key="bt_csv")
        else:
            st.caption(f"CSV export unavailable: {csv.get('error')}")


def render_backtest_history():
    """Recent backtest jobs from the backend"""
    st.markdown("### Recent Backtests")
    res = get_api_client().list_backtests(limit=20)
    if not res.get("success"):
        st.error(f"Could not load backtests: {res.get('error')}")
        return
    items = res["data"].get("backtests", [])
    if not items:
        st.info("No backtests have been run yet.")
        return
    df = pd.DataFrame([{
        "Started": (b.get("created_at") or "")[:19].replace("T", " "),
        "League": b.get("league"),
        "Range": f"{(b.get('params') or {}).get('start_date', '')} to {(b.get('params') or {}).get('end_date') or 'yesterday'}",
        "Status": b.get("status"),
        "Progress": b.get("progress") or 0,
        "Summary": b.get("summary") or b.get("message"),
        "ID": b.get("job_id"),
    } for b in items])
    st.dataframe(df, width="stretch", hide_index=True, column_config={
        "Progress": st.column_config.ProgressColumn("Progress", min_value=0.0, max_value=1.0, format="percent"),
    })
    finished = [b for b in items if b.get("status") == "completed"]
    if finished:
        labels = {b["job_id"]: f"{b.get('league')} | {(b.get('created_at') or '')[:16].replace('T', ' ')} | {b.get('summary') or ''}"
                  for b in finished}
        pick = st.selectbox("Open a finished backtest", list(labels), format_func=lambda k: labels[k], key="bt_pick")
        if st.button("Show results", key="bt_show"):
            st.session_state[JOB_KEY] = pick
            st.rerun()
        if st.session_state.get(JOB_KEY) == pick:
            st.caption("This backtest's full report is shown on the **Run Backtest** tab.")
