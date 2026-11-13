"""
Sport-specific dashboard page - Template for NBA, NFL, MLB, NHL
"""
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from components import (
    render_header, render_stat_card, render_prediction_card,
    render_team_card, render_sport_submenu
)
from utils.charts import (
    create_probability_bar, create_team_form_chart,
    create_odds_movement_chart, create_shap_waterfall,
    create_factor_chart, create_histogram_chart, create_accuracy_series_chart
)
from utils.api_client import get_api_client, cached, export_bytes
from config import SPORTS


def render_sport_dashboard(sport: str):
    """Render sport-specific dashboard"""

    sport_config = SPORTS.get(sport, {})
    sport_icon = sport_config.get('icon', '🏆')
    sport_color = sport_config.get('color', '#0078D4')
    sport_name = sport_config.get('name', sport)

    render_header(
        title=f"{sport_icon} {sport_name}",
        subtitle=f"Predictions and analytics for {sport_name}"
    )

    # Sport submenu
    selected_tab = render_sport_submenu(sport)

    if selected_tab == "Predictions":
        render_predictions_tab(sport, sport_color)
    elif selected_tab == "Team Analysis":
        render_team_analysis_tab(sport, sport_color)
    elif selected_tab == "Historical Data":
        render_historical_tab(sport, sport_color)
    elif selected_tab == "Live Odds":
        render_live_odds_tab(sport, sport_color)


def _fmt_line(v, signed=True):
    if isinstance(v, (int, float)):
        return f"{v:+g}" if signed else f"{v:g}"
    return v or "N/A"


def _fmt_price(v):
    if isinstance(v, (int, float)):
        return f"{int(v):+d}"
    return v or "N/A"


def render_predictions_tab(sport: str, color: str):
    """Render predictions tab"""

    # Live button and Date selector row
    live_col, col1, col2, col3, col4 = st.columns([1.2, 2, 1, 1, 1])

    with live_col:
        st.write("")  # Spacer for alignment
        st.markdown('<div class="live-button-container">', unsafe_allow_html=True)
        live_clicked = st.button("🔴 LIVE", key=f"{sport}_live_btn", help="View live games with predictions")
        st.markdown('</div>', unsafe_allow_html=True)

    with col1:
        selected_date = st.date_input(
            "Select Date",
            value=datetime.now(),
            key=f"{sport}_date"
        )

    with col2:
        confidence_filter = st.selectbox(
            "Confidence",
            ["All", "High (>65%)", "Medium (55-65%)", "Low (<55%)"],
            key=f"{sport}_confidence"
        )

    with col3:
        sort_by = st.selectbox(
            "Sort By",
            ["Game Time", "Confidence", "Home Win %"],
            key=f"{sport}_sort"
        )

    with col4:
        st.write("")  # Spacer
        refresh = st.button("🔄 Refresh", key=f"{sport}_refresh")

    # Handle live button click
    if live_clicked:
        st.session_state[f"{sport}_show_live"] = True

    # Show live predictions if toggled
    if st.session_state.get(f"{sport}_show_live", False):
        render_live_predictions_modal(sport, color)
        return

    st.divider()

    date_str = selected_date.strftime('%Y%m%d')
    with st.spinner(f"Loading {sport} predictions..."):
        all_predictions = fetch_predictions_from_api(sport, date_str, force_refresh=refresh)

    if not all_predictions:
        st.info(f"No {sport} games scheduled for {selected_date.strftime('%B %d, %Y')}")
        return

    predictions = all_predictions
    if confidence_filter.startswith("High"):
        predictions = [p for p in predictions if p['confidence'] > 0.65]
    elif confidence_filter.startswith("Medium"):
        predictions = [p for p in predictions if 0.55 <= p['confidence'] <= 0.65]
    elif confidence_filter.startswith("Low"):
        predictions = [p for p in predictions if p['confidence'] < 0.55]
    if sort_by == "Confidence":
        predictions = sorted(predictions, key=lambda p: p['confidence'], reverse=True)
    elif sort_by == "Home Win %":
        predictions = sorted(predictions, key=lambda p: p['home_win_prob'], reverse=True)
    else:
        predictions = sorted(predictions, key=lambda p: p.get('game_date') or "")

    model_info = all_predictions[0].get('model') or {}

    # Stats summary
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        render_stat_card(
            title="Total Games",
            value=str(len(all_predictions)),
            icon="🎮",
            color=color
        )

    with col2:
        high_conf = sum(1 for p in all_predictions if p['confidence'] >= 0.65)
        render_stat_card(
            title="High Confidence",
            value=str(high_conf),
            icon="🎯",
            color="#4CAF50"
        )

    with col3:
        avg_conf = sum(p['confidence'] for p in all_predictions) / len(all_predictions)
        render_stat_card(
            title="Avg Confidence",
            value=f"{avg_conf*100:.1f}%",
            icon="📊",
            color="#00BCF2"
        )

    with col4:
        render_stat_card(
            title="Model",
            value="Ensemble" if model_info.get('type') == 'ensemble' else "Heuristic",
            delta="Trained ML ensemble" if model_info.get('is_trained') else "No trained model yet",
            delta_type="positive" if model_info.get('is_trained') else "negative",
            icon="🤖",
            color="#9C27B0"
        )

    st.write("")

    # Export buttons (files are generated by the backend /api/export endpoint when clicked)
    api_key = st.session_state.get("api_key")
    col_export1, col_export2, col_space = st.columns([1, 1, 4])

    with col_export1:
        st.download_button(
            label="📥 Export CSV",
            data=lambda: export_bytes(sport, date_str, "csv", api_key),
            file_name=f"{sport}_predictions_{date_str}.csv",
            mime="text/csv",
            key=f"{sport}_csv_export",
            on_click="ignore",
        )

    with col_export2:
        st.download_button(
            label="📄 Export PDF",
            data=lambda: export_bytes(sport, date_str, "pdf", api_key),
            file_name=f"{sport}_predictions_{date_str}.pdf",
            mime="application/pdf",
            key=f"{sport}_pdf_export",
            on_click="ignore",
        )

    st.write("")

    if not predictions:
        st.info("No games match the selected confidence filter.")

    # Predictions grid
    for pred in predictions:
        with st.container():
            if pred['predicted_winner'] == pred['home_team_abbr']:
                ml = pred['moneyline_home']
            else:
                ml = pred['moneyline_away']

            status = pred.get('status_detail') or pred['game_time']
            if pred.get('is_final'):
                status = f"FINAL {pred.get('away_score')}-{pred.get('home_score')} | {status}"
            elif pred.get('is_live'):
                status = f"🔴 LIVE {pred.get('away_score')}-{pred.get('home_score')} | {status}"

            render_prediction_card(
                home_team=pred['home_team'],
                away_team=pred['away_team'],
                home_prob=pred['home_win_prob'],
                confidence=pred['confidence'],
                game_time=status,
                venue=pred.get('venue', ''),
                spread=_fmt_line(pred.get('spread')),
                moneyline=_fmt_price(ml),
                over_under=_fmt_line(pred.get('over_under'), signed=False),
                home_record=pred.get('home_record', ''),
                away_record=pred.get('away_record', '')
            )

            if pred.get('key_factors'):
                st.caption("Key factors: " + " | ".join(pred['key_factors'][:4]))

            # Expandable details
            with st.expander("📊 View Detailed Analysis"):
                game_key_base = f"{sport}_{pred.get('game_id') or pred['home_team'].replace(' ', '_')}"

                analysis_tab1, analysis_tab2, analysis_tab3, analysis_tab4 = st.tabs([
                    "📈 Feature Impact", "💵 Betting", "⭐ Key Players", "📊 Team Form"
                ])

                with analysis_tab1:
                    render_feature_impact_section(pred, game_key_base, sport, ml)

                with analysis_tab2:
                    render_betting_section(pred, game_key_base, sport)

                with analysis_tab3:
                    render_star_impact_section(pred, game_key_base, sport)
                    render_injuries_section(pred)

                with analysis_tab4:
                    render_team_form_section(pred, game_key_base, sport)


