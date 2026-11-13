"""
API Client for communicating with the Sports Prediction Backend (backend/app, FastAPI).

Every method returns {"success": bool, "data": ..., "error": str} so pages never have to
handle requests exceptions themselves. File downloads (exports, backtest CSV) return the raw
bytes in "data" plus "filename" / "content_type".
"""
import json
from typing import Optional, Dict, Any, List

import requests
import streamlit as st

from config import API_BASE_URL, API_TIMEOUT, ADMIN_TOKEN

LEAGUES = ["NBA", "NFL", "MLB", "NHL"]


def _error_text(response: requests.Response) -> str:
    """Pull FastAPI's {"detail": ...} out of an error response when present."""
    try:
        body = response.json()
        detail = body.get("detail", body) if isinstance(body, dict) else body
        if isinstance(detail, list):  # pydantic validation errors
            detail = "; ".join(str(d.get("msg", d)) if isinstance(d, dict) else str(d) for d in detail)
        return f"HTTP {response.status_code}: {detail}"
    except ValueError:
        return f"HTTP {response.status_code}: {response.text[:300]}"


class APIClient:
    """Handles all API communications with the backend"""

    def __init__(self, base_url: str = API_BASE_URL):
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()

    # ------------------------------------------------------------------ plumbing
    def _headers(self, admin: bool = False) -> Dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        api_key = st.session_state.get("api_key") if hasattr(st, "session_state") else None
        if api_key:
            headers["X-API-Key"] = api_key
        if admin:
            token = st.session_state.get("admin_token") or ADMIN_TOKEN
            if token:
                headers["X-Admin-Token"] = token
        return headers

    def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        data: Optional[Dict] = None,
        timeout: int = API_TIMEOUT,
        admin: bool = False,
    ) -> Dict[str, Any]:
        """Make HTTP request to the API"""
        url = f"{self.base_url}{endpoint}"
        if params:
            params = {k: v for k, v in params.items() if v is not None}
        try:
            response = self.session.request(
                method=method, url=url, params=params, json=data, timeout=timeout,
                headers=self._headers(admin),
            )
            if response.status_code >= 400:
                return {"success": False, "status_code": response.status_code, "error": _error_text(response)}
            return {"success": True, "data": response.json()}
        except requests.exceptions.ConnectionError:
            return {"success": False, "error": "Connection failed. Is the backend running?"}
        except requests.exceptions.Timeout:
            return {"success": False, "error": "Request timed out"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _download(self, endpoint: str, params: Optional[Dict] = None, timeout: int = 120) -> Dict[str, Any]:
        """GET a file (CSV/PDF). Returns bytes in data."""
        url = f"{self.base_url}{endpoint}"
        if params:
            params = {k: v for k, v in params.items() if v is not None}
        try:
            headers = self._headers()
            headers.pop("Accept", None)
            response = self.session.get(url, params=params, timeout=timeout, headers=headers)
            if response.status_code >= 400:
                return {"success": False, "status_code": response.status_code, "error": _error_text(response)}
            filename = None
            disp = response.headers.get("Content-Disposition", "")
            if "filename=" in disp:
                filename = disp.split("filename=")[-1].strip('"; ')
            return {"success": True, "data": response.content, "filename": filename,
                    "content_type": response.headers.get("Content-Type", "application/octet-stream")}
        except requests.exceptions.ConnectionError:
            return {"success": False, "error": "Connection failed. Is the backend running?"}
        except requests.exceptions.Timeout:
            return {"success": False, "error": "Request timed out"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ------------------------------------------------------------------ auth / billing
    def login(self, identifier: str, api_key: str) -> Dict[str, Any]:
        """Authenticate user with the backend"""
        return self._make_request("POST", "/login", data={"identifier": identifier, "api_key": api_key})

    def get_profile(self) -> Dict[str, Any]:
        """Get user profile and subscription info"""
        return self._make_request("GET", "/profile")

    def create_checkout_session(self, plan: str, success_url: str, cancel_url: str) -> Dict[str, Any]:
        """Create a checkout session for a subscription plan"""
        data = {"plan_name": plan, "success_url": success_url, "cancel_url": cancel_url}
        return self._make_request("POST", "/subscriptions/checkout", data=data)

    def cancel_subscription(self) -> Dict[str, Any]:
        """Cancel the user's subscription"""
        return self._make_request("POST", "/subscriptions/cancel", data={"cancel_at_period_end": False})

    def health_check(self) -> Dict[str, Any]:
        """Check if the backend is running"""
        return self._make_request("GET", "/health", timeout=5)

    # ------------------------------------------------------------------ predictions
    def get_predictions(self, league: str, date: Optional[str] = None, force_refresh: bool = False,
                        include_players: bool = True, include_form: bool = True) -> Dict[str, Any]:
        """GET /api/predict/{league}?date=YYYYMMDD -> {date, total_games, predictions:[...]}"""
        params = {"date": date, "use_odds": True, "include_players": include_players,
                  "include_form": include_form, "force_refresh": force_refresh or None}
        return self._make_request("GET", f"/api/predict/{league.lower()}", params=params, timeout=max(API_TIMEOUT, 90))

    def get_nfl_predictions(self, date: Optional[str] = None) -> Dict[str, Any]:
        return self.get_predictions("NFL", date)

    def get_nba_predictions(self, date: Optional[str] = None, include_players: bool = True,
                            include_form: bool = True, force_refresh: bool = False) -> Dict[str, Any]:
        return self.get_predictions("NBA", date, force_refresh, include_players, include_form)

    def get_mlb_predictions(self, date: Optional[str] = None) -> Dict[str, Any]:
        return self.get_predictions("MLB", date)

    def get_nhl_predictions(self, date: Optional[str] = None) -> Dict[str, Any]:
        return self.get_predictions("NHL", date)

    def get_live_predictions(self, sport: str) -> Dict[str, Any]:
        """GET /api/predict/live/{league}"""
        return self._make_request("GET", f"/api/predict/live/{sport.lower()}", timeout=max(API_TIMEOUT, 90))

    def get_prediction(self, league: str, game_id: str) -> Dict[str, Any]:
        """Get prediction for a specific game"""
        return self._make_request("GET", f"/api/predict/{league.lower()}/{game_id}", timeout=max(API_TIMEOUT, 60))

    def explain_prediction(self, league: str, game_id: str) -> Dict[str, Any]:
        """GET /api/predict/{league}/{game_id}/explain -> features[{name,contribution,text}], key_factors"""
        return self._make_request("GET", f"/api/predict/{league.lower()}/{game_id}/explain", timeout=max(API_TIMEOUT, 60))

    def recalculate(self, sport: str, game_id: Any, custom_spread: Optional[float] = None,
                    custom_over_under: Optional[float] = None, home_win_probability: Optional[float] = None,
                    is_live: bool = False, home_score: int = 0, away_score: int = 0,
                    period: Any = None, clock: Optional[str] = None) -> Dict[str, Any]:
        """POST /api/predict/recalculate with user-edited spread / O-U lines."""
        body = {"game_id": str(game_id), "sport": sport.upper(), "custom_spread": custom_spread,
                "custom_over_under": custom_over_under, "home_win_probability": home_win_probability,
                "is_live": is_live, "home_score": int(home_score or 0), "away_score": int(away_score or 0),
                "period": period, "clock": clock}
        return self._make_request("POST", "/api/predict/recalculate", data=body)

    def export_predictions(self, league: str, date: Optional[str] = None, fmt: str = "csv") -> Dict[str, Any]:
        """GET /api/export/{league}?date=&format=csv|pdf -> file bytes"""
        return self._download(f"/api/export/{league.lower()}", params={"date": date, "format": fmt})

    # ------------------------------------------------------------------ sport data
    def get_teams(self, league: str) -> Dict[str, Any]:
        return self._make_request("GET", f"/api/{league.lower()}/teams")

    def get_team_form(self, league: str, team_abbr: str) -> Dict[str, Any]:
        return self._make_request("GET", f"/api/{league.lower()}/team/{team_abbr}/form")

    def get_schedule(self, league: str, days: int = 7) -> Dict[str, Any]:
        return self._make_request("GET", f"/api/{league.lower()}/schedule", params={"days": days})

    def get_nfl_team_form(self, team_abbr: str) -> Dict[str, Any]:
        return self.get_team_form("NFL", team_abbr)

    def get_nba_team_form(self, team_abbr: str) -> Dict[str, Any]:
        return self.get_team_form("NBA", team_abbr)

    def get_nfl_qbs(self) -> Dict[str, Any]:
        return self._make_request("GET", "/api/nfl/qbs")

    def get_nba_players(self) -> Dict[str, Any]:
        return self._make_request("GET", "/api/nba/players")

    def get_mlb_pitchers(self) -> Dict[str, Any]:
        return self._make_request("GET", "/api/mlb/pitchers")

    def get_nhl_goalies(self) -> Dict[str, Any]:
        return self._make_request("GET", "/api/nhl/goalies")

    # ------------------------------------------------------------------ models / training
    def get_models(self) -> Dict[str, Any]:
        """GET /api/models -> {leagues:{NBA:{is_trained, models_in_ensemble, accuracy, ...}}, model_types}"""
        return self._make_request("GET", "/api/models")

    def get_model_performance(self, league: str) -> Dict[str, Any]:
        """GET /api/models/{LEAGUE}/performance -> metrics, weights, history, tracked_accuracy"""
        return self._make_request("GET", f"/api/models/{league.upper()}/performance")

    def train_model(self, league: str, backfill_first: bool = False, seasons: int = 2) -> Dict[str, Any]:
        """POST /api/models/train/{league} (admin) -> {job_id}"""
        return self._make_request("POST", f"/api/models/train/{league.lower()}",
                                  data={"backfill_first": backfill_first, "seasons": seasons}, admin=True)

    # ------------------------------------------------------------------ jobs / notifications / logs
    def get_job(self, job_id: str) -> Dict[str, Any]:
        """GET /api/jobs/{id} -> {status, progress 0..1, eta_seconds, message, result}"""
        return self._make_request("GET", f"/api/jobs/{job_id}")

    def list_jobs(self, limit: int = 30, kind: Optional[str] = None) -> Dict[str, Any]:
        return self._make_request("GET", "/api/jobs", params={"limit": limit, "kind": kind})

    def cancel_job(self, job_id: str) -> Dict[str, Any]:
        return self._make_request("POST", f"/api/jobs/{job_id}/cancel", admin=True)

    def get_notifications(self, since: Optional[str] = None) -> Dict[str, Any]:
        return self._make_request("GET", "/api/notifications", params={"since": since}, timeout=10)

    def get_logs(self, level: str = "all", limit: int = 100, search: Optional[str] = None,
                 source: Optional[str] = None, persisted: bool = False) -> Dict[str, Any]:
        """GET /api/logs?level=&limit=&search=&source="""
        params = {"level": level or "all", "limit": limit, "search": search or None, "source": source or None,
                  "persisted": persisted or None}
        return self._make_request("GET", "/api/logs", params=params)

    # ------------------------------------------------------------------ backtesting
    def run_backtest(self, config: Dict) -> Dict[str, Any]:
        """POST /api/backtest/run -> {backtest_id}"""
        return self._make_request("POST", "/api/backtest/run", data=config)

    def get_backtest_results(self, backtest_id: str) -> Dict[str, Any]:
        """GET /api/backtest/{id} -> job dict (status, progress, eta_seconds, result)"""
        return self._make_request("GET", f"/api/backtest/{backtest_id}")

    def get_backtest(self, backtest_id: str) -> Dict[str, Any]:
        return self.get_backtest_results(backtest_id)

    def get_backtest_csv(self, backtest_id: str) -> Dict[str, Any]:
        """GET /api/backtest/{id}?format=csv -> bets CSV bytes"""
        return self._download(f"/api/backtest/{backtest_id}", params={"format": "csv"})

    def list_backtests(self, limit: int = 20) -> Dict[str, Any]:
        return self._make_request("GET", "/api/backtests", params={"limit": limit})

    # ------------------------------------------------------------------ simulations
    def run_simulation(self, config: Dict) -> Dict[str, Any]:
        """POST /api/simulations/run with {league, game_id} or custom expected scores."""
        return self._make_request("POST", "/api/simulations/run", data=config, timeout=max(API_TIMEOUT, 90))

    def get_simulation_results(self, simulation_id: str) -> Dict[str, Any]:
        return self._make_request("GET", f"/api/simulations/{simulation_id}")

    def get_simulation(self, simulation_id: str) -> Dict[str, Any]:
        return self.get_simulation_results(simulation_id)

    # ------------------------------------------------------------------ historical / accuracy
    def get_accuracy(self, league: str, days: int = 90) -> Dict[str, Any]:
        """GET /api/accuracy/{league}?days= -> {accuracy, settled_predictions, series:[{date, accuracy, ...}]}"""
        return self._make_request("GET", f"/api/accuracy/{league.lower()}", params={"days": days})

    def get_historical_games(self, league: str, start_date: Optional[str] = None, end_date: Optional[str] = None,
                             team: Optional[str] = None, limit: int = 500) -> Dict[str, Any]:
        params = {"start_date": start_date, "end_date": end_date, "team": team, "limit": limit}
        return self._make_request("GET", f"/api/historical/games/{league.lower()}", params=params)


@st.cache_resource
def get_api_client() -> APIClient:
    """Get a cached API client instance"""
    return APIClient()


def check_backend_status() -> bool:
    """Quick check if backend is available"""
    return get_api_client().health_check().get("success", False)


# ---------------------------------------------------------------------------------------------
# Short-lived caching for read-only calls that several pages share (predictions take seconds).
# Failed calls raise inside the cached function so errors are never cached.
# ---------------------------------------------------------------------------------------------
class _APIFailure(Exception):
    pass


@st.cache_data(ttl=60, show_spinner=False)
def _cached_call(method_name: str, args_json: str, cache_scope: str):
    client = get_api_client()
    result = getattr(client, method_name)(**json.loads(args_json))
    if not result.get("success"):
        raise _APIFailure(result.get("error", "request failed"))
    return result


def cached(method_name: str, **kwargs) -> Dict[str, Any]:
    """Call an APIClient method with a 60 s cache, e.g. cached("get_predictions", league="NBA")."""
    api_key = st.session_state.get("api_key")
    try:
        return _cached_call(method_name, json.dumps(kwargs, sort_keys=True, default=str), str(api_key))
    except _APIFailure as e:
        return {"success": False, "error": str(e)}


def clear_cache() -> None:
    _cached_call.clear()


def fmt_eta(seconds: Optional[float]) -> str:
    """Human-readable ETA for job progress bars."""
    if seconds is None:
        return "estimating..."
    seconds = int(max(0, seconds))
    if seconds < 60:
        return f"{seconds}s"
    m, s = divmod(seconds, 60)
    if m < 60:
        return f"{m}m {s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m"


def export_bytes(league: str, date: Optional[str], fmt: str, api_key: Optional[str] = None) -> bytes:
    """Fetch /api/export/{league} as bytes. Safe to call from st.download_button's deferred callable
    (runs off the script thread, so it must not touch st.session_state)."""
    headers = {"X-API-Key": api_key} if api_key else {}
    try:
        r = requests.get(f"{API_BASE_URL.rstrip('/')}/api/export/{league.lower()}",
                         params={k: v for k, v in {"date": date, "format": fmt}.items() if v},
                         headers=headers, timeout=120)
        if r.status_code >= 400:
            return f"Export failed: {_error_text(r)}".encode()
        return r.content
    except requests.exceptions.RequestException as e:
        return f"Export failed: {e}".encode()
