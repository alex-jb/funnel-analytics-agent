"""VibeX (vibexforge.com) business-metrics source.

Reads core launch-board metrics directly from the VibeX Supabase project:
  - new creator signups (last 24h)
  - new project submissions (last 24h)
  - total projects + cumulative plays + cumulative upvotes (gauge)
  - elite stage count (Breakout / Legend / Myth — rare graduations)

Auth: SUPABASE_PERSONAL_ACCESS_TOKEN (same one the advisor source uses).
Project: VIBEX_PROJECT_REF (defaults to SUPABASE_PROJECT_REF for the
common case where Alex has one Supabase project).

Why a dedicated source: OpenPanel + HyperDX cover *generic* events.
This source pulls the actual core-business numbers — "are people signing
up", "are people submitting projects", "is the evolution ladder
moving" — straight from the source-of-truth tables. Zero Claude API
calls; pure SQL through Supabase's Management API query endpoint.

Cost: $0. Each fetch is one SQL round-trip returning a single aggregate
row. Total monthly cost at 6 fetches/hour × 24h × 30d ≈ free tier.
"""
from __future__ import annotations
import os
import json
import urllib.request
import urllib.error
from datetime import datetime, timezone

from ..milestones import check_crossing
from .base import MetricSample, Source, SourceReport


VIBEX_AGGREGATE_SQL = """
SELECT
  (SELECT count(*) FROM creators
     WHERE joined_at >= current_date - interval '1 day')        AS new_creators_24h,
  (SELECT count(*) FROM projects
     WHERE created_at >= now() - interval '24 hours')           AS new_projects_24h,
  (SELECT count(*) FROM projects)                                AS total_projects,
  (SELECT count(*) FROM creators)                                AS total_creators,
  (SELECT coalesce(sum(plays), 0) FROM projects)                 AS total_plays,
  (SELECT coalesce(sum(upvotes), 0) FROM projects)               AS total_upvotes,
  (SELECT coalesce(sum(views), 0) FROM projects)                 AS total_views,
  (SELECT count(*) FROM projects
     WHERE evolution_stage IN ('Breakout','Legend','Myth'))      AS elite_projects,
  (SELECT count(*) FROM projects
     WHERE evolution_stage = 'Myth')                             AS myth_projects
""".strip()


