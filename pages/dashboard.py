"""
Main Dashboard Page - overview of today's predictions and tracked model performance across all leagues
"""
import pandas as pd
import streamlit as st

from components import render_header, render_stat_card, render_prediction_card
from utils.charts import create_accuracy_by_sport_radar, create_accuracy_series_chart
from utils.api_client import cached, LEAGUES
from config import SPORTS

MODEL_LABELS = {"logistic_regression": "Logistic Regression", "random_forest": "Random Forest",
                "xgboost": "XGBoost", "lightgbm": "LightGBM", "neural_network": "Neural Network"}


def _pct(v, digits=1):
    return f"{v * 100:.{digits}f}%" if isinstance(v, (int, float)) else "N/A"


def _load():
    """Fetch everything the dashboard needs (cached 60 s)."""
    models = cached("get_models")
    preds, acc = {}, {}
    if not models.get("success") and "Connection failed" in str(models.get("error")):
        return models, {lg: models for lg in LEAGUES}, {lg: models for lg in LEAGUES}
    for lg in LEAGUES:
        preds[lg] = cached("get_predictions", league=lg)
        acc[lg] = cached("get_accuracy", league=lg, days=30)
    return models, preds, acc


def _merge_series(acc: dict, leagues: list) -> list:
    by_day = {}
    for lg in leagues:
        res = acc.get(lg) or {}
        for s in (res.get("data") or {}).get("series", []) if res.get("success") else []:
            d = by_day.setdefault(s["date"], [0, 0])
            d[0] += s["correct"]
            d[1] += s["games"]
    out, cc, cn = [], 0, 0
    for day in sorted(by_day):
        c, n = by_day[day]
        cc += c
        cn += n
        out.append({"date": day, "correct": c, "games": n, "accuracy": c / n, "cumulative_accuracy": cc / cn})
    return out


