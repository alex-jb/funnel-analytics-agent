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

import pytest

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