class VibexSource(Source):
    """Pulls core VibeX launch-board metrics. Each metric goes into the
    daily brief and is baseline-tracked, so a 'new_creators_24h' jump
    over baseline auto-promotes severity in alert mode.
    """
    name = "vibex"
    API_BASE = "https://api.supabase.com"

    @property
    def configured(self) -> bool:
        if not os.getenv("SUPABASE_PERSONAL_ACCESS_TOKEN"):
            return False
        # VIBEX_PROJECT_REF wins; fall back to the shared SUPABASE_PROJECT_REF
        return bool(os.getenv("VIBEX_PROJECT_REF")
                     or os.getenv("SUPABASE_PROJECT_REF"))

    def _project_ref(self) -> str:
        return (os.getenv("VIBEX_PROJECT_REF")
                  or os.getenv("SUPABASE_PROJECT_REF") or "")

    def _query(self, sql: str) -> list[dict]:
        token = os.getenv("SUPABASE_PERSONAL_ACCESS_TOKEN", "")
        ref = self._project_ref()
        url = f"{self.API_BASE}/v1/projects/{ref}/database/query"
        body = json.dumps({"query": sql}).encode()
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Authorization": f"Bearer {token}",
                      "Content-Type": "application/json",
                      "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
        # Management API returns either a list of rows or {"result": [...]}
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("result", "rows", "data"):
                if key in data and isinstance(data[key], list):
                    return data[key]
        return []

    def fetch(self) -> SourceReport:
        now = datetime.now(timezone.utc)
        report = SourceReport(source=self.name, fetched_at=now)
        if not self.configured:
            report.error = ("missing SUPABASE_PERSONAL_ACCESS_TOKEN or "
                            "VIBEX_PROJECT_REF / SUPABASE_PROJECT_REF")
            return report

        try:
            rows = self._query(VIBEX_AGGREGATE_SQL)
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError) as e:
            report.error = f"Supabase API error: {e}"
            return report
        except Exception as e:
            report.error = f"unexpected: {e}"
            return report

        if not rows:
            report.error = "Supabase returned no rows for vibex aggregate"
            return report

        row = rows[0]
        # 24h flow metrics (the ones that move daily)
        new_creators = int(row.get("new_creators_24h") or 0)
        new_projects = int(row.get("new_projects_24h") or 0)
        # Cumulative gauges (baseline machinery surfaces day-over-day delta)
        total_projects = int(row.get("total_projects") or 0)
        total_creators = int(row.get("total_creators") or 0)
        total_plays = int(row.get("total_plays") or 0)
        total_upvotes = int(row.get("total_upvotes") or 0)
        total_views = int(row.get("total_views") or 0)
        elite = int(row.get("elite_projects") or 0)
        myth = int(row.get("myth_projects") or 0)

        # Severity rules:
        #   new_creators_24h == 0  → warn (signup pipeline broken?)
        #   new_creators_24h > 50  → info (upside)
        report.metrics.append(MetricSample(
            name="vibex_new_creators_24h",
            value=new_creators,
            severity="warn" if new_creators == 0 else "info",
            note=("0 signups in 24h — auth flow / RLS regression?"
                  if new_creators == 0
                  else f"{new_creators} new creator signups"),
        ))
        report.metrics.append(MetricSample(
            name="vibex_new_projects_24h",
            value=new_projects,
            severity="info",
            note=f"{new_projects} new project submissions",
        ))
        report.metrics.append(MetricSample(
            name="vibex_total_projects",
            value=total_projects,
            severity="info",
            note=f"{total_projects} total projects · {total_creators} creators",
        ))
        report.metrics.append(MetricSample(
            name="vibex_total_plays",
            value=total_plays,
            severity="info",
            note=f"{total_plays} cumulative plays",
        ))
        report.metrics.append(MetricSample(
            name="vibex_total_upvotes",
            value=total_upvotes,
            severity="info",
            note=f"{total_upvotes} cumulative upvotes",
        ))
        report.metrics.append(MetricSample(
            name="vibex_total_views",
            value=total_views,
            severity="info",
            note=f"{total_views} cumulative project views",
        ))
        # Elite stages — Breakout/Legend/Myth are rare. Surface as info,
        # promote to alert when first Myth appears (only happens once per
        # exceptional project).
        report.metrics.append(MetricSample(
            name="vibex_elite_stage_count",
            value=elite,
            severity="info",
            note=(f"{elite} project(s) at Breakout/Legend/Myth stage"
                  + (f" · {myth} at Myth ✨" if myth > 0 else "")),
        ))
        if myth > 0:
            report.metrics.append(MetricSample(
                name="vibex_myth_count",
                value=myth,
                severity="alert",  # Promotes the brief when first Myth appears
                note=f"{myth} project(s) at Myth stage — share them!",
            ))

        # ── PH-day milestone crossings → alert + ready-to-send tweet ──
        # Each gauge metric checked against its threshold ladder. State is
        # persisted in ~/.funnel-analytics-agent/milestones.json so the
        # same milestone fires once. The notifier fan-out (ntfy/Telegram/
        # Slack) surfaces these — Alex pastes the tweet, hits send.
        for metric_name, value in [
            ("vibex_total_upvotes", total_upvotes),
            ("vibex_total_plays", total_plays),
            ("vibex_total_creators", total_creators),
            ("vibex_myth_count", myth),
        ]:
            crossing = check_crossing(metric_name, value)
            if crossing is None:
                continue
            threshold, tweet = crossing
            report.metrics.append(MetricSample(
                name=f"milestone_{metric_name}_{threshold}",
                value=threshold,
                severity="alert",
                note=(f"🎉 milestone crossed: {metric_name} = {value} "
                      f"(passed {threshold}). Ready tweet:\n\n{tweet}"),
                raw={"metric": metric_name, "threshold": threshold,
                     "value": value, "tweet": tweet},
            ))

        return report