def render_dashboard():
    """Render the main dashboard page"""

    render_header(
        title="Dashboard",
        subtitle="Today's predictions and tracked model performance across all leagues"
    )

    with st.spinner("Loading predictions and model status..."):
        models_res, preds, acc = _load()

    if not models_res.get("success") and not any(p.get("success") for p in preds.values()):
        st.error(f"Could not reach the backend: {models_res.get('error')}")
        st.info("Start the backend and make sure API_BASE_URL points at it.")
        return

    league_models = (models_res.get("data") or {}).get("leagues", {})
    today = {lg: (r.get("data") or {}).get("predictions", []) if r.get("success") else [] for lg, r in preds.items()}
    failed = [lg for lg, r in preds.items() if not r.get("success")]
    if failed:
        st.warning(f"Could not load today's predictions for: {', '.join(failed)}")

    all_games = [dict(p, _league=lg) for lg, ps in today.items() for p in ps]
    upcoming = [p for p in all_games if not p.get("is_final")]
    week = _merge_series(acc, LEAGUES)[-7:]
    week_games = sum(s["games"] for s in week)
    week_acc = (sum(s["correct"] for s in week) / week_games) if week_games else None
    trained = [lg for lg in LEAGUES if league_models.get(lg, {}).get("is_trained")]
    sims = next(((p.get("betting") or {}).get("simulation", {}).get("simulations_run") for p in all_games
                 if (p.get("betting") or {}).get("simulation")), None)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        render_stat_card(title="Today's Predictions", value=str(len(all_games)),
                         delta=f"{len([p for p in all_games if p.get('is_live')])} live now", icon="📊")
    with col2:
        render_stat_card(title="Tracked Accuracy (7 Days)", value=_pct(week_acc),
                         delta=f"{week_games} settled games" if week_games else "No settled games yet", icon="🎯")
    with col3:
        render_stat_card(title="Trained Models", value=f"{len(trained)} / {len(LEAGUES)}",
                         delta=", ".join(trained) if trained else "Heuristic fallback in use", icon="🤖")
    with col4:
        render_stat_card(title="Simulations Run", value=f"{sims:,}" if sims else "N/A", delta="Per prediction",
                         icon="🔬")

    st.divider()

    col_left, col_right = st.columns([2, 1])

    with col_left:
        st.subheader("🔥 Top Predictions Today")
        st.caption("Highest confidence picks across all leagues")
        top = sorted(upcoming, key=lambda p: p.get("confidence") or 0, reverse=True)[:3]
        if not top:
            st.info("No upcoming games today in any league.")
        for pred in top:
            lg = pred["_league"]
            hf = (pred.get("team_form") or {}).get("home_form", {})
            af = (pred.get("team_form") or {}).get("away_form", {})
            st.markdown(f"**{SPORTS.get(lg, {}).get('icon', '🏆')} {lg}**")
            render_prediction_card(
                home_team=pred.get("home_team", ""), away_team=pred.get("away_team", ""),
                home_prob=pred.get("home_win_probability", 0.5), confidence=pred.get("confidence", 0.5),
                game_time=pred.get("status_detail") or pred.get("game_time", ""),
                home_record=hf.get("season_record") or hf.get("record_last_10", ""),
                away_record=af.get("season_record") or af.get("record_last_10", ""),
                show_details=False,
            )
            if pred.get("key_factors"):
                st.caption("Key factors: " + " | ".join(pred["key_factors"][:3]))

    with col_right:
        st.subheader("📈 Model Performance")
        if len(trained) >= 3:
            radar = create_accuracy_by_sport_radar(
                trained, [league_models[lg].get("accuracy") or 0.5 for lg in trained],
                [league_models[lg].get("roc_auc") or 0.5 for lg in trained])
            radar.update_polars(radialaxis=dict(range=[0.4, 0.8]))
            st.plotly_chart(radar, width="stretch", config={'displayModeBar': False}, key="radar_dashboard")
        rows = [{"League": lg,
                 "Holdout Acc.": league_models.get(lg, {}).get("accuracy"),
                 "ROC-AUC": league_models.get(lg, {}).get("roc_auc"),
                 "Status": "Trained" if lg in trained else "Untrained"} for lg in LEAGUES]
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True, column_config={
            "Holdout Acc.": st.column_config.NumberColumn(format="percent"),
            "ROC-AUC": st.column_config.NumberColumn(format="%.3f"),
        })

        st.subheader("Ensemble Weights")
        if trained:
            wl = st.selectbox("League", trained, key="dash_weights_league", label_visibility="collapsed")
            for m in league_models[wl].get("models_in_ensemble", []):
                w = m.get("weight") or 0
                st.progress(min(max(w, 0.0), 1.0), text=f"{m.get('label') or MODEL_LABELS.get(m['name'], m['name'])}: {w * 100:.0f}%")
        else:
            st.info("No trained models yet. Train one on the Models page.")

    st.divider()

    st.subheader("📊 Tracked Accuracy Trend (30 Days)")
    trend_league = st.selectbox("League", ["All"] + LEAGUES, key="dash_trend_league")
    series = _merge_series(acc, LEAGUES if trend_league == "All" else [trend_league])
    if series:
        st.plotly_chart(create_accuracy_series_chart(series), width="stretch",
                        config={'displayModeBar': False}, key="trend_dashboard")
        st.caption("Accuracy of stored pre-game predictions once games went final.")
    else:
        st.info("No settled predictions yet. Accuracy appears here once predicted games have finished "
                "(predictions are stored when they are made, then graded automatically).")

    st.subheader("🏆 League Breakdown")
    cols = st.columns(4)
    for col, lg in zip(cols, LEAGUES):
        a = (acc[lg].get("data") or {}) if acc[lg].get("success") else {}
        with col:
            st.metric(label=f"{SPORTS.get(lg, {}).get('icon', '')} {lg} (30d)",
                      value=_pct(a.get("accuracy")),
                      delta=f"{len(today.get(lg, []))} games today", delta_color="off")
            st.caption(f"{a.get('settled_predictions', 0)} settled predictions")
