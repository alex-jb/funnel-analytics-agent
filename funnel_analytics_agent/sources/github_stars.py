"""GitHub stars source — track star + fork growth across a list of repos.

For the Solo Founder OS stack: surfaces which OSS repos are getting
attention day-to-day. Combined with the baseline machinery, a 5-star
day on a repo that normally gets 0 surfaces as warn (anomaly worth
checking — usually means a tweet or a dev.to article landed).

Auth: GITHUB_TOKEN (optional). Public repos work without it (60 req/h
unauth limit), but with a token you get 5000 req/h — comfortable for
20+ repos polled hourly.

Configure: GITHUB_STARS_REPOS, comma-separated `owner/repo` list. Default
is the 8 repos in Alex's agent stack.
"""
from __future__ import annotations
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone

from .base import MetricSample, Source, SourceReport


DEFAULT_REPOS = [
    "alex-jb/solo-founder-os",
    "alex-jb/build-quality-agent",
    "alex-jb/customer-discovery-agent",
    "alex-jb/funnel-analytics-agent",
    "alex-jb/vc-outreach-agent",
    "alex-jb/cost-audit-agent",
    "alex-jb/bilingual-content-sync-agent",
    "alex-jb/orallexa-marketing-agent",
    "alex-jb/vibex",
]


class GithubStarsSource(Source):
    """Pulls star + fork counts for a list of repos.

    Each repo emits two MetricSamples:
      - github_stars_<owner>_<repo>:  current star count (gauge)
      - github_forks_<owner>_<repo>:  current fork count (gauge)

    The baseline machinery handles day-over-day delta detection.
    """
    name = "github_stars"
    API_BASE = "https://api.github.com"

    @property
    def configured(self) -> bool:
        # Public repos work without a token, so this source is "configured"
        # whenever GITHUB_STARS_REPOS is non-empty (or when defaults apply).
        return bool(self._repos())

    def _repos(self) -> list[str]:
        env = os.getenv("GITHUB_STARS_REPOS", "").strip()
        if env:
            return [r.strip() for r in env.split(",") if r.strip()]
        return list(DEFAULT_REPOS)

    def _fetch_repo(self, owner_repo: str) -> dict | None:
        url = f"{self.API_BASE}/repos/{owner_repo}"
        headers = {"Accept": "application/vnd.github+json",
                    "User-Agent": "funnel-analytics-agent"}
        token = os.getenv("GITHUB_TOKEN", "")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read().decode())
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError):
            return None
        except Exception:
            return None

    def fetch(self) -> SourceReport:
        now = datetime.now(timezone.utc)
        report = SourceReport(source=self.name, fetched_at=now)
        repos = self._repos()
        if not repos:
            report.error = "no GITHUB_STARS_REPOS configured"
            return report

        successes = 0
        for owner_repo in repos:
            data = self._fetch_repo(owner_repo)
            if not data:
                continue
            successes += 1
            slug = owner_repo.replace("/", "_").replace("-", "_")
            stars = int(data.get("stargazers_count") or 0)
            forks = int(data.get("forks_count") or 0)
            report.metrics.append(MetricSample(
                name=f"github_stars_{slug}",
                value=stars,
                severity="info",
                note=f"⭐ {owner_repo}: {stars}",
                raw={"owner_repo": owner_repo,
                     "url": data.get("html_url"),
                     "open_issues": data.get("open_issues_count") or 0},
            ))
            report.metrics.append(MetricSample(
                name=f"github_forks_{slug}",
                value=forks,
                severity="info",
                note=f"🍴 {owner_repo}: {forks}",
            ))

        if successes == 0:
            report.error = (f"all {len(repos)} repo lookups failed — "
                            "GitHub API rate limited? Set GITHUB_TOKEN.")
            return report

        # Total stars across the stack — useful single-number for daily brief
        total_stars = sum(m.value for m in report.metrics
                          if m.name.startswith("github_stars_"))
        report.metrics.append(MetricSample(
            name="github_stars_total",
            value=total_stars,
            severity="info",
            note=f"⭐ {total_stars} stars across {successes} tracked repo(s)",
        ))
        return report