def render_feature_impact_section(pred: dict, game_key_base: str, sport: str, ml):
    """Explanation factors (SHAP + injury/news adjustments) and the simulated margin distribution"""
    explanation = pred.get('explanation') or {}
    factors = explanation.get('factors') or []

    detail_col1, detail_col2 = st.columns(2)

    with detail_col1:
        st.markdown("**Why the model leans this way**")
        if factors:
            st.plotly_chart(
                create_factor_chart(factors), width="stretch",
                config={'displayModeBar': False}, key=f"factors_{game_key_base}"
            )
            method = explanation.get('method', '')
            st.caption(
                f"Method: {method.replace('_', ' ')}. Impacts are changes in home win probability."
                + (f" {explanation.get('note')}" if explanation.get('note') else "")
            )
        else:
            features, values = build_shap_features(pred, sport)
            if features:
                st.plotly_chart(create_shap_waterfall(features, values), width="stretch",
                                config={'displayModeBar': False}, key=f"shap_{game_key_base}")
            else:
                st.info("No explanation available for this game.")

    with detail_col2:
        st.markdown("**Monte Carlo Simulation**")
        sim = (pred.get('betting') or {}).get('simulation') or {}
        hist = (sim.get('histograms') or {}).get('margin')
        if hist:
            st.plotly_chart(
                create_histogram_chart(hist, f"Simulated margin ({sim.get('simulations_run', 0):,} sims)",
                                       f"{pred['home_team_abbr'] or 'Home'} margin", ref_zero=True),
                width="stretch", config={'displayModeBar': False}, key=f"mc_{game_key_base}"
            )
            st.caption(f"Projected score {pred['home_team_abbr']} {sim.get('predicted_home_score')} - "
                       f"{sim.get('predicted_away_score')} {pred['away_team_abbr']}; 80% margin range "
                       f"{sim.get('margin_range_80')}")
        else:
            st.info("No simulation data for this game.")

    if pred.get('key_factors'):
        st.markdown("**Key factors**")
        for f in pred['key_factors']:
            st.markdown(f"- {f}")

    # Market odds details
    market_odds = pred.get('market_odds', {})
    if market_odds:
        st.markdown("---")
        st.markdown("**Market Odds Analysis**")
        odds_col1, odds_col2, odds_col3, odds_col4, odds_col5 = st.columns(5)
        with odds_col1:
            st.metric("Moneyline", _fmt_price(ml))
        with odds_col2:
            st.metric("Spread", _fmt_line(market_odds.get('spread')))
        with odds_col3:
            st.metric("Over/Under", _fmt_line(market_odds.get('over_under'), signed=False))
        with odds_col4:
            mp = market_odds.get('market_home_probability')
            st.metric("Market Home %", f"{mp*100:.1f}%" if isinstance(mp, (int, float)) else "N/A")
        with odds_col5:
            edge = market_odds.get('model_edge_home')
            st.metric("Model Edge (Home)", f"{edge*100:+.1f}%" if isinstance(edge, (int, float)) else "N/A")
        if market_odds.get('data_source'):
            st.caption(f"Odds source: {market_odds['data_source']}")


def _rec_row(name, block, prob_text):
    return {
        "Market": name, "Line": block.get('line'),
        "Recommendation": block.get('recommendation', 'N/A'), "Probabilities": prob_text,
        "Edge": block.get('edge_probability'), "EV": block.get('expected_value'),
        "Kelly": block.get('kelly_fraction'),
    }


def _betting_table(betting: dict, home: str, away: str):
    rows = []
    ou = betting.get('over_under') or {}
    sp = betting.get('spread') or betting.get('puckline') or betting.get('runline') or {}
    mlb = betting.get('moneyline') or {}
    if ou:
        rows.append(_rec_row("Total", ou, f"Over {ou.get('over_probability', 0)*100:.1f}% / Under {ou.get('under_probability', 0)*100:.1f}%"))
    if sp:
        rows.append(_rec_row("Spread (home line)", sp, f"{home} {sp.get('home_cover_probability', 0)*100:.1f}% / {away} {sp.get('away_cover_probability', 0)*100:.1f}%"))
    if mlb:
        hp = mlb.get('home_probability')
        rows.append({"Market": "Moneyline", "Line": f"{_fmt_price(mlb.get('home_price'))} / {_fmt_price(mlb.get('away_price'))}",
                     "Recommendation": mlb.get('recommendation', 'N/A'),
                     "Probabilities": f"{home} {hp*100:.1f}% / {away} {(1-hp)*100:.1f}%" if isinstance(hp, (int, float)) else "",
                     "Edge": mlb.get('edge_probability'), "EV": mlb.get('expected_value'),
                     "Kelly": mlb.get('kelly_fraction')})
    if rows:
        df = pd.DataFrame(rows)
        df["Line"] = df["Line"].astype(str)
        st.dataframe(df, width="stretch", hide_index=True, column_config={
            "Edge": st.column_config.NumberColumn(format="percent"),
            "EV": st.column_config.NumberColumn(format="%.3f"),
            "Kelly": st.column_config.NumberColumn(format="percent"),
        })
    else:
        st.info("No betting lines available for this game.")


