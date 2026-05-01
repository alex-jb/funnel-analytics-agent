"""Tests for source classes — graceful degradation paths only.

Real API calls are mocked. The point is:
- missing creds → SourceReport with error, never raises
- API failure → SourceReport with error, never raises
- valid response → produces metrics with correct severity
"""
from __future__ import annotations
import json
import os
import sys
from unittest.mock import patch, MagicMock


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from funnel_analytics_agent.sources.vercel import VercelSource
from funnel_analytics_agent.sources.producthunt import ProductHuntSource


# ─── VercelSource ───────────────────────────────────────────────────

def test_vercel_missing_creds_returns_error_report(monkeypatch):
    monkeypatch.delenv("VERCEL_TOKEN", raising=False)
    monkeypatch.delenv("VERCEL_PROJECT_ID", raising=False)
    r = VercelSource().fetch()
    assert r.error is not None
    assert "VERCEL_TOKEN" in r.error or "VERCEL_PROJECT_ID" in r.error
    assert r.metrics == []


def test_vercel_api_error_caught(monkeypatch):
    monkeypatch.setenv("VERCEL_TOKEN", "x")
    monkeypatch.setenv("VERCEL_PROJECT_ID", "p")
    with patch("urllib.request.urlopen", side_effect=Exception("network")):
        r = VercelSource().fetch()
    assert r.error is not None
    assert "network" in r.error or "unexpected" in r.error


def test_vercel_ready_state_renders_info(monkeypatch):
    monkeypatch.setenv("VERCEL_TOKEN", "x")
    monkeypatch.setenv("VERCEL_PROJECT_ID", "p")
    fake_resp = MagicMock()
    fake_resp.read.return_value = json.dumps({
        "deployments": [
            {"state": "READY", "name": "vibex", "url": "x.vercel.app",
             "createdAt": 0, "uid": "u1"},
        ]
    }).encode()
    fake_resp.__enter__ = lambda s: s
    fake_resp.__exit__ = lambda *a: None
    with patch("urllib.request.urlopen", return_value=fake_resp):
        r = VercelSource().fetch()
    assert r.error is None
    state_metric = [m for m in r.metrics if m.name == "latest_deployment_state"][0]
    assert state_metric.severity == "info"
    assert state_metric.value == 1


def test_vercel_error_state_renders_critical(monkeypatch):
    monkeypatch.setenv("VERCEL_TOKEN", "x")
    monkeypatch.setenv("VERCEL_PROJECT_ID", "p")
    fake_resp = MagicMock()
    fake_resp.read.return_value = json.dumps({
        "deployments": [
            {"state": "ERROR", "name": "vibex", "url": "x.vercel.app",
             "createdAt": 0, "uid": "u1"},
        ]
    }).encode()
    fake_resp.__enter__ = lambda s: s
    fake_resp.__exit__ = lambda *a: None
    with patch("urllib.request.urlopen", return_value=fake_resp):
        r = VercelSource().fetch()
    state_metric = [m for m in r.metrics if m.name == "latest_deployment_state"][0]
    assert state_metric.severity == "critical"


# ─── ProductHuntSource ─────────────────────────────────────────────

def test_ph_missing_creds_returns_error_report(monkeypatch):
    monkeypatch.delenv("PH_DEV_TOKEN", raising=False)
    monkeypatch.delenv("PH_LAUNCH_SLUG", raising=False)
    r = ProductHuntSource().fetch()
    assert r.error is not None
    assert r.metrics == []


def test_ph_api_error_caught(monkeypatch):
    monkeypatch.setenv("PH_DEV_TOKEN", "x")
    monkeypatch.setenv("PH_LAUNCH_SLUG", "vibexforge")
    with patch("urllib.request.urlopen", side_effect=Exception("network")):
        r = ProductHuntSource().fetch()
    assert r.error is not None


def test_ph_post_not_found(monkeypatch):
    monkeypatch.setenv("PH_DEV_TOKEN", "x")
    monkeypatch.setenv("PH_LAUNCH_SLUG", "missing")
    fake_resp = MagicMock()
    fake_resp.read.return_value = json.dumps({"data": {"post": None}}).encode()
    fake_resp.__enter__ = lambda s: s
    fake_resp.__exit__ = lambda *a: None
    with patch("urllib.request.urlopen", return_value=fake_resp):
        r = ProductHuntSource().fetch()
    assert r.error is not None
    assert "not found" in r.error


def test_ph_votes_render(monkeypatch):
    monkeypatch.setenv("PH_DEV_TOKEN", "x")
    monkeypatch.setenv("PH_LAUNCH_SLUG", "vibexforge")
    fake_resp = MagicMock()
    fake_resp.read.return_value = json.dumps({
        "data": {"post": {
            "id": "1", "name": "VibeXForge", "tagline": "...",
            "url": "https://producthunt.com/posts/vibexforge",
            "votesCount": 200, "commentsCount": 10,
            "featuredAt": None, "createdAt": "2026-05-04T00:01:00Z",
        }}
    }).encode()
    fake_resp.__enter__ = lambda s: s
    fake_resp.__exit__ = lambda *a: None
    with patch("urllib.request.urlopen", return_value=fake_resp):
        r = ProductHuntSource().fetch()
    assert r.error is None
    votes = [m for m in r.metrics if m.name == "ph_votes"][0]
    assert votes.value == 200
    comments = [m for m in r.metrics if m.name == "ph_comments"][0]
    assert comments.value == 10


