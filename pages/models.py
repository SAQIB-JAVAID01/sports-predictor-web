"""
Models Management Page - real per-league ensemble metrics, calibration, feature importance and training jobs
"""
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from components import render_header, render_stat_card, render_model_card
from components.job_progress import track_job, render_job_outcome
from utils.api_client import get_api_client, clear_cache, LEAGUES
from utils.charts import (
    create_model_performance_chart, create_calibration_chart, create_feature_importance_chart
)
from utils.export import export_model_performance_report
from config import SPORTS, ADMIN_TOKEN

MODEL_COLORS = {
    "logistic_regression": "#FF6B6B", "random_forest": "#4ECDC4", "xgboost": "#45B7D1",
    "lightgbm": "#96CEB4", "neural_network": "#C792EA", "gradient_boosting": "#FFB86C",
}


def _pct(v, digits=1):
    return f"{v * 100:.{digits}f}%" if isinstance(v, (int, float)) else "N/A"


def _num(v, digits=3):
    return f"{v:.{digits}f}" if isinstance(v, (int, float)) else "N/A"


def _ago(iso: str) -> str:
    if not iso:
        return "Never"
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        secs = (datetime.now(timezone.utc) - dt).total_seconds()
    except Exception:
        return str(iso)
    if secs < 3600:
        return f"{int(secs // 60)}m ago"
    if secs < 86400:
        return f"{int(secs // 3600)}h ago"
    return f"{int(secs // 86400)}d ago"


def render_models_page():
    """Render the models management page"""

    render_header(
        title="Model Management",
        subtitle="Per-league ensemble models: validation metrics, calibration and training"
    )

    client = get_api_client()
    res = client.get_models()
    if not res.get("success"):
        st.error(f"Could not load models: {res.get('error')}")
        st.info("Make sure the backend is running and API_BASE_URL points at it.")
        return
    leagues = res["data"].get("leagues", {})

    league = st.radio("League", LEAGUES, horizontal=True, key="models_league",
                      format_func=lambda lg: f"{SPORTS.get(lg, {}).get('icon', '')} {lg}")
    summary = leagues.get(league, {})

    jobs_res = client.list_jobs(limit=20, kind="train")
    train_jobs = jobs_res.get("data", {}).get("jobs", []) if jobs_res.get("success") else []
    active_jobs = [j for j in train_jobs if j.get("status") in ("queued", "running")]

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        trained = sum(1 for s in leagues.values() if s.get("is_trained"))
        render_stat_card(title="Trained Leagues", value=f"{trained} / {len(LEAGUES)}", icon="🤖")
    with col2:
        render_stat_card(title=f"{league} Holdout Accuracy",
                         value=_pct(summary.get("accuracy")) if summary.get("is_trained") else "Untrained",
                         icon="🎯")
    with col3:
        render_stat_card(title=f"{league} Last Training", value=_ago(summary.get("training_date")), icon="⏱️")
    with col4:
        render_stat_card(title="Training Jobs Running", value=str(len(active_jobs)), icon="📋")

    st.divider()

    tab1, tab2, tab3 = st.tabs(["Model Overview", "Calibration & Features", "Training"])

    perf = None
    if summary.get("is_trained"):
        pres = client.get_model_performance(league)
        perf = pres.get("data") if pres.get("success") else None
        if not pres.get("success"):
            st.warning(f"Could not load detailed performance: {pres.get('error')}")

    with tab1:
        render_model_overview(league, summary, perf, leagues)
    with tab2:
        render_calibration(league, summary, perf)
    with tab3:
        render_model_training(league, summary, perf, train_jobs)


def _untrained_message(league: str, summary: dict):
    stored = summary.get("stored_final_games", 0) or 0
    need = summary.get("min_training_games", 150)
    st.warning(
        f"No trained {league} model yet. Predictions currently use the fallback "
        f"**{summary.get('description', 'heuristic model')}**."
    )
    if stored >= need:
        st.info(f"{stored:,} completed {league} games are stored, enough to train. Start a job in the **Training** tab.")
    else:
        st.info(f"Only {stored:,} completed {league} games are stored ({need} needed). "
                f"Use **Training > Backfill history first** to fetch past seasons, then train.")


