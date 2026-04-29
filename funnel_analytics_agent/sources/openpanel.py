"""OpenPanel events source.

Reads OpenPanel server-side API to count specific events over the last 24h.
Configure which events to track via OPENPANEL_TRACKED_EVENTS env var
(comma-separated names, default: signup_completed,project_submit_completed).

Auth: OpenPanel uses a CLIENT_ID + CLIENT_SECRET pair distinct from the
public client ID used by the JS SDK. Generate the secret in the OpenPanel
dashboard → Project settings → Clients.

Env vars:
  OPENPANEL_CLIENT_ID
  OPENPANEL_CLIENT_SECRET
  OPENPANEL_PROJECT_ID            (optional if your client maps to one project)
  OPENPANEL_TRACKED_EVENTS        (comma-separated; default: signup_completed,project_submit_completed)
  OPENPANEL_API_BASE              (default: https://api.openpanel.dev)

Notes:
- v0.2 reports counts only. v0.3 will add 7-day baseline + delta_pct.
- If the API is rate-limited or unauthenticated, fetch() returns
  SourceReport with error set; never raises.
"""
from __future__ import annotations
import os
import json
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timezone, timedelta
from .base import MetricSample, Source, SourceReport


DEFAULT_EVENTS = "signup_completed,project_submit_completed"


class OpenPanelSource(Source):
    name = "openpanel"

    @property
    def configured(self) -> bool:
        return bool(os.getenv("OPENPANEL_CLIENT_ID")) \
           and bool(os.getenv("OPENPANEL_CLIENT_SECRET"))

    def _api_base(self) -> str:
        return os.getenv("OPENPANEL_API_BASE", "https://api.openpanel.dev")

    def _query_events(self, event_name: str, since_iso: str) -> int | None:
        """Return count of events with this name since `since_iso`, or None
        if the API request failed."""
        client_id = os.getenv("OPENPANEL_CLIENT_ID", "")
        client_secret = os.getenv("OPENPANEL_CLIENT_SECRET", "")
        params = {"name": event_name, "since": since_iso}
        project_id = os.getenv("OPENPANEL_PROJECT_ID")
        if project_id:
            params["project_id"] = project_id
        qs = urllib.parse.urlencode(params)
        url = f"{self._api_base()}/v1/events/count?{qs}"
        req = urllib.request.Request(url, headers={
            "openpanel-client-id": client_id,
            "openpanel-client-secret": client_secret,
            "Accept": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read().decode())
            return int(data.get("count", 0))
        except Exception:
            return None

    def fetch(self) -> SourceReport:
        now = datetime.now(timezone.utc)
        report = SourceReport(source=self.name, fetched_at=now)
        if not self.configured:
            report.error = "missing OPENPANEL_CLIENT_ID or OPENPANEL_CLIENT_SECRET"
            return report

        events = os.getenv("OPENPANEL_TRACKED_EVENTS", DEFAULT_EVENTS)
        event_names = [e.strip() for e in events.split(",") if e.strip()]
        since = (now - timedelta(hours=24)).isoformat()

        any_failure = False
        for name in event_names:
            count = self._query_events(name, since)
            if count is None:
                any_failure = True
                continue
            # Heuristic: if a tracked event is at 0 over 24h and it's not
            # mid-night, surface as a warn (could be a tracking regression)
            severity = "warn" if count == 0 else "info"
            report.metrics.append(MetricSample(
                name=f"events_{name}_24h",
                value=count,
                severity=severity,
                note=f"{name}: {count} in last 24h" + (
                    " — 0 events: tracking regression?" if count == 0 else ""),
            ))

        if any_failure and not report.metrics:
            report.error = "all OpenPanel API calls failed (auth or rate-limit?)"

        return report