def _ph_response(*, post_extra=None, posts_edges=None):
    """Build a PH GraphQL response with optional rank list + comments."""
    post = {
        "id": "1", "name": "VibeXForge", "tagline": "...",
        "url": "https://producthunt.com/posts/vibexforge",
        "votesCount": 100, "commentsCount": 4,
        "featuredAt": None, "createdAt": "2026-05-04T00:01:00Z",
        "comments": {"edges": []},
    }
    if post_extra:
        post.update(post_extra)
    fake = MagicMock()
    fake.read.return_value = json.dumps({
        "data": {
            "post": post,
            "posts": {"edges": posts_edges or []},
        }
    }).encode()
    fake.__enter__ = lambda s: s
    fake.__exit__ = lambda *a: None
    return fake


def test_ph_rank_top_3_is_info(monkeypatch):
    monkeypatch.setenv("PH_DEV_TOKEN", "x")
    monkeypatch.setenv("PH_LAUNCH_SLUG", "vibexforge")
    fake = _ph_response(posts_edges=[
        {"node": {"slug": "competitor-a", "votesCount": 300}},
        {"node": {"slug": "competitor-b", "votesCount": 250}},
        {"node": {"slug": "vibexforge", "votesCount": 200}},
    ])
    with patch("urllib.request.urlopen", return_value=fake):
        r = ProductHuntSource().fetch()
    rank = [m for m in r.metrics if m.name == "ph_daily_rank"][0]
    assert rank.value == 3
    assert rank.severity == "info"


def test_ph_rank_outside_top_30_during_launch_is_alert(monkeypatch):
    """Within the 24h launch window, rank=None means we slipped off the
    front page — that's a backer-DM-wave-now signal."""
    from datetime import datetime, timezone
    monkeypatch.setenv("PH_DEV_TOKEN", "x")
    monkeypatch.setenv("PH_LAUNCH_SLUG", "vibexforge")
    # featuredAt 2h ago == still in launch window
    featured = datetime.now(timezone.utc).replace(microsecond=0)
    featured = featured.isoformat().replace("+00:00", "Z")
    fake = _ph_response(
        post_extra={"featuredAt": featured, "votesCount": 80},
        posts_edges=[
            {"node": {"slug": "other", "votesCount": 999}}
        ] * 30,
    )
    with patch("urllib.request.urlopen", return_value=fake):
        r = ProductHuntSource().fetch()
    rank = [m for m in r.metrics if m.name == "ph_daily_rank"][0]
    assert rank.value == 0
    assert rank.severity == "alert"
    assert "backer DM" in rank.note


def test_ph_rank_15_in_launch_window_is_warn(monkeypatch):
    from datetime import datetime, timezone
    monkeypatch.setenv("PH_DEV_TOKEN", "x")
    monkeypatch.setenv("PH_LAUNCH_SLUG", "vibexforge")
    featured = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    edges = [{"node": {"slug": f"other-{i}", "votesCount": 500 - i}}
             for i in range(14)]
    edges.append({"node": {"slug": "vibexforge", "votesCount": 100}})
    fake = _ph_response(
        post_extra={"featuredAt": featured},
        posts_edges=edges,
    )
    with patch("urllib.request.urlopen", return_value=fake):
        r = ProductHuntSource().fetch()
    rank = [m for m in r.metrics if m.name == "ph_daily_rank"][0]
    assert rank.value == 15
    assert rank.severity == "warn"


def test_ph_negative_comment_promotes_to_alert(monkeypatch):
    monkeypatch.setenv("PH_DEV_TOKEN", "x")
    monkeypatch.setenv("PH_LAUNCH_SLUG", "vibexforge")
    fake = _ph_response(post_extra={
        "comments": {"edges": [
            {"node": {
                "id": "c1", "createdAt": "2026-05-04T00:30:00Z",
                "body": "Cool idea but the signup link is broken",
                "user": {"username": "skeptical_user"},
            }},
            {"node": {
                "id": "c2", "createdAt": "2026-05-04T00:35:00Z",
                "body": "Love this 🔨 forging my project right now",
                "user": {"username": "happy_user"},
            }},
        ]}
    })
    with patch("urllib.request.urlopen", return_value=fake):
        r = ProductHuntSource().fetch()
    by_name = {m.name: m for m in r.metrics}
    assert by_name["ph_comment_c1"].severity == "alert"
    assert "skeptical_user" in by_name["ph_comment_c1"].note
    assert by_name["ph_comment_c2"].severity == "info"
    assert "happy_user" in by_name["ph_comment_c2"].note


def test_ph_recent_comments_skipped_when_empty(monkeypatch):
    monkeypatch.setenv("PH_DEV_TOKEN", "x")
    monkeypatch.setenv("PH_LAUNCH_SLUG", "vibexforge")
    fake = _ph_response()  # no comments
    with patch("urllib.request.urlopen", return_value=fake):
        r = ProductHuntSource().fetch()
    assert not [m for m in r.metrics if m.name.startswith("ph_comment_")]