def render_model_overview(league: str, summary: dict, perf: dict, leagues: dict):
    """Per-model comparison for the selected league plus a status table for all leagues"""

    if not summary.get("is_trained"):
        _untrained_message(league, summary)
    else:
        models = summary.get("models_in_ensemble", [])
        st.subheader(f"{league} Ensemble: Per-Model Comparison")
        st.caption(f"Out-of-fold metrics over {summary.get('n_samples', 0):,} games "
                   f"({' to '.join(summary.get('date_range') or [])}). Weights are learned from validation log-loss.")

        col_chart, col_export = st.columns([4, 1])
        with col_chart:
            names = [m.get("label", m["name"]) for m in models]
            accs = [m.get("accuracy") or 0 for m in models]
            colors = [MODEL_COLORS.get(m["name"], "#0078D4") for m in models]
            if models:
                st.plotly_chart(create_model_performance_chart(names, accs, colors), width="stretch",
                                config={'displayModeBar': False}, key="models_perf_chart")
        with col_export:
            st.write("")
            pdf = export_model_performance_report(
                [{"name": m.get("label", m["name"]), "accuracy": m.get("accuracy") or 0,
                  "roc_auc": m.get("roc_auc") or 0, "weight": m.get("weight") or 0, "status": "Active"}
                 for m in models], league)
            st.download_button("📥 Export Report", data=pdf, file_name=f"{league}_model_report.pdf",
                               mime="application/pdf", key="models_export_pdf")

        col1, col2 = st.columns(2)
        for i, m in enumerate(models):
            with col1 if i % 2 == 0 else col2:
                render_model_card(
                    model_name=m.get("label", m["name"]),
                    accuracy=m.get("accuracy") or 0,
                    weight=m.get("weight") or 0,
                    status="Active" if (m.get("weight") or 0) > 0 else "Inactive",
                    color=MODEL_COLORS.get(m["name"], "#0078D4"),
                    last_trained=f"Trained {_ago(summary.get('training_date'))} | Brier {_num(m.get('brier'))} | Log-loss {_num(m.get('log_loss'))}",
                    roc_auc=m.get("roc_auc"),
                )

        st.subheader("Ensemble vs Baselines")
        metrics = (perf or {}).get("metrics", {})
        rows = []
        for m in models:
            rows.append({"Model": m.get("label", m["name"]), "Accuracy": m.get("accuracy"), "ROC-AUC": m.get("roc_auc"),
                         "Brier": m.get("brier"), "Log-loss": m.get("log_loss"), "Weight": m.get("weight")})
        for key, label in [("ensemble_uncalibrated", "Ensemble (out-of-fold)"),
                           ("ensemble_calibrated_holdout", "Ensemble (calibrated, holdout)")]:
            mm = metrics.get(key)
            if mm:
                rows.append({"Model": label, "Accuracy": mm.get("accuracy"), "ROC-AUC": mm.get("roc_auc"),
                             "Brier": mm.get("brier"), "Log-loss": mm.get("log_loss"), "Weight": None})
        base = metrics.get("baselines", {})
        if isinstance(base.get("home_team_always"), (int, float)):
            rows.append({"Model": "Baseline: always pick home", "Accuracy": base["home_team_always"],
                         "ROC-AUC": None, "Brier": None, "Log-loss": None, "Weight": None})
        if isinstance(base.get("market_implied"), dict):
            mi = base["market_implied"]
            rows.append({"Model": "Baseline: market implied odds", "Accuracy": mi.get("accuracy"),
                         "ROC-AUC": mi.get("roc_auc"), "Brier": mi.get("brier"), "Log-loss": mi.get("log_loss"),
                         "Weight": None})
        if rows:
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True, column_config={
                "Accuracy": st.column_config.NumberColumn("Accuracy", format="percent"),
                "ROC-AUC": st.column_config.NumberColumn("ROC-AUC", format="%.3f"),
                "Brier": st.column_config.NumberColumn("Brier", format="%.4f"),
                "Log-loss": st.column_config.NumberColumn("Log-loss", format="%.4f"),
                "Weight": st.column_config.NumberColumn("Weight", format="percent"),
            })
        if isinstance(base.get("market_implied"), dict) and summary.get("accuracy") is not None:
            if (summary.get("roc_auc") or 0) < (base["market_implied"].get("roc_auc") or 0):
                st.caption("Note: the market-implied baseline currently ranks games better (higher ROC-AUC) than "
                           "the model on the same games.")

    st.subheader("All Leagues")
    table = []
    for lg in LEAGUES:
        s = leagues.get(lg, {})
        tracked = s.get("tracked_accuracy") or {}
        table.append({
            "League": lg,
            "Status": "Trained" if s.get("is_trained") else "Untrained (heuristic)",
            "Holdout Accuracy": s.get("accuracy"),
            "ROC-AUC": s.get("roc_auc"),
            "Models": len(s.get("models_in_ensemble") or []),
            "Stored Games": s.get("stored_final_games"),
            "Tracked Accuracy (90d)": tracked.get("accuracy"),
            "Settled Predictions": tracked.get("settled_predictions"),
            "Last Trained": _ago(s.get("training_date")),
        })
    st.dataframe(pd.DataFrame(table), width="stretch", hide_index=True, column_config={
        "Holdout Accuracy": st.column_config.NumberColumn(format="percent"),
        "ROC-AUC": st.column_config.NumberColumn(format="%.3f"),
        "Tracked Accuracy (90d)": st.column_config.NumberColumn(format="percent"),
    })


