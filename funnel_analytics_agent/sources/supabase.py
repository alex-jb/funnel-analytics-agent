"""Supabase advisor source.

Uses Supabase Management API to fetch security + performance advisors.
Surfaces any CRITICAL or WARN advisor as a metric, with severity mapped:
- CRITICAL advisor → severity="critical"
- WARN advisor     → severity="warn"
- INFO advisor     → severity="info"

Auth: SUPABASE_PERSONAL_ACCESS_TOKEN env var, generated at
https://supabase.com/dashboard/account/tokens (NOT the project anon/service
key — those don't have advisor access).

Project scope: SUPABASE_PROJECT_REF (the slug in your dashboard URL,
e.g. "yjqmquesxwlsmqowoahl").

Designed for: morning brief that catches new advisor flags within 24h
of any DDL change. The 2026-04-29 vibex incident (auth_users_exposed
missed for months) is exactly the failure mode this prevents.
"""
from __future__ import annotations
import os
import json
import urllib.request
import urllib.error
from datetime import datetime, timezone
from .base import MetricSample, Source, SourceReport


SEVERITY_MAP = {
    "ERROR": "critical",
    "WARN": "warn",
    "INFO": "info",
}


class SupabaseAdvisorSource(Source):
    name = "supabase_advisor"
    API_BASE = "https://api.supabase.com"

    @property
    def configured(self) -> bool:
        return bool(os.getenv("SUPABASE_PERSONAL_ACCESS_TOKEN")) \
           and bool(os.getenv("SUPABASE_PROJECT_REF"))

    def _api(self, path: str) -> dict:
        token = os.getenv("SUPABASE_PERSONAL_ACCESS_TOKEN", "")
        url = f"{self.API_BASE}{path}"
        req = urllib.request.Request(
            url, headers={"Authorization": f"Bearer {token}",
                          "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode())

    def fetch(self) -> SourceReport:
        now = datetime.now(timezone.utc)
        report = SourceReport(source=self.name, fetched_at=now)
        if not self.configured:
            report.error = "missing SUPABASE_PERSONAL_ACCESS_TOKEN or SUPABASE_PROJECT_REF"
            return report

        ref = os.getenv("SUPABASE_PROJECT_REF", "")
        try:
            data = self._api(f"/v1/projects/{ref}/advisors/security")
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError) as e:
            report.error = f"Supabase API error: {e}"
            return report
        except Exception as e:
            report.error = f"unexpected: {e}"
            return report

        # Response shape: {"lints": [{"name", "level", "title", ...}]}
        lints = (data or {}).get("lints") or data.get("results") or []
        if not isinstance(lints, list):
            report.error = f"unexpected response shape: {type(lints).__name__}"
            return report

        bucket = {"ERROR": [], "WARN": [], "INFO": []}
        for lint in lints:
            level = (lint.get("level") or "INFO").upper()
            if level in bucket:
                bucket[level].append(lint)

        # One summary metric per severity tier
        report.metrics.append(MetricSample(
            name="advisor_errors",
            value=len(bucket["ERROR"]),
            severity="critical" if bucket["ERROR"] else "info",
            note=(f"{len(bucket['ERROR'])} CRITICAL advisor(s) — "
                  + ", ".join(l.get("name", "?") for l in bucket["ERROR"][:3])
                  + ("…" if len(bucket["ERROR"]) > 3 else ""))
                 if bucket["ERROR"] else "0 CRITICAL advisors ✓",
        ))
        report.metrics.append(MetricSample(
            name="advisor_warnings",
            value=len(bucket["WARN"]),
            severity="warn" if len(bucket["WARN"]) > 10 else "info",
            note=f"{len(bucket['WARN'])} WARN advisors (post-PH cleanup target)",
        ))
        report.metrics.append(MetricSample(
            name="advisor_info",
            value=len(bucket["INFO"]),
            severity="info",
            note=f"{len(bucket['INFO'])} INFO suggestion(s)",
        ))

        # Per-CRITICAL row so they show up individually in the brief
        for lint in bucket["ERROR"]:
            report.metrics.append(MetricSample(
                name=f"advisor_{lint.get('name', 'unknown')}",
                value=1,
                severity="critical",
                note=f"{lint.get('title', '?')} — {lint.get('description', '')[:120]}",
                raw=lint,
            ))

        return report
