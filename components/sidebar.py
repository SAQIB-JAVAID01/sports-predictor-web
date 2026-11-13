"""
Sidebar navigation component for the Sports Prediction Platform
"""
import streamlit as st
from streamlit_option_menu import option_menu
from config import SPORTS, APP_NAME, APP_VERSION
from utils.api_client import get_api_client, cached

QUICK_STAT_COLORS = {"NFL": "#4CAF50", "NBA": "#00BCF2", "MLB": "#FF9800", "NHL": "#F44336"}


def _stat_tile(value: str, label: str, color: str):
    st.markdown(f"""
    <div style="background: linear-gradient(145deg, #2D2D30 0%, #252526 100%);
                border-radius: 8px; padding: 0.75rem; text-align: center;
                border: 1px solid rgba(255,255,255,0.08);">
        <div style="font-size: 1.25rem; font-weight: 700; color: {color};">{value}</div>
        <div style="font-size: 0.625rem; color: #8A8A8A;">{label}</div>
    </div>
    """, unsafe_allow_html=True)


def render_quick_stats():
    """Per-league model accuracy from /api/models (cached 60 s)."""
    res = cached("get_models") if st.session_state.get("backend_online") else {"success": False}
    leagues = (res.get("data") or {}).get("leagues", {}) if res.get("success") else {}
    order = ["NFL", "NBA", "MLB", "NHL"]
    for row in (order[:2], order[2:]):
        cols = st.columns(2)
        for col, lg in zip(cols, row):
            info = leagues.get(lg, {})
            acc = info.get("accuracy")
            with col:
                if info.get("is_trained") and isinstance(acc, (int, float)):
                    _stat_tile(f"{acc * 100:.1f}%", f"{lg} Accuracy", QUICK_STAT_COLORS[lg])
                else:
                    _stat_tile("--", f"{lg} {'untrained' if leagues else 'offline'}", "#8A8A8A")
        st.markdown("<div style='height: 0.5rem;'></div>", unsafe_allow_html=True)


def render_sidebar_notifications():
    """Finished background jobs and recent errors (GET /api/notifications)."""
    if not st.session_state.get("backend_online"):
        return
    res = get_api_client().get_notifications()
    if not res.get("success"):
        return
    notes = res["data"].get("notifications", [])
    jobs = [n for n in notes if n.get("type") == "job"]
    # toast jobs that finished since this session last looked
    seen = st.session_state.setdefault("seen_notifications", None)
    ids = {n.get("job_id") or n.get("timestamp") for n in notes}
    if seen is not None:
        for n in jobs:
            if (n.get("job_id") or n.get("timestamp")) not in seen:
                st.toast(f"{n.get('title')}: {n.get('message', '')[:120]}",
                         icon="✅" if n.get("level") == "success" else "⚠️")
    st.session_state.seen_notifications = ids
    if not notes:
        return
    with st.expander(f"🔔 Notifications ({len(notes)})", expanded=False):
        for n in notes[:8]:
            icon = "✅" if n.get("level") == "success" else "⚠️"
            when = (n.get("timestamp") or "")[11:16]
            st.markdown(f"{icon} **{n.get('title')}** <span style='color:#8A8A8A;font-size:0.7rem;'>{when} UTC</span>",
                        unsafe_allow_html=True)
            if n.get("message"):
                st.caption(n["message"][:160])