def render_betting_section(pred: dict, game_key_base: str, sport: str):
    """Model betting forecast plus user-editable spread / O-U lines (POST /api/predict/recalculate)"""
    betting = pred.get('betting') or {}
    home, away = pred['home_team_abbr'] or "Home", pred['away_team_abbr'] or "Away"
    mo = pred.get('market_odds') or {}

    st.markdown("**Model betting forecast (market lines)**")
    _betting_table(betting, home, away)

    st.markdown("---")
    st.markdown("**Try your own lines**")
    st.caption("Spread is quoted for the home team (e.g. -3.5 = home favoured by 3.5).")
    rk = f"recalc_{game_key_base}"
    with st.form(f"form_{rk}", border=False):
        c1, c2, c3 = st.columns([1, 1, 1])
        with c1:
            custom_spread = st.number_input("Spread (home)", value=mo.get('spread'), step=0.5, format="%.1f",
                                            key=f"{rk}_spread")
        with c2:
            custom_ou = st.number_input("Over/Under", value=mo.get('over_under'), step=0.5, format="%.1f",
                                        key=f"{rk}_ou")
        with c3:
            st.write("")
            submitted = st.form_submit_button("Recalculate")
    if submitted:
        res = get_api_client().recalculate(
            sport, pred.get('game_id'), custom_spread=custom_spread, custom_over_under=custom_ou,
            home_win_probability=pred.get('home_win_prob'), is_live=bool(pred.get('is_live')),
            home_score=pred.get('home_score') or 0, away_score=pred.get('away_score') or 0,
            period=pred.get('period') if pred.get('is_live') else None,
            clock=pred.get('clock') if pred.get('is_live') else None,
        )
        if res.get('success'):
            st.session_state[rk] = res['data']
        else:
            st.error(f"Recalculation failed: {res.get('error')}")
    recalc = st.session_state.get(rk)
    if recalc:
        lines = recalc.get('custom_lines') or {}
        st.markdown(f"**Forecast at spread {_fmt_line(lines.get('spread'))}, total {_fmt_line(lines.get('over_under'), False)}**")
        _betting_table(recalc.get('betting') or {}, home, away)
        hist = ((recalc.get('betting') or {}).get('simulation') or {}).get('histograms', {}).get('total')
        if hist:
            st.plotly_chart(create_histogram_chart(hist, "Simulated total", "Combined score",
                                                   line=lines.get('over_under'), line_label="O/U"),
                            width="stretch", config={'displayModeBar': False}, key=f"{rk}_hist")


def render_injuries_section(pred: dict):
    injuries = pred.get('injuries') or {}
    items = [dict(i, side="Home") for i in injuries.get('home', [])] + [dict(i, side="Away") for i in injuries.get('away', [])]
    if not items:
        return
    st.markdown("---")
    st.markdown("**Injury Report**")
    st.dataframe(pd.DataFrame([{
        "Team": i.get('team_abbr'), "Player": i.get('player_name'), "Pos": i.get('position'),
        "Status": i.get('status'), "Detail": i.get('detail')} for i in items]),
        width="stretch", hide_index=True)


def render_team_analysis_tab(sport: str, color: str):
    """Team analysis from /api/{league}/teams and /api/{league}/team/{abbr}/form"""

    teams_res = cached("get_teams", league=sport)
    if not teams_res.get('success'):
        st.error(f"Could not load teams: {teams_res.get('error')}")
        return
    teams = teams_res['data'].get('teams', [])
    if not teams:
        st.info("No teams available.")
        return
    by_abbr = {t['abbr']: t for t in teams}

    col1, col2 = st.columns([1, 3])
    with col1:
        abbr = st.selectbox("Select Team", list(by_abbr), format_func=lambda a: by_abbr[a]['name'],
                            key=f"{sport}_team_select")

    st.divider()
    team = by_abbr[abbr]
    form_res = cached("get_team_form", league=sport, team_abbr=abbr)

    col1, col2 = st.columns([1, 5])
    with col1:
        if team.get('logo'):
            st.image(team['logo'], width=64)
        else:
            st.markdown("### 🏆")
    with col2:
        st.subheader(team['name'])
        st.caption("Recent form from stored results")

    if not form_res.get('success'):
        st.info(f"No completed games stored for {team['name']} yet.")
        return
    f = form_res['data']
    l10 = (f.get('form') or {}).get('last_10', {})

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        render_stat_card("Last 10", f.get('record_last_10', 'N/A'), icon="📊", color=color)
    with col2:
        render_stat_card("Win % (L10)", f"{(f.get('win_pct') or 0)*100:.1f}%", icon="📈", color="#4CAF50")
    with col3:
        render_stat_card("Streak", f.get('streak', 'N/A'), icon="🔥", color="#FF9800")
    with col4:
        render_stat_card("Avg Margin (L10)", f"{l10.get('avg_point_diff', 0):+.1f}", icon="📅", color="#00BCF2")

    st.write("")

    col_left, col_right = st.columns([2, 1])
    games = list(reversed((f.get('form') or {}).get('games', [])))

    with col_left:
        st.markdown("**Recent Performance**")
        if games:
            labels = [f"{'vs' if g.get('is_home') else '@'} {g.get('opponent_abbr')} {g.get('game_date', '')[5:10]}" for g in games]
            results = ["W" if g.get('won') else "L" for g in games]
            margins = [g.get('margin', 0) for g in games]
            st.plotly_chart(create_team_form_chart(labels, results, margins), width="stretch",
                            config={'displayModeBar': False}, key=f"{sport}_{abbr}_form")

    with col_right:
        st.markdown("**Upcoming Games**")
        sched = cached("get_schedule", league=sport, days=10)
        sgames = []
        if sched.get('success'):
            data = sched['data']
            sgames = data.get('games') or data.get('schedule') or []
        mine = [g for g in sgames if abbr in (g.get('home_team_abbr'), g.get('away_team_abbr'))][:5]
        if not mine:
            st.caption("No games in the next 10 days.")
        for g in mine:
            is_home = g.get('home_team_abbr') == abbr
            opp = g.get('away_team') if is_home else g.get('home_team')
            when = (g.get('game_date') or g.get('date') or '')[:10]
            c1, c2 = st.columns([3, 1])
            with c1:
                st.markdown(f"**{'vs' if is_home else '@'} {opp}**")
                st.caption("Home" if is_home else "Away")
            with c2:
                st.caption(when)
            st.divider()

    if games:
        st.markdown("**Last 10 Games**")
        st.dataframe(pd.DataFrame([{
            "Date": g.get('game_date', '')[:10], "Opponent": g.get('opponent_name'),
            "Venue": "Home" if g.get('is_home') else "Away", "Score": f"{g.get('team_score')}-{g.get('opponent_score')}",
            "Result": "W" if g.get('won') else "L", "Margin": g.get('margin'),
            "Spread": g.get('spread'), "O/U": g.get('over_under')} for g in reversed(games)]),
            width="stretch", hide_index=True)