def render_calibration(league: str, summary: dict, perf: dict):
    """Calibration curve, feature importance and the out-of-fold betting simulation"""
    if not summary.get("is_trained") or not perf:
        _untrained_message(league, summary)
        return
    metrics = perf.get("metrics", {})

    col1, col2 = st.columns(2)
    with col1:
        curve = metrics.get("calibration_curve") or []
        if curve:
            st.plotly_chart(create_calibration_chart(curve, f"{league} Calibration ({metrics.get('calibration_method', '')})"),
                            width="stretch", config={'displayModeBar': False}, key="models_calibration")
            st.caption("Points on the dashed line mean a predicted 60% wins about 60% of the time. "
                       "Marker size reflects the number of games in each bin.")
        else:
            st.info("No calibration data stored for this model.")
    with col2:
        fi = metrics.get("feature_importance") or {}
        if fi:
            st.plotly_chart(create_feature_importance_chart(fi, 15, f"{league} Top Features"),
                            width="stretch", config={'displayModeBar': False}, key="models_feature_importance")
        else:
            st.info("No feature importance stored for this model.")

    st.subheader("Error Metrics")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Margin MAE", _num(metrics.get("margin_mae"), 2))
    c2.metric("Total MAE", _num(metrics.get("total_mae"), 2))
    c3.metric("CV Folds", str(metrics.get("cv_folds", "N/A")))
    c4.metric("Training Time", f"{metrics.get('training_seconds', 0):.1f}s")

    sim = metrics.get("betting_simulation_oof")
    if sim:
        st.subheader("Out-of-Fold Betting Simulation (moneyline, flat stakes)")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Bets", f"{sim.get('bets', 0):,}")
        c2.metric("Hit Rate", _pct(sim.get("hit_rate")))
        c3.metric("ROI", _pct(sim.get("roi"), 2))
        c4.metric("Profit", f"${sim.get('profit', 0):,.2f}")
        if (sim.get("roi") or 0) <= 0:
            st.warning("This model did not show a profitable betting edge in out-of-fold validation. "
                       "Treat recommendations accordingly.")
        st.caption(f"Bets placed when model edge >= {_pct(sim.get('edge_threshold'))}; for a full walk-forward "
                   f"test with CIs use the Backtesting page.")

    if perf.get("history"):
        st.subheader("Training History")
        hist = pd.DataFrame(perf["history"])
        st.dataframe(hist, width="stretch", hide_index=True, column_config={
            "accuracy": st.column_config.NumberColumn("Accuracy", format="percent"),
            "roc_auc": st.column_config.NumberColumn("ROC-AUC", format="%.3f"),
        })


