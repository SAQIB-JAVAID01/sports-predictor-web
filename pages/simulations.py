"""
Simulations Page - Monte Carlo simulations run by the backend (/api/simulations/run)
"""
from datetime import datetime

import pandas as pd
import streamlit as st

from components import render_header, render_stat_card
from utils.api_client import get_api_client, cached, LEAGUES
from utils.charts import create_histogram_chart
from config import SPORTS

RESULT_KEY = "sim_result"


def _pct(v, digits=1):
    return f"{v * 100:.{digits}f}%" if isinstance(v, (int, float)) else "N/A"


def render_simulations_page():
    """Render the simulations page"""

    render_header(
        title="🔬 Simulations",
        subtitle="Monte Carlo score simulations for real games or custom matchups"
    )

    tab1, tab2 = st.tabs(["🎯 Run Simulation", "📊 Recent Simulations"])
    with tab1:
        render_simulation_runner()
        result = st.session_state.get(RESULT_KEY)
        if result:
            render_simulation_result(result)
    with tab2:
        render_simulation_history()


def _game_label(p: dict) -> str:
    status = "LIVE " if p.get("is_live") else ("FINAL " if p.get("is_final") else "")
    return f"{status}{p.get('away_team')} @ {p.get('home_team')} ({p.get('status_detail') or p.get('game_time', '')})"


def render_simulation_runner():
    """Simulation configuration"""
    st.markdown("### Configure Simulation")

    col1, col2 = st.columns(2)
    with col1:
        league = st.selectbox("League", LEAGUES, key="sim_league",
                              format_func=lambda lg: f"{SPORTS.get(lg, {}).get('icon', '')} {lg}")
        mode = st.radio("Source", ["Today's game", "Custom matchup"], horizontal=True, key="sim_mode")
    with col2:
        n_sims = st.number_input("Number of Simulations", min_value=1000, max_value=200000, value=10000,
                                 step=1000, key="sim_count")
        seed = st.number_input("Random seed (0 = random)", min_value=0, max_value=99999, value=0, key="sim_seed")

    body = {"league": league, "n_simulations": int(n_sims), "seed": int(seed) or None}

    if mode == "Today's game":
        date_val = st.date_input("Game date", value=datetime.now(), key="sim_date")
        with st.spinner(f"Loading {league} games..."):
            res = cached("get_predictions", league=league, date=date_val.strftime("%Y%m%d"))
        if not res.get("success"):
            st.error(f"Could not load games: {res.get('error')}")
            return
        games = [p for p in res["data"].get("predictions", []) if not p.get("is_final")]
        if not games:
            st.info(f"No upcoming or live {league} games on {date_val:%B %d, %Y}. Pick another date or use a custom matchup.")
            return
        by_id = {str(p["game_id"]): p for p in games}
        gid = st.selectbox("Game", list(by_id), format_func=lambda g: _game_label(by_id[g]), key=f"sim_game_{league}")
        game = by_id[gid]
        mo = game.get("market_odds") or {}
        c1, c2 = st.columns(2)
        with c1:
            spread_line = st.number_input("Spread line (home, blank = market)", value=mo.get("spread"), step=0.5,
                                          format="%.1f", key=f"sim_spread_{gid}")
        with c2:
            total_line = st.number_input("Total line (blank = market)", value=mo.get("over_under"), step=0.5,
                                         format="%.1f", key=f"sim_total_{gid}")
        body.update({"game_id": gid, "spread_line": spread_line, "total_line": total_line})
        sim0 = (game.get("betting") or {}).get("simulation") or {}
        st.caption(f"Model: home win {_pct(game.get('home_win_probability'))} | projected "
                   f"{sim0.get('predicted_home_score', '?')}-{sim0.get('predicted_away_score', '?')}")
    else:
        c1, c2 = st.columns(2)
        defaults = {"NBA": (114.0, 111.0, 225.5, -3.5), "NFL": (23.5, 21.0, 44.5, -2.5),
                    "MLB": (4.6, 4.3, 8.5, -1.5), "NHL": (3.2, 2.9, 6.0, -1.5)}[league]
        with c1:
            home_exp = st.number_input("Expected home score", min_value=0.0, value=defaults[0], step=0.5, key=f"sim_he_{league}")
            spread_line = st.number_input("Spread line (home)", value=defaults[3], step=0.5, key=f"sim_cs_{league}")
            home_score = st.number_input("Current home score (live)", min_value=0, value=0, key="sim_hs")
        with c2:
            away_exp = st.number_input("Expected away score", min_value=0.0, value=defaults[1], step=0.5, key=f"sim_ae_{league}")
            total_line = st.number_input("Total line", min_value=0.0, value=defaults[2], step=0.5, key=f"sim_ct_{league}")
            away_score = st.number_input("Current away score (live)", min_value=0, value=0, key="sim_as")
        c3, c4 = st.columns(2)
        with c3:
            period = st.number_input("Period / inning (0 = pre-game)", min_value=0, max_value=20, value=0, key="sim_period")
        with c4:
            clock = st.text_input("Clock remaining (e.g. 8:51)", value="", key="sim_clock")
        body.update({"home_expected": home_exp, "away_expected": away_exp, "spread_line": spread_line,
                     "total_line": total_line, "home_score": int(home_score), "away_score": int(away_score),
                     "period": int(period) or None, "clock": clock or None})

    if st.button("🚀 Run Simulation", type="primary", key="run_sim"):
        with st.spinner(f"Running {int(n_sims):,} simulations..."):
            res = get_api_client().run_simulation(body)
        if res.get("success"):
            st.session_state[RESULT_KEY] = res["data"]
        else:
            st.error(f"Simulation failed: {res.get('error')}")