def render_historical_tab(sport: str, color: str):
    """Tracked accuracy of stored predictions and stored final games"""

    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        start_date = st.date_input("Start Date", value=datetime.now() - timedelta(days=30), key=f"{sport}_hist_start")
    with col2:
        end_date = st.date_input("End Date", value=datetime.now(), key=f"{sport}_hist_end")

    st.divider()

    days = max(1, min(730, (datetime.now().date() - start_date).days + 1))
    acc = cached("get_accuracy", league=sport, days=days)
    st.markdown("**Historical Accuracy Trend**")
    if not acc.get('success'):
        st.error(f"Could not load accuracy: {acc.get('error')}")
    else:
        series = [s for s in acc['data'].get('series', [])
                  if start_date.isoformat() <= s['date'] <= end_date.isoformat()]
        if series:
            st.plotly_chart(create_accuracy_series_chart(series, color=color), width="stretch",
                            config={'displayModeBar': False}, key=f"{sport}_hist_trend")
            n = sum(s['games'] for s in series)
            c = sum(s['correct'] for s in series)
            st.caption(f"{c}/{n} correct ({c / n * 100:.1f}%) in the selected range.")
        else:
            st.info("No settled predictions in this range yet. Predictions are graded automatically once games finish.")

    st.markdown("**Stored Results**")
    res = cached("get_historical_games", league=sport, start_date=start_date.strftime('%Y%m%d'),
                 end_date=end_date.strftime('%Y%m%d'), limit=500)
    if not res.get('success'):
        st.error(f"Could not load games: {res.get('error')}")
        return
    games = res['data'].get('games', [])
    if not games:
        st.info("No completed games stored for this range.")
        return
    df = pd.DataFrame([{
        "Date": g['game_date'][:10], "Away": g['away_team_abbr'], "Home": g['home_team_abbr'],
        "Score": f"{g['away_score']}-{g['home_score']}",
        "Winner": g['home_team_abbr'] if (g['home_score'] or 0) > (g['away_score'] or 0) else g['away_team_abbr'],
        "Spread": g.get('spread'), "O/U": g.get('over_under'),
        "ML Home": g.get('moneyline_home'), "ML Away": g.get('moneyline_away')} for g in reversed(games)])
    st.dataframe(df, width="stretch", hide_index=True)


def render_live_odds_tab(sport: str, color: str):
    """Current lines and open-to-current movement from today's predictions"""

    with st.spinner("Loading lines..."):
        preds = fetch_predictions_from_api(sport, None)
    with_odds = [p for p in preds if p.get('market_odds')]
    if not with_odds:
        st.info(f"No {sport} lines available today.")
        return

    rows = []
    for p in with_odds:
        mo = p['market_odds']
        rows.append({
            "Game": f"{p['away_team_abbr']} @ {p['home_team_abbr']}",
            "Status": p.get('status_detail', ''),
            "Spread": mo.get('spread'), "Open Spread": mo.get('open_spread'),
            "O/U": mo.get('over_under'), "Open O/U": mo.get('open_over_under'),
            "ML Home": mo.get('moneyline_home'), "Open ML Home": mo.get('open_moneyline_home'),
            "ML Away": mo.get('moneyline_away'),
            "Market Home %": mo.get('market_home_probability'),
            "Model Home %": p['home_win_prob'],
            "Source": mo.get('data_source'),
        })
    st.markdown("**Current Lines vs Open**")
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True, column_config={
        "Market Home %": st.column_config.NumberColumn(format="percent"),
        "Model Home %": st.column_config.NumberColumn(format="percent"),
    })

    st.markdown("**Moneyline Movement (open to current)**")
    moved = [p for p in with_odds if p['market_odds'].get('open_moneyline_home') is not None
             and p['market_odds'].get('moneyline_home') is not None]
    if moved:
        labels = {str(p['game_id']): f"{p['away_team_abbr']} @ {p['home_team_abbr']}" for p in moved}
        gid = st.selectbox("Game", list(labels), format_func=lambda g: labels[g], key=f"{sport}_odds_game")
        p = next(x for x in moved if str(x['game_id']) == gid)
        mo = p['market_odds']
        fig = create_odds_movement_chart(
            ["Open", "Current"], [mo['open_moneyline_home'], mo['moneyline_home']],
            [mo.get('open_moneyline_away'), mo.get('moneyline_away')], p['home_team'], p['away_team'])
        st.plotly_chart(fig, width="stretch", config={'displayModeBar': False}, key=f"{sport}_odds_chart")
        st.caption("Only opening and current lines are available from the odds feed (no intraday history).")
    else:
        st.caption("No opening lines available to show movement.")


def render_live_predictions_modal(sport: str, color: str):
    """Render live predictions section with real-time game data"""
    import plotly.graph_objects as go

    # Header with back button
    col_back, col_title, col_refresh = st.columns([1, 4, 1])

    with col_back:
        if st.button("← Back", key=f"{sport}_live_back"):
            st.session_state[f"{sport}_show_live"] = False
            st.rerun()

    with col_title:
        st.markdown(
            f"""
            <div style="display: flex; align-items: center; gap: 12px;">
                <span style="
                    display: inline-block;
                    width: 12px;
                    height: 12px;
                    background: #F44336;
                    border-radius: 50%;
                    animation: liveBlink 1.5s ease-in-out infinite;
                "></span>
                <h2 style="margin: 0; color: white;">Live {sport} Games</h2>
            </div>
            """,
            unsafe_allow_html=True
        )

    with col_refresh:
        if st.button("🔄", key=f"{sport}_live_refresh", help="Refresh live data"):
            st.rerun()

    st.divider()

    # Fetch live predictions from API
    api_client = get_api_client()
    result = api_client.get_live_predictions(sport)

    if not result.get("success"):
        error_msg = result.get("error", "Failed to fetch live predictions")
        st.error(f"Could not load live games: {error_msg}")
        st.info("Make sure the backend server is running and the live prediction endpoints are available.")
        return

    data = result.get("data", {})
    live_games = data.get("games", data.get("predictions", []))

    if not live_games:
        st.info(f"No live {sport} games at the moment.")
        st.caption("Live games will appear here when games are in progress.")
        return

    # Stats summary for live games
    col1, col2, col3 = st.columns(3)

    with col1:
        render_stat_card(
            title="Live Games",
            value=str(len(live_games)),
            icon="🔴",
            color="#F44336"
        )

    with col2:
        high_conf = sum(1 for g in live_games if g.get('confidence', 0) >= 0.65)
        render_stat_card(
            title="High Confidence",
            value=str(high_conf),
            icon="🎯",
            color="#4CAF50"
        )

    with col3:
        avg_conf = sum(g.get('confidence', 0.5) for g in live_games) / len(live_games) if live_games else 0
        render_stat_card(
            title="Avg Confidence",
            value=f"{avg_conf*100:.1f}%",
            icon="📊",
            color="#00BCF2"
        )

    st.write("")

    # Render each live game
    for game in live_games:
        render_live_game_card(game, sport, color)


