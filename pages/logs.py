"""
Logs Page - live backend logs (/api/logs), background jobs and notifications
"""
from collections import Counter
from datetime import datetime

import pandas as pd
import streamlit as st

from components import render_header, render_stat_card, render_log_entry
from utils.api_client import get_api_client

LEVELS = ["All", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


def _ts(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return iso or ""


def render_logs_page():
    """Render the logs page"""

    render_header(
        title="System Logs",
        subtitle="Backend activity, errors and background jobs"
    )

    col1, col2, col3, col4 = st.columns([1, 1, 2, 1])
    with col1:
        level = st.selectbox("Minimum Level", LEVELS, key="log_level")
    with col2:
        limit = st.selectbox("Entries", [50, 100, 250, 500, 1000], index=1, key="log_limit")
    with col3:
        search = st.text_input("Search messages", key="log_search")
    with col4:
        source = st.text_input("Source contains", key="log_source")

    col_a, col_b, col_c = st.columns([1, 1, 2])
    with col_a:
        auto = st.toggle("Auto-refresh (5s)", value=False, key="log_auto")
    with col_b:
        if st.button("🔄 Refresh Now", key="log_refresh"):
            st.rerun()
    with col_c:
        persisted = st.checkbox("Include persisted history (warnings and errors kept across restarts)",
                                value=False, key="log_persisted")

    st.divider()

    tab1, tab2, tab3 = st.tabs(["All Logs", "Errors & Warnings", "Jobs & Notifications"])

    if auto:
        @st.fragment(run_every=5)
        def _live():
            _render_logs_body(level, limit, search, source, persisted)
        with tab1:
            _live()
    else:
        with tab1:
            _render_logs_body(level, limit, search, source, persisted)

    with tab2:
        render_error_logs()
    with tab3:
        render_jobs_and_notifications()


def _render_logs_body(level, limit, search, source, persisted):
    res = get_api_client().get_logs(level=level.lower() if level == "All" else level, limit=int(limit),
                                    search=search or None, source=source or None, persisted=persisted)
    if not res.get("success"):
        st.error(f"Could not load logs: {res.get('error')}")
        return
    logs = res["data"].get("logs", [])
    if persisted and (search or source):
        q, s = (search or "").lower(), (source or "").lower()
        logs = [l for l in logs if q in l.get("message", "").lower() and s in l.get("source", "").lower()]

    counts = Counter(l.get("level") for l in logs)
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        render_stat_card("Entries Shown", f"{len(logs):,}", icon="📊")
    with c2:
        render_stat_card("Errors", str(counts.get("ERROR", 0) + counts.get("CRITICAL", 0)), icon="⚠️")
    with c3:
        render_stat_card("Warnings", str(counts.get("WARNING", 0)), icon="⚡")
    with c4:
        render_stat_card("Info", str(counts.get("INFO", 0)), icon="ℹ️")

    if not logs:
        st.info("No log entries match these filters.")
        return

    view = st.radio("View", ["Table", "Cards"], horizontal=True, key="log_view", label_visibility="collapsed")
    if view == "Table":
        df = pd.DataFrame([{"Time": _ts(l.get("timestamp")), "Level": l.get("level"), "Source": l.get("source"),
                            "Message": l.get("message")} for l in logs])
        st.dataframe(df, width="stretch", hide_index=True, height=520)
    else:
        for l in logs[:200]:
            render_log_entry(timestamp=_ts(l.get("timestamp")), level=l.get("level", "INFO"),
                             message=l.get("message", ""), source=l.get("source", ""))

    st.download_button("📥 Export CSV", data=pd.DataFrame(logs).to_csv(index=False),
                       file_name=f"logs_{datetime.now().strftime('%Y%m%d_%H%M')}.csv", mime="text/csv",
                       key="log_export")


def render_error_logs():
    """Recent errors and warnings"""
    client = get_api_client()
    errs = client.get_logs(level="ERROR", limit=50)
    warns = client.get_logs(level="WARNING", limit=100)
    if not errs.get("success"):
        st.error(f"Could not load logs: {errs.get('error')}")
        return

    st.subheader("Recent Errors")
    error_items = errs["data"].get("logs", [])
    if not error_items:
        st.success("No errors in the backend log buffer.")
    for e in error_items:
        st.error(f"**{e.get('level')}** - {_ts(e.get('timestamp'))}\n\n{e.get('message')}\n\n_Source: {e.get('source')}_")

    st.divider()
    st.subheader("Recent Warnings")
    warn_items = [w for w in warns.get("data", {}).get("logs", []) if w.get("level") == "WARNING"]
    if not warn_items:
        st.info("No warnings.")
    for w in warn_items[:50]:
        st.warning(f"**{_ts(w.get('timestamp'))}** | _{w.get('source')}_\n\n{w.get('message')}")


def render_jobs_and_notifications():
    """Background jobs and the notification feed"""
    client = get_api_client()

    st.subheader("Notifications (last 24h)")
    nres = client.get_notifications()
    if nres.get("success"):
        notes = nres["data"].get("notifications", [])
        if not notes:
            st.info("No notifications.")
        for n in notes[:30]:
            text = f"**{n.get('title')}** - {_ts(n.get('timestamp'))}\n\n{n.get('message')}"
            (st.success if n.get("level") == "success" else st.error)(text)
    else:
        st.error(f"Could not load notifications: {nres.get('error')}")

    st.divider()
    st.subheader("Background Jobs")
    jres = client.list_jobs(limit=50)
    if not jres.get("success"):
        st.error(f"Could not load jobs: {jres.get('error')}")
        return
    jobs = jres["data"].get("jobs", [])
    if not jobs:
        st.info("No jobs yet.")
        return
    df = pd.DataFrame([{
        "Created": _ts(j.get("created_at")), "Kind": j.get("kind"), "League": j.get("league"),
        "Status": j.get("status"), "Progress": j.get("progress") or 0, "Message": j.get("message"),
        "Finished": _ts(j.get("finished_at")) if j.get("finished_at") else "",
    } for j in jobs])
    st.dataframe(df, width="stretch", hide_index=True, column_config={
        "Progress": st.column_config.ProgressColumn("Progress", min_value=0.0, max_value=1.0, format="percent"),
    })