def render_sidebar() -> str:
    """Render the sidebar navigation and return selected page"""

    with st.sidebar:
        # Logo and branding
        st.markdown("""
        <div style="text-align: center; padding: 0rem 0 1rem 0;">
            <div style="font-size: 2.5rem; margin-bottom: 0.5rem;">🎯</div>
            <div style="font-size: 1.25rem; font-weight: 700; color: #FFFFFF;">Sports Prediction</div>
            <div style="font-size: 0.75rem; color: #8A8A8A;">Platform v{}</div>
        </div>
        """.format(APP_VERSION), unsafe_allow_html=True)

        st.markdown("---")

        # User Authentication Section
        if not st.session_state.get('is_logged_in', False):
            st.markdown("""
            <div style="padding: 0 0.5rem 0.75rem 0.5rem;">
                <div style="font-size: 0.75rem; color: #8A8A8A; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 0.5rem;">
                    User Login
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            with st.form("sidebar_login_form", border=False, enter_to_submit=False):
                identifier = st.text_input("Identifier", placeholder="identifier", label_visibility="collapsed")
                api_key_input = st.text_input("API Key", type="password", placeholder="enter api key", label_visibility="collapsed")
                submit = st.form_submit_button("Login", use_container_width=True)
                
                if submit:
                    if identifier and api_key_input:
                        client = get_api_client()
                        response = client.login(identifier, api_key_input)
                        
                        if response.get("success"):
                            data = response.get("data", {})
                            st.session_state.api_key = data.get("api_key")
                            st.session_state.username = data.get("identifier")
                            
                            # Fetch plan info separately as it's no longer in login response
                            profile_response = client.get_profile()
                            if profile_response.get("success"):
                                profile_data = profile_response.get("data", {})
                                st.session_state.active_plan = profile_data.get("plan", "free")
                            else:
                                st.session_state.active_plan = "free"

                            st.session_state.is_logged_in = True
                            st.success("Logged in!")
                            st.rerun()
                        else:
                            st.error("Login failed")
                    else:
                        st.warning("Enter credentials")
        else:
            # Logged in user info
            st.markdown(f"""
            <div style="background: linear-gradient(145deg, #2D2D30 0%, #252526 100%);
                        border-radius: 8px; padding: 1rem; text-align: left;
                        border: 1px solid rgba(255,255,255,0.08); margin-bottom: 1rem;">
                <div style="font-size: 0.7rem; color: #8A8A8A; text-transform: uppercase; margin-bottom: 0.4rem;">Logged in as</div>
                <div style="font-size: 1rem; font-weight: 700; color: #FFFFFF; margin-bottom: 0.75rem; display: flex; align-items: center; gap: 0.5rem;">
                    <span style="font-size: 1.2rem;">👤</span> {st.session_state.username}
                </div>
                <div style="font-size: 0.7rem; color: #8A8A8A; text-transform: uppercase; margin-bottom: 0.4rem;">Current Plan</div>
                <div style="font-size: 0.9rem; font-weight: 600; color: #4CAF50; display: flex; align-items: center; gap: 0.5rem;">
                    <span style="font-size: 1rem;">⭐</span> {st.session_state.active_plan}
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            if st.button("Logout", use_container_width=True):
                st.session_state.is_logged_in = False
                st.session_state.api_key = None
                st.session_state.username = None
                st.session_state.active_plan = None
                st.rerun()

        st.markdown("---")

        # Main navigation menu
        selected = option_menu(
            menu_title=None,
            options=[
                "Dashboard",
                "🏀 NBA",
                "🏈 NFL",
                "⚾ MLB",
                "🏒 NHL",
                "Models",
                "Simulations",
                "Backtesting",
                "Logs",
                "Billing",
                "Settings"
            ],
            icons=[
                "speedometer2",
                "",
                "",
                "",
                "",
                "cpu",
                "graph-up-arrow",
                "clock-history",
                "terminal",
                "credit-card",
                "gear"
            ],
            menu_icon="cast",
            default_index=0,
            styles={
                "container": {
                    "padding": "0",
                    "background-color": "transparent"
                },
                "icon": {
                    "color": "#00BCF2",
                    "font-size": "1rem"
                },
                "nav-link": {
                    "font-size": "0.875rem",
                    "text-align": "left",
                    "padding": "0.75rem 1rem",
                    "border-radius": "8px",
                    "margin": "2px 0",
                    "color": "#CCCCCC",
                    "background-color": "transparent",
                    "--hover-color": "#2D2D30"
                },
                "nav-link-selected": {
                    "background": "linear-gradient(135deg, #0078D4 0%, #106EBE 100%)",
                    "color": "white",
                    "font-weight": "600"
                }
            }
        )

        st.markdown("---")

        # Quick stats section
        st.markdown("""
        <div style="padding: 0.5rem;">
            <div style="font-size: 0.75rem; color: #8A8A8A; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 0.75rem;">
                Quick Stats
            </div>
        </div>
        """, unsafe_allow_html=True)

        # Sport stats cards (holdout accuracy of each league's trained model)
        render_quick_stats()

        render_sidebar_notifications()

        st.markdown("---")

        # Backend status indicator
        if 'backend_status' not in st.session_state:
            st.session_state.backend_status = "checking"

        status_color = "#4CAF50" if st.session_state.get('backend_online', False) else "#F44336"
        status_text = "Online" if st.session_state.get('backend_online', False) else "Offline"

        st.markdown(f"""
        <div style="display: flex; align-items: center; gap: 0.5rem; padding: 0.75rem;
                    background: rgba(255,255,255,0.05); border-radius: 8px;">
            <div style="width: 8px; height: 8px; border-radius: 50%; background: {status_color};
                        box-shadow: 0 0 8px {status_color};"></div>
            <span style="font-size: 0.75rem; color: #CCCCCC;">Backend: {status_text}</span>
        </div>
        """, unsafe_allow_html=True)

        # Footer
        st.markdown("""
        <div style="position: absolute; bottom: 1rem; left: 1rem; right: 1rem;">
            <div style="font-size: 0.625rem; color: #666; text-align: center;">
                © 2024 Sports Prediction Platform
            </div>
        </div>
        """, unsafe_allow_html=True)

    return selected


def render_sport_submenu(sport: str) -> str:
    """Render sport-specific submenu"""
    config = SPORTS.get(sport, {})

    tabs = ["Predictions", "Team Analysis", "Historical Data", "Live Odds"]

    selected_tab = option_menu(
        key=f"{sport}_submenu",
        menu_title=None,
        options=tabs,
        icons=["lightning", "people", "clock-history", "graph-up"],
        orientation="horizontal",
        styles={
            "container": {
                "padding": "0",
                "background-color": "rgba(45,45,48,0.5)",
                "border-radius": "10px",
                "margin-bottom": "1rem"
            },
            "icon": {
                "font-size": "0.875rem"
            },
            "nav-link": {
                "font-size": "0.8125rem",
                "padding": "0.625rem 1rem",
                "margin": "0 2px",
                "border-radius": "8px",
                "color": "#CCCCCC"
            },
            "nav-link-selected": {
                "background": f"linear-gradient(135deg, {config.get('color', '#0078D4')} 0%, #106EBE 100%)",
                "color": "white"
            }
        }
    )

    return selected_tab