def render_live_game_card(game: dict, sport: str, color: str):
    """Render a single live game card with prediction"""
    import plotly.graph_objects as go

    home_team = game.get("home_team", "Home Team")
    away_team = game.get("away_team", "Away Team")
    home_prob = game.get("home_win_probability", game.get("home_win_prob", 0.5))
    away_prob = 1 - home_prob
    confidence = game.get("confidence", 0.5)
    home_score = game.get("home_score", game.get("home_points", "-"))
    away_score = game.get("away_score", game.get("away_points", "-"))
    period = game.get("period", game.get("quarter", game.get("inning", "")))
    time_remaining = game.get("time_remaining", game.get("clock", ""))
    game_status = game.get("status", "In Progress")

    # Create unique key for this game
    game_key = f"{sport}_{home_team}_{away_team}".replace(" ", "_")

    with st.container():
        # Live game card with red border styling
        st.markdown('<div class="live-game-card">', unsafe_allow_html=True)

        # Game status header
        status_col1, status_col2 = st.columns([3, 1])
        with status_col1:
            period_display = f"Period {period}" if period else ""
            time_display = f" - {time_remaining}" if time_remaining else ""
            st.caption(f"🔴 LIVE {period_display}{time_display}")
        with status_col2:
            st.caption(game_status)

        # Score display
        score_col1, score_col2, score_col3 = st.columns([2, 1, 2])

        with score_col1:
            if home_prob > 0.5:
                st.markdown(f"**:green[{home_team}]**")
            else:
                st.markdown(f"**{home_team}**")
            st.markdown(f"### {home_score}")

        with score_col2:
            st.markdown(
                "<div style='text-align: center; padding-top: 15px;'><b>VS</b></div>",
                unsafe_allow_html=True
            )

        with score_col3:
            if away_prob > 0.5:
                st.markdown(f"**:green[{away_team}]**")
            else:
                st.markdown(f"**{away_team}**")
            st.markdown(f"### {away_score}")

        # Probability bar
        fig = go.Figure()
        fig.add_trace(go.Bar(
            y=[''],
            x=[home_prob * 100],
            orientation='h',
            name=home_team,
            marker_color='#4CAF50' if home_prob > 0.5 else '#666666',
            text=f"{home_team}: {home_prob*100:.1f}%",
            textposition='inside',
            insidetextanchor='start'
        ))
        fig.add_trace(go.Bar(
            y=[''],
            x=[away_prob * 100],
            orientation='h',
            name=away_team,
            marker_color='#4CAF50' if away_prob > 0.5 else '#666666',
            text=f"{away_team}: {away_prob*100:.1f}%",
            textposition='inside',
            insidetextanchor='end'
        ))
        fig.update_layout(
            barmode='stack',
            height=50,
            margin=dict(l=0, r=0, t=0, b=0),
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            showlegend=False,
            xaxis=dict(showticklabels=False, showgrid=False, zeroline=False, range=[0, 100]),
            yaxis=dict(showticklabels=False, showgrid=False, zeroline=False)
        )
        st.plotly_chart(fig, width="stretch", config={'displayModeBar': False}, key=f"live_prob_{game_key}")

        # Additional live stats
        stat_col1, stat_col2, stat_col3 = st.columns(3)
        with stat_col1:
            st.metric("Confidence", f"{confidence*100:.1f}%")
        with stat_col2:
            spread = (game.get("market_odds") or {}).get("spread", game.get("spread"))
            st.metric("Spread", _fmt_line(spread))
        with stat_col3:
            over_under = (game.get("market_odds") or {}).get("over_under", game.get("over_under"))
            st.metric("Over/Under", _fmt_line(over_under, signed=False))
        if game.get("key_factors"):
            st.caption("Key factors: " + " | ".join(game["key_factors"][:3]))

        st.markdown('</div>', unsafe_allow_html=True)
        st.write("")  # Spacing between cards


