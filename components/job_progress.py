"""
Progress bar + ETA for backend background jobs (training, backtests, backfills).

Usage:
    job = track_job("models_train_job")   # job_id stored in st.session_state["models_train_job"]
    if job and job["status"] == "completed": ...

While the job is queued/running a fragment re-polls /api/jobs/{id} every couple of seconds and
reruns the page once the job finishes, so results appear without a manual refresh.
"""
from typing import Any, Dict, Optional

import streamlit as st

from utils.api_client import get_api_client, fmt_eta

ACTIVE = ("queued", "running")


def _fetch(job_id: str, getter: str) -> Dict[str, Any]:
    return getattr(get_api_client(), getter)(job_id)


def _render_bar(job: Dict[str, Any], label: str) -> None:
    progress = float(job.get("progress") or 0.0)
    status = job.get("status", "queued")
    msg = job.get("message") or status.title()
    eta = fmt_eta(job.get("eta_seconds")) if status == "running" else "waiting for a worker"
    st.progress(min(max(progress, 0.0), 1.0), text=f"{label}: {progress * 100:.0f}% | ETA {eta}")
    st.caption(msg)


def track_job(state_key: str, label: str = "Job", getter: str = "get_job",
              poll_seconds: float = 2.0) -> Optional[Dict[str, Any]]:
    """Render the job stored under st.session_state[state_key]; returns the latest job dict."""
    job_id = st.session_state.get(state_key)
    if not job_id:
        return None
    res = _fetch(job_id, getter)
    if not res.get("success"):
        st.error(f"Could not read job status: {res.get('error')}")
        return None
    job = res["data"]
    if job.get("status") not in ACTIVE:
        return job

    @st.fragment(run_every=poll_seconds)
    def _poll():
        r = _fetch(job_id, getter)
        if not r.get("success"):
            st.warning(f"Lost contact with job: {r.get('error')}")
            return
        j = r["data"]
        if j.get("status") not in ACTIVE:
            st.rerun()  # whole page re-renders with the finished result
        _render_bar(j, label)

    _poll()
    return job


def render_job_outcome(job: Dict[str, Any], label: str = "Job") -> None:
    """One-line outcome banner for a finished job."""
    status = job.get("status")
    if status == "completed":
        st.success(f"{label} completed: {job.get('message', '')}")
    elif status == "failed":
        st.error(f"{label} failed: {job.get('message', '')}")
        trace = (job.get("result") or {}).get("trace")
        if trace:
            with st.expander("Error details"):
                st.code(trace)
    elif status == "cancelled":
        st.warning(f"{label} was cancelled.")
