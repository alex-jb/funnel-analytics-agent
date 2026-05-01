"""Product Hunt source — track your launch's rank, votes, comments live.

Uses Product Hunt's GraphQL API v2. Requires PH_DEV_TOKEN env var; bearer
token from a PH developer app at api.producthunt.com/v2/oauth/applications.

Falls back to public-data scrape only if no token (limited info, no live
rank). For PH launch day, get a token — the live rank metric is critical.

Configure PH_LAUNCH_SLUG (e.g. "vibexforge") to track a specific launch.

v0.10 additions (PH-day survival kit):
  - ph_daily_rank: your current position in today's PH leaderboard.
    Promotes to alert severity when rank drops below 10 in the first
    12h of launch — that's the signal to push another wave of backer DMs.
  - ph_recent_comments: snapshots the 5 newest comments. Surfaces a
    per-comment alert metric when a comment matches negative-signal
    keywords (broken / doesn't work / why doesn't / can't / 504 / 5xx),
    so you respond in under 15 min while the PH algo still rewards it.
"""
from __future__ import annotations
import os
import json
import re
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from .base import MetricSample, Source, SourceReport


# Triggers per-comment alert. Keep it tight — false-positive alerts at
# 3am ruin the launch night more than missing a slow-burn comment does.
NEGATIVE_COMMENT_PATTERNS = re.compile(
    r"\b(broken|doesn[''']t work|not working|can[''']t|cannot|"
    r"why doesn[''']t|where[''']s the|how do i|missing|404|500|502|503|504|"
    r"5xx|crash(?:ed|ing)?|stuck|spinning|loading forever)\b",
    re.IGNORECASE,
)


class ProductHuntSource(Source):
    name = "producthunt"
    API_URL = "https://api.producthunt.com/v2/api/graphql"

    @property
    def configured(self) -> bool:
        return bool(os.getenv("PH_DEV_TOKEN")) and bool(os.getenv("PH_LAUNCH_SLUG"))

    def _query(self, slug: str, posted_after: datetime) -> dict:
        token = os.getenv("PH_DEV_TOKEN", "")
        # Single round-trip: post details + recent comments + daily top 30.
        # We compute rank locally by scanning the daily-leaderboard edges
        # for our slug — PH GraphQL has no direct "what's my rank" field.
        query = """
        query Launch($slug: String!, $postedAfter: DateTime) {
          post(slug: $slug) {
            id
            name
            tagline
            url
            votesCount
            commentsCount
            featuredAt
            createdAt
            comments(first: 5, order: NEWEST) {
              edges {
                node {
                  id
                  createdAt
                  body
                  user { username name }
                }
              }
            }
          }
          posts(postedAfter: $postedAfter, order: VOTES, first: 30) {
            edges {
              node {
                slug
                votesCount
              }
            }
          }
        }
        """
        variables = {
            "slug": slug,
            "postedAfter": posted_after.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        payload = json.dumps({"query": query, "variables": variables}).encode()
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

    def _compute_rank(self, slug: str, posts_data: dict) -> int | None:
        """Return 1-based rank if slug appears in the daily top-30, else None."""
        edges = (posts_data or {}).get("edges") or []
        for i, edge in enumerate(edges):
            node = (edge or {}).get("node") or {}
            if node.get("slug") == slug:
                return i + 1
        return None

    def fetch(self) -> SourceReport:
        now = datetime.now(timezone.utc)
        report = SourceReport(source=self.name, fetched_at=now)

        if not self.configured:
            report.error = "missing PH_DEV_TOKEN or PH_LAUNCH_SLUG"
            return report

        slug = os.getenv("PH_LAUNCH_SLUG", "")
        # Daily leaderboard window: last 24h. PH "today" floats based on
        # PT midnight, but a 24h window is close enough to identify your
        # rank during launch day. After 24h we'd want featuredAt/-PT-day
        # alignment, but launch-day is the only moment rank really matters.
        posted_after = now - timedelta(hours=24)
        try:
            data = self._query(slug, posted_after)
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

        # ── Rank tracker ──────────────────────────────────────────
        posts_data = (data.get("data") or {}).get("posts") or {}
        rank = self._compute_rank(slug, posts_data)
        # Severity ladder during the first 12h of launch:
        #   rank 1-5   → info  (you're winning)
        #   rank 6-10  → info  (still in top page)
        #   rank 11-15 → warn  (slipping — push another DM wave)
        #   rank 16-30 → alert (off the front page)
        #   not in top 30 / unknown → alert (worst case during PH-day)
        is_launch_window = False
        if post.get("featuredAt"):
            launched_at = datetime.fromisoformat(
                post["featuredAt"].replace("Z", "+00:00"))
            hours_since = (now - launched_at).total_seconds() / 3600
            is_launch_window = 0 <= hours_since <= 24
        if rank is None:
            severity = "alert" if is_launch_window else "info"
            report.metrics.append(MetricSample(
                name="ph_daily_rank",
                value=0,  # 0 == "not in top 30"
                severity=severity,
                note=("not in PH top 30 — push another backer DM wave"
                      if is_launch_window
                      else "outside daily top 30 (off launch window — informational)"),
            ))
        else:
            if rank <= 10:
                severity = "info"
            elif rank <= 15 and is_launch_window:
                severity = "warn"
            elif is_launch_window:
                severity = "alert"
            else:
                severity = "info"
            report.metrics.append(MetricSample(
                name="ph_daily_rank",
                value=rank,
                severity=severity,
                note=f"PH daily rank: #{rank} of top 30",
            ))

        # ── Recent comments ───────────────────────────────────────
        comment_edges = ((post.get("comments") or {}).get("edges") or [])
        for edge in comment_edges:
            node = (edge or {}).get("node") or {}
            body = (node.get("body") or "").strip()
            if not body:
                continue
            user = (node.get("user") or {}).get("username") or "anon"
            is_negative = bool(NEGATIVE_COMMENT_PATTERNS.search(body))
            severity = "alert" if is_negative else "info"
            preview = body[:140].replace("\n", " ")
            report.metrics.append(MetricSample(
                name=f"ph_comment_{node.get('id', 'unknown')}",
                value=1,
                severity=severity,
                note=(f"@{user}: {preview}"
                      + (" — possible issue, reply fast"
                         if is_negative else "")),
                raw=node,
            ))

        # ── Pace alert (existing v0.1 behavior, retained) ─────────
        if is_launch_window and votes < 50:
            hours_since = (now - datetime.fromisoformat(
                post["featuredAt"].replace("Z", "+00:00"))).total_seconds() / 3600
            if 1.0 <= hours_since <= 6.0:
                report.metrics.append(MetricSample(
                    name="ph_pace_alert",
                    value=votes,
                    severity="warn",
                    note=f"only {votes} votes after {hours_since:.1f}h — momentum check",
                ))

        return report