def build_shap_features(pred: dict, sport: str = "NBA") -> tuple:
    """Build SHAP feature names and values from prediction data - sport-specific"""
    features = []
    values = []

    # Get common data
    team_form = pred.get('team_form', {})
    form_adjustment = team_form.get('form_adjustment', 0)
    star_impact = pred.get('star_impact', {})
    net_star_impact = star_impact.get('net_impact', 0)
    market_odds = pred.get('market_odds', {})
    spread_adjustment = market_odds.get('spread_adjustment', 0)
    total_adjustment = market_odds.get('total_adjustment', 0)
    feature_weights = pred.get('feature_weights', {})
    adjustments = pred.get('adjustments', {})

    # Calculate probability shift for direction hints
    base_prob = pred.get('base_home_probability', 0.5)
    final_prob = pred.get('home_win_prob', 0.5)
    prob_shift = final_prob - base_prob

    # ===== NFL-SPECIFIC FEATURES =====
    if sport.upper() == "NFL":
        # QB adjustment (20% weight in NFL)
        qb_adj = adjustments.get('qb_adjustment', 0)
        if qb_adj != 0:
            features.append("QB Impact")
            values.append(qb_adj)

        # Weather adjustment (5% weight)
        weather_adj = adjustments.get('weather_adjustment', 0)
        if weather_adj != 0:
            features.append("Weather")
            values.append(weather_adj)

        # Turnover adjustment (18% weight)
        turnover_adj = adjustments.get('turnover_adjustment', 0)
        if turnover_adj != 0:
            features.append("Turnover Risk")
            values.append(turnover_adj)

        # Rest adjustment (18% weight)
        rest_adj = adjustments.get('rest_adjustment', 0)
        if rest_adj != 0:
            features.append("Rest Advantage")
            values.append(rest_adj)

        # Form (36% weight)
        if form_adjustment != 0:
            features.append("Team Form")
            values.append(form_adjustment)

    # ===== MLB-SPECIFIC FEATURES =====
    elif sport.upper() == "MLB":
        # Pitcher impact (60% of variance)
        pitcher_impact = pred.get('pitcher_impact', {})
        home_pitcher_adj = pitcher_impact.get('home_starter_impact', 0)
        away_pitcher_adj = pitcher_impact.get('away_starter_impact', 0)
        net_pitcher = home_pitcher_adj - away_pitcher_adj

        if net_pitcher != 0:
            features.append("Starting Pitcher")
            values.append(net_pitcher)
        elif adjustments.get('pitcher_adjustment', 0) != 0:
            features.append("Starting Pitcher")
            values.append(adjustments.get('pitcher_adjustment', 0))

        # Bullpen impact (13%)
        bullpen_adj = adjustments.get('bullpen_adjustment', 0)
        if bullpen_adj != 0:
            features.append("Bullpen")
            values.append(bullpen_adj)

        # Team offense (19%)
        if form_adjustment != 0:
            features.append("Team Offense")
            values.append(form_adjustment)

        # Weather for outdoor games
        weather_adj = adjustments.get('weather_adjustment', 0)
        if weather_adj != 0:
            features.append("Weather")
            values.append(weather_adj)

    # ===== NHL-SPECIFIC FEATURES =====
    elif sport.upper() == "NHL":
        # Goalie impact (18% weight)
        goalie_impact = pred.get('goalie_impact', {})
        net_goalie = goalie_impact.get('net_impact', 0)
        if net_goalie != 0:
            features.append("Goalie Impact")
            values.append(net_goalie)
        elif net_star_impact != 0:
            features.append("Goalie Impact")
            values.append(net_star_impact)

        # Goal differential (32% weight)
        if form_adjustment != 0:
            features.append("Goal Differential")
            values.append(form_adjustment)

        # Special teams (18% weight)
        special_teams = pred.get('special_teams', {})
        pp_diff = special_teams.get('power_play_diff', 0)
        pk_diff = special_teams.get('penalty_kill_diff', 0)
        if pp_diff != 0 or pk_diff != 0:
            features.append("Special Teams")
            values.append((pp_diff + pk_diff) / 2 * 0.18)

    # ===== NBA-SPECIFIC FEATURES =====
    else:  # NBA default
        # Team form (70% signal)
        if form_adjustment != 0:
            features.append("Team Form")
            values.append(form_adjustment)

        # Star player impact (20%)
        if net_star_impact != 0:
            features.append("Star Players")
            values.append(net_star_impact)

        # Back-to-back penalty
        if pred.get('back_to_back_home') or pred.get('back_to_back_away'):
            b2b_penalty = -0.03 if pred.get('back_to_back_home') else 0.03
            features.append("Back-to-Back")
            values.append(b2b_penalty)

    # ===== COMMON FEATURES FOR ALL SPORTS =====
    # Market spread signal
    if spread_adjustment != 0:
        features.append("Market Spread")
        values.append(spread_adjustment)

    # Market total/over-under signal
    if total_adjustment != 0:
        features.append("Market Total")
        values.append(total_adjustment)

    # Home advantage
    home_adv_weight = feature_weights.get('home_advantage', 0.08)
    if home_adv_weight > 0:
        features.append("Home Advantage")
        values.append(home_adv_weight * (1 if prob_shift >= 0 else -0.5))

    # Ensure minimum features
    if len(features) < 3:
        rest_weight = feature_weights.get('rest_days', 0.05)
        features.append("Rest Days")
        values.append(rest_weight * (0.5 if prob_shift > 0 else -0.5))

        h2h_weight = feature_weights.get('h2h_history', 0.03)
        features.append("H2H History")
        values.append(h2h_weight * (0.5 if prob_shift > 0 else -0.5))

    # Sort by absolute value (most impactful first)
    sorted_pairs = sorted(zip(features, values), key=lambda x: abs(x[1]), reverse=True)
    features = [p[0] for p in sorted_pairs]
    values = [p[1] for p in sorted_pairs]

    return features, values


def render_star_impact_section(pred: dict, game_key_base: str, sport: str = "NBA"):
    """Render the star/key player impact section - sport-specific"""

    # Get sport-specific impact data
    star_impact = pred.get('star_impact', {})
    pitcher_impact = pred.get('pitcher_impact', {})
    goalie_impact = pred.get('goalie_impact', {})
    qb_impact = pred.get('qb_impact', {})

    # Determine section title and data based on sport
    sport_upper = sport.upper()
    if sport_upper == "NFL":
        section_title = "Quarterback Impact"
        impact_data = qb_impact if qb_impact else star_impact
        tier_labels = {1: "Elite", 2: "Above Avg", 3: "Average", 4: "Below Avg"}
        player_label = "QB"
    elif sport_upper == "MLB":
        section_title = "Starting Pitcher Impact"
        impact_data = pitcher_impact if pitcher_impact else star_impact
        tier_labels = {1: "Ace", 2: "Quality", 3: "Backend"}
        player_label = "SP"
    elif sport_upper == "NHL":
        section_title = "Goalie Impact"
        impact_data = goalie_impact if goalie_impact else star_impact
        tier_labels = {1: "Elite", 2: "Starting", 3: "Backup"}
        player_label = "G"
    else:  # NBA
        section_title = "Star Player Impact"
        impact_data = star_impact
        tier_labels = {1: "MVP", 2: "All-Star", 3: "Starter", 4: "Role"}
        player_label = "Star"

    if not impact_data:
        st.info(f"No {section_title.lower()} data available for this game.")
        return

    st.markdown(f"### {section_title}")

    # Summary metrics
    col1, col2, col3 = st.columns(3)
    with col1:
        home_impact = impact_data.get('home_impact', 0)
        delta_color = "normal" if home_impact >= 0 else "inverse"
        st.metric(
            f"Home {player_label} Impact",
            f"{home_impact*100:+.1f}%",
            delta=f"{'Boost' if home_impact >= 0 else 'Penalty'}",
            delta_color=delta_color
        )
    with col2:
        away_impact = impact_data.get('away_impact', 0)
        delta_color = "normal" if away_impact >= 0 else "inverse"
        st.metric(
            f"Away {player_label} Impact",
            f"{away_impact*100:+.1f}%",
            delta=f"{'Boost' if away_impact >= 0 else 'Penalty'}",
            delta_color=delta_color
        )
    with col3:
        net_impact = impact_data.get('net_impact', 0)
        weight = impact_data.get('weight', 0.2)
        st.metric(
            "Net Impact (Home)",
            f"{net_impact*100:+.2f}%",
            delta=f"Weight: {weight*100:.0f}%"
        )

    st.markdown("---")

    # Get players list - handle different field names per sport
    home_players = (impact_data.get('home_stars', []) or
                    impact_data.get('home_qbs', []) or
                    impact_data.get('home_pitchers', []) or
                    impact_data.get('home_goalies', []) or [])
    away_players = (impact_data.get('away_stars', []) or
                    impact_data.get('away_qbs', []) or
                    impact_data.get('away_pitchers', []) or
                    impact_data.get('away_goalies', []) or [])

    player_col1, player_col2 = st.columns(2)

    with player_col1:
        st.markdown(f"**{pred.get('home_team', 'Home')}**")
        if home_players:
            for player in home_players:
                render_player_card(player, tier_labels, sport_upper)
        else:
            st.caption(f"No tracked {player_label}s")

    with player_col2:
        st.markdown(f"**{pred.get('away_team', 'Away')}**")
        if away_players:
            for player in away_players:
                render_player_card(player, tier_labels, sport_upper)
        else:
            st.caption(f"No tracked {player_label}s")

    # Sport-specific additional info
    if sport_upper == "MLB" and pitcher_impact:
        st.markdown("---")
        st.markdown("**Pitching Stats**")
        stats_col1, stats_col2 = st.columns(2)
        with stats_col1:
            home_era = pitcher_impact.get('home_starter_era', 'N/A')
            home_whip = pitcher_impact.get('home_starter_whip', 'N/A')
            st.caption(f"Home SP: ERA {home_era}, WHIP {home_whip}")
        with stats_col2:
            away_era = pitcher_impact.get('away_starter_era', 'N/A')
            away_whip = pitcher_impact.get('away_starter_whip', 'N/A')
            st.caption(f"Away SP: ERA {away_era}, WHIP {away_whip}")

    elif sport_upper == "NHL" and goalie_impact:
        st.markdown("---")
        st.markdown("**Goalie Stats**")
        stats_col1, stats_col2 = st.columns(2)
        with stats_col1:
            home_sv = goalie_impact.get('home_save_pct', 'N/A')
            home_gaa = goalie_impact.get('home_gaa', 'N/A')
            st.caption(f"Home G: SV% {home_sv}, GAA {home_gaa}")
        with stats_col2:
            away_sv = goalie_impact.get('away_save_pct', 'N/A')
            away_gaa = goalie_impact.get('away_gaa', 'N/A')
            st.caption(f"Away G: SV% {away_sv}, GAA {away_gaa}")

    elif sport_upper == "NFL" and qb_impact:
        st.markdown("---")
        st.markdown("**QB Stats**")
        stats_col1, stats_col2 = st.columns(2)
        with stats_col1:
            home_rating = qb_impact.get('home_passer_rating', 'N/A')
            st.caption(f"Home QB Rating: {home_rating}")
        with stats_col2:
            away_rating = qb_impact.get('away_passer_rating', 'N/A')
            st.caption(f"Away QB Rating: {away_rating}")


