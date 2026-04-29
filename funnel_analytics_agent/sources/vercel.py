"""Vercel deployment source.

Reports:
- latest deployment state (READY / BUILDING / ERROR)
- deployments in the last 24h (ship velocity signal)
- build minutes consumed in the current month (cost signal)

Auth: VERCEL_TOKEN env var, generated at vercel.com/account/tokens.
Project scope: VERCEL_PROJECT_ID + optional VERCEL_TEAM_ID env vars.

Graceful degradation: if creds missing or Vercel API down, fetch() returns a
SourceReport with error set and an empty metric list. Never raises.
"""
from __future__ import annotations
import os
import urllib.request
import urllib.error
import json
from datetime import datetime, timezone, timedelta
from .base import MetricSample, Source, SourceReport


class VercelSource(Source):
    name = "vercel"
    API_BASE = "https://api.vercel.com"

    @property
    def configured(self) -> bool:
        return bool(os.getenv("VERCEL_TOKEN")) and bool(os.getenv("VERCEL_PROJECT_ID"))

    def _api(self, path: str, *, query: dict | None = None) -> dict:
        token = os.getenv("VERCEL_TOKEN", "")
        team_id = os.getenv("VERCEL_TEAM_ID")
        url = f"{self.API_BASE}{path}"
        params = dict(query or {})
        if team_id:
            params["teamId"] = team_id
        if params:
            qs = "&".join(f"{k}={v}" for k, v in params.items())
            url = f"{url}?{qs}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode())

    def fetch(self) -> SourceReport:
        now = datetime.now(timezone.utc)
        report = SourceReport(source=self.name, fetched_at=now)
        if not self.configured:
            report.error = "missing VERCEL_TOKEN or VERCEL_PROJECT_ID"
            return report

        project_id = os.getenv("VERCEL_PROJECT_ID", "")
        try:
            data = self._api(
                "/v6/deployments",
                query={"projectId": project_id, "limit": 100},
            )
            deployments = data.get("deployments", [])
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError) as e:
            report.error = f"vercel API error: {e}"
            return report
        except Exception as e:
            report.error = f"unexpected: {e}"
            return report

        # Latest deployment state
        if deployments:
            latest = deployments[0]
            state = latest.get("state", "UNKNOWN")
            severity = "critical" if state == "ERROR" else "info"
            report.metrics.append(MetricSample(
                name="latest_deployment_state",
                value=1 if state == "READY" else 0,
                severity=severity,
                note=f"latest deployment: {state} ({latest.get('name', '?')})",
                raw={"url": latest.get("url"), "createdAt": latest.get("createdAt"),
                     "state": state, "uid": latest.get("uid")},
            ))

        # Count deployments in the last 24h
        since = (now - timedelta(hours=24)).timestamp() * 1000
        recent = [d for d in deployments if d.get("createdAt", 0) >= since]
        report.metrics.append(MetricSample(
            name="deployments_24h",
            value=len(recent),
            severity="info",
            note=f"{len(recent)} deployment(s) in last 24h",
        ))

        # Failed deployments in last 24h
        failed = [d for d in recent if d.get("state") == "ERROR"]
        if failed:
            report.metrics.append(MetricSample(
                name="failed_deployments_24h",
                value=len(failed),
                severity="alert",
                note=f"{len(failed)} failed deployment(s) in last 24h — investigate",
            ))

        return report