def _admin_credentials_available() -> bool:
    return bool(ADMIN_TOKEN or st.session_state.get("admin_token") or st.session_state.get("api_key"))


def render_model_training(league: str, summary: dict, perf: dict, train_jobs: list):
    """Start a training job and show its progress"""

    st.subheader(f"Train {league} Ensemble")
    st.caption(f"{summary.get('stored_final_games', 0):,} completed games stored "
               f"({summary.get('stored_games_with_odds', 0):,} with closing odds). "
               f"At least {summary.get('min_training_games', 150)} are required.")

    col1, col2 = st.columns(2)
    with col1:
        backfill = st.checkbox("Backfill history first", value=False, key="train_backfill",
                               help="Fetch past seasons of results and odds before training (slower).")
    with col2:
        seasons = st.number_input("Seasons to backfill", min_value=1, max_value=6, value=2, key="train_seasons",
                                  disabled=not backfill)

    if not ADMIN_TOKEN:
        st.text_input("Admin token", type="password", key="admin_token",
                      help="Training is an admin action. Paste the backend ADMIN_TOKEN, or log in with an admin API key.")

    job_key = "models_train_job"
    current = st.session_state.get(job_key)
    running = any(j.get("status") in ("queued", "running") and j.get("league") == league for j in train_jobs)

    if st.button("🚀 Start Training", type="primary", key="train_start", disabled=running):
        if not _admin_credentials_available():
            st.error("Admin credentials required: paste the admin token above or log in with an admin API key.")
        else:
            res = get_api_client().train_model(league, backfill_first=backfill, seasons=int(seasons))
            if res.get("success"):
                st.session_state[job_key] = res["data"]["job_id"]
                st.session_state["models_train_league"] = league
                st.rerun()
            elif res.get("status_code") == 403:
                st.error("The backend rejected the admin credentials (403). Check the admin token.")
            else:
                st.error(f"Could not start training: {res.get('error')}")

    if running and not current:
        st.info(f"A {league} training job is already running.")
        st.session_state[job_key] = next(j["job_id"] for j in train_jobs
                                         if j.get("status") in ("queued", "running") and j.get("league") == league)

    if st.session_state.get(job_key):
        job = track_job(job_key, label=f"Training {st.session_state.get('models_train_league', league)}")
        if job and job.get("status") not in ("queued", "running"):
            render_job_outcome(job, "Training")
            if job.get("status") == "completed" and st.session_state.get("models_train_done") != job["job_id"]:
                st.session_state["models_train_done"] = job["job_id"]
                clear_cache()
                st.rerun()  # refresh metrics with the new model
            if st.button("Dismiss", key="train_dismiss"):
                st.session_state.pop(job_key, None)
                st.rerun()
    elif not running:
        st.info("🎯 No training in progress.")

    st.subheader("Recent Training Jobs")
    if train_jobs:
        df = pd.DataFrame([{
            "Started": (j.get("started_at") or j.get("created_at") or "")[:19].replace("T", " "),
            "League": j.get("league"), "Status": j.get("status"),
            "Progress": j.get("progress") or 0, "Message": j.get("message"),
        } for j in train_jobs])
        st.dataframe(df, width="stretch", hide_index=True, column_config={
            "Progress": st.column_config.ProgressColumn("Progress", min_value=0.0, max_value=1.0, format="percent"),
        })
    else:
        st.caption("No training jobs yet.")