def render_player_card(player: dict, tier_labels: dict, sport: str):
    """Render a single player impact card"""
    status = player.get('status', 'unknown')
    status_emoji = "✅" if status == "available" else "❌" if status == "out" else "⚠️"
    tier = player.get('tier', 0)
    tier_label = tier_labels.get(tier, f"Tier {tier}")
    impact = player.get('impact_applied', player.get('impact_weight', 0))

    player_name = player.get('player_name', player.get('name', 'Unknown'))

    st.markdown(
        f"{status_emoji} **{player_name}** ({tier_label})"
    )

    # Show sport-specific stats
    if sport == "MLB":
        era = player.get('era', '')
        whip = player.get('whip', '')
        stats_str = f"ERA: {era} | WHIP: {whip}" if era else ""
        st.caption(f"Status: {status.title()} | Impact: {impact*100:+.1f}% {stats_str}")
    elif sport == "NHL":
        sv_pct = player.get('save_pct', '')
        gaa = player.get('gaa', '')
        stats_str = f"SV%: {sv_pct} | GAA: {gaa}" if sv_pct else ""
        st.caption(f"Status: {status.title()} | Impact: {impact*100:+.1f}% {stats_str}")
    elif sport == "NFL":
        rating = player.get('passer_rating', '')
        stats_str = f"Rating: {rating}" if rating else ""
        st.caption(f"Status: {status.title()} | Impact: {impact*100:+.1f}% {stats_str}")
    else:
        st.caption(f"Status: {status.title()} | Impact: {impact*100:+.1f}%")


def render_team_form_section(pred: dict, game_key_base: str, sport: str = "NBA"):
    """Render the team form section with recent performance data - sport-specific"""
    team_form = pred.get('team_form', {})
    special_teams = pred.get('special_teams', {})
    adjustments = pred.get('adjustments', {})

    if not team_form:
        st.info("No team form data available for this game.")
        return

    sport_upper = sport.upper()

    # Form adjustment summary
    form_adjustment = team_form.get('form_adjustment', 0)
    adj_direction = "favors Home" if form_adjustment > 0 else "favors Away" if form_adjustment < 0 else "neutral"

    st.metric(
        "Form Adjustment",
        f"{form_adjustment*100:+.2f}%",
        delta=adj_direction
    )

    st.markdown("---")

    # Team form details
    home_form = team_form.get('home_form', {})
    away_form = team_form.get('away_form', {})

    form_col1, form_col2 = st.columns(2)

    # Sport-specific labels
    if sport_upper == "MLB":
        diff_label = "Run Diff"
        period_short = "7"
        period_long = "10"
    elif sport_upper == "NHL":
        diff_label = "Goal Diff"
        period_short = "5"
        period_long = "10"
    else:  # NBA, NFL
        diff_label = "Pt Diff"
        period_short = "5"
        period_long = "10"

    with form_col1:
        st.markdown(f"**{pred.get('home_team', 'Home')} Recent Form**")
        if home_form:
            metric_col1, metric_col2 = st.columns(2)
            with metric_col1:
                record_short = home_form.get(f'record_last_{period_short}', home_form.get('record_last_5', 'N/A'))
                st.metric(f"Last {period_short}", record_short)

                # Net rating or equivalent
                if sport_upper == "NBA":
                    net_rating = home_form.get('net_rating_last_5', 0)
                    st.metric("Net Rating", f"{net_rating:+.1f}")
                elif sport_upper == "NHL":
                    xg_diff = home_form.get('xg_diff_last_5', home_form.get('goal_diff_last_5', 0))
                    st.metric("xG Diff", f"{xg_diff:+.1f}")

            with metric_col2:
                record_long = home_form.get(f'record_last_{period_long}', home_form.get('record_last_10', 'N/A'))
                st.metric(f"Last {period_long}", record_long)

                if sport_upper == "NBA":
                    net_rating_10 = home_form.get('net_rating_last_10', 0)
                    st.metric("Net Rating (10)", f"{net_rating_10:+.1f}")

            # Differential
            diff_short = home_form.get(f'point_diff_last_{period_short}',
                         home_form.get(f'goal_diff_last_{period_short}',
                         home_form.get(f'run_diff_last_{period_short}',
                         home_form.get('point_diff_last_5', 0))))
            diff_long = home_form.get(f'point_diff_last_{period_long}',
                        home_form.get(f'goal_diff_last_{period_long}',
                        home_form.get(f'run_diff_last_{period_long}',
                        home_form.get('point_diff_last_10', 0))))
            st.caption(f"{diff_label}: L{period_short}: {diff_short:+.1f} | L{period_long}: {diff_long:+.1f}")
        else:
            st.caption("No form data available")

    with form_col2:
        st.markdown(f"**{pred.get('away_team', 'Away')} Recent Form**")
        if away_form:
            metric_col1, metric_col2 = st.columns(2)
            with metric_col1:
                record_short = away_form.get(f'record_last_{period_short}', away_form.get('record_last_5', 'N/A'))
                st.metric(f"Last {period_short}", record_short)

                if sport_upper == "NBA":
                    net_rating = away_form.get('net_rating_last_5', 0)
                    st.metric("Net Rating", f"{net_rating:+.1f}")
                elif sport_upper == "NHL":
                    xg_diff = away_form.get('xg_diff_last_5', away_form.get('goal_diff_last_5', 0))
                    st.metric("xG Diff", f"{xg_diff:+.1f}")

            with metric_col2:
                record_long = away_form.get(f'record_last_{period_long}', away_form.get('record_last_10', 'N/A'))
                st.metric(f"Last {period_long}", record_long)

                if sport_upper == "NBA":
                    net_rating_10 = away_form.get('net_rating_last_10', 0)
                    st.metric("Net Rating (10)", f"{net_rating_10:+.1f}")

            diff_short = away_form.get(f'point_diff_last_{period_short}',
                         away_form.get(f'goal_diff_last_{period_short}',
                         away_form.get(f'run_diff_last_{period_short}',
                         away_form.get('point_diff_last_5', 0))))
            diff_long = away_form.get(f'point_diff_last_{period_long}',
                        away_form.get(f'goal_diff_last_{period_long}',
                        away_form.get(f'run_diff_last_{period_long}',
                        away_form.get('point_diff_last_10', 0))))
            st.caption(f"{diff_label}: L{period_short}: {diff_short:+.1f} | L{period_long}: {diff_long:+.1f}")
        else:
            st.caption("No form data available")

    # Sport-specific additional sections
    if sport_upper == "NHL" and (special_teams or home_form.get('power_play')):
        st.markdown("---")
        st.markdown("**Special Teams**")
        st_col1, st_col2 = st.columns(2)
        with st_col1:
            home_pp = home_form.get('power_play', special_teams.get('home_pp', 'N/A'))
            home_pk = home_form.get('penalty_kill', special_teams.get('home_pk', 'N/A'))
            st.caption(f"Home - PP: {home_pp}% | PK: {home_pk}%")
        with st_col2:
            away_pp = away_form.get('power_play', special_teams.get('away_pp', 'N/A'))
            away_pk = away_form.get('penalty_kill', special_teams.get('away_pk', 'N/A'))
            st.caption(f"Away - PP: {away_pp}% | PK: {away_pk}%")

    elif sport_upper == "MLB":
        st.markdown("---")
        st.markdown("**Offensive Stats**")
        off_col1, off_col2 = st.columns(2)
        with off_col1:
            runs_7 = home_form.get('runs_last_7', 'N/A')
            st.caption(f"Home - Runs/G (L7): {runs_7}")
        with off_col2:
            runs_7 = away_form.get('runs_last_7', 'N/A')
            st.caption(f"Away - Runs/G (L7): {runs_7}")

    elif sport_upper == "NFL":
        # Show turnover and rest info for NFL
        st.markdown("---")
        st.markdown("**Schedule & Turnovers**")
        nfl_col1, nfl_col2 = st.columns(2)
        with nfl_col1:
            turnover_adj = adjustments.get('turnover_adjustment', 0)
            st.metric("Turnover Adj", f"{turnover_adj*100:+.2f}%")
        with nfl_col2:
            rest_adj = adjustments.get('rest_adjustment', 0)
            st.metric("Rest Adj", f"{rest_adj*100:+.2f}%")

        # Weather if available
        weather_adj = adjustments.get('weather_adjustment', 0)
        if weather_adj != 0:
            st.caption(f"Weather Impact: {weather_adj*100:+.2f}%")


