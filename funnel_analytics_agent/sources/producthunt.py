"""Product Hunt source — track your launch's rank, votes, comments live.

Uses Product Hunt's GraphQL API v2. Requires PH_DEV_TOKEN env var; bearer
token from a PH developer app at api.producthunt.com/v2/oauth/applications.

Falls back to public-data scrape only if no token (limited info, no live
rank). For PH launch day, get a token — the live rank metric is critical.

Configure PH_LAUNCH_SLUG (e.g. "vibexforge") to track a specific launch.
"""
from __future__ import annotations
import os
import json
import urllib.request
import urllib.error
from datetime import datetime, timezone
from .base import MetricSample, Source, SourceReport


class ProductHuntSource(Source):
    name = "producthunt"
    API_URL = "https://api.producthunt.com/v2/api/graphql"

    @property
    def configured(self) -> bool:
        return bool(os.getenv("PH_DEV_TOKEN")) and bool(os.getenv("PH_LAUNCH_SLUG"))

    def _query(self, slug: str) -> dict:
        token = os.getenv("PH_DEV_TOKEN", "")
        query = """
        query LaunchByPostSlug($slug: String!) {
          post(slug: $slug) {
            id
            name
            tagline
            url
            votesCount
            commentsCount
            featuredAt
            createdAt
          }
        }
        """
        payload = json.dumps({"query": query, "variables": {"slug": slug}}).encode()
        req = urllib.request.Request(
            self.API_URL,
            data=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode())

    def fetch(self) -> SourceReport:
        now = datetime.now(timezone.utc)
        report = SourceReport(source=self.name, fetched_at=now)

        if not self.configured:
            report.error = "missing PH_DEV_TOKEN or PH_LAUNCH_SLUG"
            return report

        slug = os.getenv("PH_LAUNCH_SLUG", "")
        try:
            data = self._query(slug)
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError) as e:
            report.error = f"PH API error: {e}"
            return report
        except Exception as e:
            report.error = f"unexpected: {e}"
            return report

        post = (data.get("data") or {}).get("post")
        if not post:
            report.error = f"PH post not found for slug={slug}"
            return report

        votes = post.get("votesCount", 0)
        comments = post.get("commentsCount", 0)

        report.metrics.append(MetricSample(
            name="ph_votes",
            value=votes,
            severity="info",
            note=f"PH upvotes: {votes}",
            raw={"url": post.get("url"), "name": post.get("name")},
        ))
        report.metrics.append(MetricSample(
            name="ph_comments",
            value=comments,
            severity="info",
            note=f"PH comments: {comments} — reply within 15 min for algo boost",
        ))
        # During launch day, fewer than 50 upvotes by 6h in is concerning
        if post.get("featuredAt") and votes < 50:
            launched_at = datetime.fromisoformat(post["featuredAt"].replace("Z", "+00:00"))
            hours_since = (now - launched_at).total_seconds() / 3600
            if 1.0 <= hours_since <= 6.0:
                report.metrics.append(MetricSample(
                    name="ph_pace_alert",
                    value=votes,
                    severity="warn",
                    note=f"only {votes} votes after {hours_since:.1f}h — momentum check",
                ))

        return report