def _rec_badge(rec: str) -> str:
    return {"OVER": "🟢 OVER", "UNDER": "🔵 UNDER", "HOME": "🏠 HOME", "AWAY": "✈️ AWAY", "PASS": "⚪ PASS"}.get(rec or "", rec or "N/A")


def render_simulation_result(r: dict):
    """Probabilities, histograms and recommendations"""
    st.markdown("---")
    title = r.get("matchup") or f"Custom {r.get('league')} matchup"
    st.markdown(f"### Simulation Results: {title}")
    st.caption(f"{r.get('simulations_run', 0):,} simulations | expected score (home-away) "
               f"{r.get('expected_home')}-{r.get('expected_away')}"
               + (f" | live, {r.get('fraction_remaining', 1) * 100:.0f}% of game remaining" if r.get("is_live") else ""))

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        render_stat_card("Home Win %", _pct(r.get("home_win_probability")), icon="🏠")
    with col2:
        render_stat_card("Away Win %", _pct(r.get("away_win_probability")), icon="✈️")
    with col3:
        render_stat_card("Projected Score", f"{r.get('predicted_home_score')}-{r.get('predicted_away_score')}", icon="📈")
    with col4:
        render_stat_card("Projected Total", f"{r.get('predicted_total')}", icon="Σ")

    if r.get("model_home_probability") is not None:
        st.caption(f"Ensemble model home win probability: {_pct(r['model_home_probability'])}. "
                   f"Tie/OT probability: {_pct(r.get('tie_probability'))}")

    hists = r.get("histograms") or {}
    ou = r.get("over_under") or {}
    sp = r.get("spread") or {}
    col_left, col_right = st.columns(2)
    with col_left:
        if hists.get("total"):
            st.plotly_chart(create_histogram_chart(hists["total"], "Total Points Distribution", "Combined score",
                                                   line=ou.get("line"), line_label="O/U"),
                            width="stretch", config={'displayModeBar': False}, key="sim_hist_total")
    with col_right:
        if hists.get("margin"):
            # spread line is quoted for the home side (-3.5 = home favoured); home covers when margin > -line
            cover = -sp["line"] if isinstance(sp.get("line"), (int, float)) else None
            st.plotly_chart(create_histogram_chart(hists["margin"], "Margin Distribution (home - away)", "Home margin",
                                                   line=cover, line_label="Cover at", color="#00BCF2", ref_zero=True),
                            width="stretch", config={'displayModeBar': False}, key="sim_hist_margin")

    st.markdown("**Recommendations**")
    rows = []
    if ou:
        rows.append({"Market": f"Total {ou.get('line')}", "Recommendation": _rec_badge(ou.get("recommendation")),
                     "Probability": f"Over {_pct(ou.get('over_probability'))} / Under {_pct(ou.get('under_probability'))}",
                     "Edge vs -110": _pct(ou.get("edge_probability")), "Expected Value": ou.get("expected_value"),
                     "Kelly": ou.get("kelly_fraction")})
    if sp:
        rows.append({"Market": f"Spread (home {sp.get('line'):+g})" if isinstance(sp.get("line"), (int, float)) else "Spread",
                     "Recommendation": _rec_badge(sp.get("recommendation")),
                     "Probability": f"Home {_pct(sp.get('home_cover_probability'))} / Away {_pct(sp.get('away_cover_probability'))}",
                     "Edge vs -110": _pct(sp.get("edge_probability")), "Expected Value": sp.get("expected_value"),
                     "Kelly": sp.get("kelly_fraction")})
    if rows:
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True, column_config={
            "Expected Value": st.column_config.NumberColumn(format="%.3f"),
            "Kelly": st.column_config.NumberColumn("Kelly Fraction", format="percent"),
        })
    else:
        st.caption("No lines supplied, so there are no betting recommendations.")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**80% Ranges**")
        st.dataframe(pd.DataFrame([
            {"Quantity": "Total", "Low": (r.get("total_range_80") or [None, None])[0],
             "High": (r.get("total_range_80") or [None, None])[1], "Std Dev": r.get("total_sd")},
            {"Quantity": "Home margin", "Low": (r.get("margin_range_80") or [None, None])[0],
             "High": (r.get("margin_range_80") or [None, None])[1], "Std Dev": r.get("margin_sd")},
        ]), width="stretch", hide_index=True)
    with c2:
        bins = []
        for name in ("total", "margin"):
            h = hists.get(name) or {}
            for i, c in enumerate(h.get("counts") or []):
                bins.append({"histogram": name, "bin_low": h["edges"][i], "bin_high": h["edges"][i + 1], "count": c})
        if bins:
            st.download_button("📥 Export Histograms CSV", data=pd.DataFrame(bins).to_csv(index=False),
                               file_name=f"simulation_{r.get('simulation_id', '')[:8]}.csv", mime="text/csv",
                               key="sim_export")