def fetch_predictions_from_api(sport: str, date: str = None, force_refresh: bool = False):
    """Fetch predictions from the backend API for a specific date (YYYYMMDD).

    The backend already returns the games listed on that (US Eastern) day, so no client-side date
    filtering is done here: an evening game on the 12th has a UTC game_date on the 13th.
    """
    if force_refresh:
        result = get_api_client().get_predictions(sport, date, force_refresh=True)
    else:
        result = cached("get_predictions", league=sport, date=date)

    if not result.get("success"):
        st.error(f"API Error: {result.get('error', 'Failed to fetch predictions')}")
        return []

    data = result.get("data") or {}
    predictions = data.get("predictions", []) if isinstance(data, dict) else data
    if not isinstance(predictions, list):
        return []

    transformed = []
    for pred in predictions:
        home_prob = pred.get("home_win_probability", pred.get("home_win_prob", 0.5))
        game_date_str = pred.get("game_date", "") or ""
        game_time = pred.get("game_time", pred.get("commence_time", "")) or game_date_str
        try:
            game_time = datetime.fromisoformat(str(game_time).replace("Z", "+00:00")).astimezone().strftime("%a %b %d, %I:%M %p")
        except Exception:
            pass

        market_odds = pred.get("market_odds") or {}
        team_form = pred.get("team_form") or {}
        home_form = team_form.get("home_form") or {}
        away_form = team_form.get("away_form") or {}
        rest = pred.get("rest") or {}

        transformed.append({
            **pred,
            "game_id": pred.get("game_id", ""),
            "home_team": pred.get("home_team", ""),
            "away_team": pred.get("away_team", ""),
            "home_team_abbr": pred.get("home_team_abbr", ""),
            "away_team_abbr": pred.get("away_team_abbr", ""),
            "home_win_prob": home_prob,
            "away_win_prob": pred.get("away_win_probability", 1 - home_prob),
            "confidence": pred.get("confidence", max(home_prob, 1 - home_prob)),
            "predicted_winner": pred.get("predicted_winner", ""),
            "game_date": game_date_str,
            "game_time": game_time,
            "venue": pred.get("venue", ""),
            "spread": market_odds.get("spread", pred.get("spread")),
            "moneyline_home": market_odds.get("moneyline_home", ""),
            "moneyline_away": market_odds.get("moneyline_away", ""),
            "over_under": market_odds.get("over_under", pred.get("over_under")),
            "home_record": home_form.get("season_record") or home_form.get("record_last_10", pred.get("home_record", "")),
            "away_record": away_form.get("season_record") or away_form.get("record_last_10", pred.get("away_record", "")),
            "base_home_probability": pred.get("base_home_probability", home_prob),
            "market_odds": market_odds,
            "team_form": team_form,
            "star_impact": pred.get("star_impact") or {},
            "qb_impact": pred.get("qb_impact") or pred.get("qb_status") or {},
            "pitcher_impact": pred.get("pitcher_impact") or {},
            "goalie_impact": pred.get("goalie_impact") or {},
            "special_teams": pred.get("special_teams") or {},
            "adjustments": pred.get("adjustments") or {},
            "feature_weights": pred.get("feature_weights") or {},
            "back_to_back_home": rest.get("home_back_to_back", pred.get("back_to_back_home", False)),
            "back_to_back_away": rest.get("away_back_to_back", pred.get("back_to_back_away", False)),
        })
    return transformed