def render_simulation_history():
    """Recent simulations stored by the backend"""
    st.markdown("### Recent Simulations")
    res = get_api_client().list_jobs(limit=30, kind="simulation")
    if not res.get("success"):
        st.error(f"Could not load simulations: {res.get('error')}")
        return
    jobs = res["data"].get("jobs", [])
    if not jobs:
        st.info("No simulations have been run yet.")
        return
    df = pd.DataFrame([{
        "Time": (j.get("created_at") or "")[:19].replace("T", " "),
        "League": j.get("league"),
        "Game": (j.get("params") or {}).get("game_id") or "custom",
        "Simulations": (j.get("params") or {}).get("n_simulations"),
        "Spread Line": (j.get("params") or {}).get("spread_line"),
        "Total Line": (j.get("params") or {}).get("total_line"),
        "ID": j.get("job_id"),
    } for j in jobs])
    st.dataframe(df, width="stretch", hide_index=True)
    pick = st.selectbox("Re-open a simulation", [j["job_id"] for j in jobs], key="sim_pick",
                        format_func=lambda i: next(f"{j.get('league')} {(j.get('params') or {}).get('game_id') or 'custom'} "
                                                   f"({(j.get('created_at') or '')[:16].replace('T', ' ')})"
                                                   for j in jobs if j["job_id"] == i))
    if st.button("Open", key="sim_open"):
        r = get_api_client().get_simulation_results(pick)
        if r.get("success"):
            st.session_state[RESULT_KEY] = r["data"]
            st.rerun()
        else:
            st.error(r.get("error"))
