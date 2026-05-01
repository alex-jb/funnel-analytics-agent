"""Tests for v0.2 sources: SupabaseAdvisorSource, OpenPanelSource, HyperDXSource.

Same pattern as test_sources.py — graceful degradation paths + mocked happy
paths. Real API calls are never made.
"""
from __future__ import annotations
import json
import os
import sys
from unittest.mock import patch, MagicMock


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from funnel_analytics_agent.sources.supabase import SupabaseAdvisorSource
from funnel_analytics_agent.sources.openpanel import OpenPanelSource
from funnel_analytics_agent.sources.hyperdx import HyperDXSource


def _fake_urlopen(payload: dict | None = None, *, http_error: int | None = None,
                  exc: Exception | None = None):
    """Build a context-manager-compatible mock for urllib.request.urlopen."""
    if exc is not None:
        return MagicMock(side_effect=exc)
    if http_error is not None:
        import urllib.error
        return MagicMock(side_effect=urllib.error.HTTPError(
            url="x", code=http_error, msg="x", hdrs=None, fp=None))
    fake = MagicMock()
    fake.read.return_value = json.dumps(payload or {}).encode()
    fake.__enter__ = lambda s: s
    fake.__exit__ = lambda *a: None
    return fake


# ─── SupabaseAdvisorSource ────────────────────────────────────────

def test_supabase_missing_creds(monkeypatch):
    monkeypatch.delenv("SUPABASE_PERSONAL_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("SUPABASE_PROJECT_REF", raising=False)
    r = SupabaseAdvisorSource().fetch()
    assert r.error is not None
    assert r.metrics == []


def test_supabase_zero_advisors(monkeypatch):
    monkeypatch.setenv("SUPABASE_PERSONAL_ACCESS_TOKEN", "x")
    monkeypatch.setenv("SUPABASE_PROJECT_REF", "abc")
    fake = _fake_urlopen({"lints": []})
    with patch("urllib.request.urlopen", return_value=fake):
        r = SupabaseAdvisorSource().fetch()
    assert r.error is None
    errors = [m for m in r.metrics if m.name == "advisor_errors"][0]
    assert errors.value == 0
    assert errors.severity == "info"


def test_supabase_critical_advisor_renders(monkeypatch):
    monkeypatch.setenv("SUPABASE_PERSONAL_ACCESS_TOKEN", "x")
    monkeypatch.setenv("SUPABASE_PROJECT_REF", "abc")
    fake = _fake_urlopen({
        "lints": [
            {"name": "auth_users_exposed", "level": "ERROR",
             "title": "User data exposed",
             "description": "A view is exposing emails"},
        ]
    })
    with patch("urllib.request.urlopen", return_value=fake):
        r = SupabaseAdvisorSource().fetch()
    summary = [m for m in r.metrics if m.name == "advisor_errors"][0]
    assert summary.value == 1
    assert summary.severity == "critical"
    # Per-CRITICAL row
    detail = [m for m in r.metrics
              if m.name == "advisor_auth_users_exposed"][0]
    assert detail.severity == "critical"
    assert "exposed" in detail.note.lower()


def test_supabase_api_error(monkeypatch):
    monkeypatch.setenv("SUPABASE_PERSONAL_ACCESS_TOKEN", "x")
    monkeypatch.setenv("SUPABASE_PROJECT_REF", "abc")
    with patch("urllib.request.urlopen",
               side_effect=Exception("network")):
        r = SupabaseAdvisorSource().fetch()
    assert r.error is not None


# ─── OpenPanelSource ──────────────────────────────────────────────

def test_openpanel_missing_creds(monkeypatch):
    monkeypatch.delenv("OPENPANEL_CLIENT_ID", raising=False)
    monkeypatch.delenv("OPENPANEL_CLIENT_SECRET", raising=False)
    r = OpenPanelSource().fetch()
    assert r.error is not None


def test_openpanel_event_count_renders(monkeypatch):
    monkeypatch.setenv("OPENPANEL_CLIENT_ID", "id")
    monkeypatch.setenv("OPENPANEL_CLIENT_SECRET", "secret")
    monkeypatch.setenv("OPENPANEL_TRACKED_EVENTS", "signup_completed")
    fake = _fake_urlopen({"count": 42})
    with patch("urllib.request.urlopen", return_value=fake):
        r = OpenPanelSource().fetch()
    assert r.error is None
    sig = [m for m in r.metrics if m.name == "events_signup_completed_24h"][0]
    assert sig.value == 42
    assert sig.severity == "info"


def test_openpanel_zero_events_warns(monkeypatch):
    monkeypatch.setenv("OPENPANEL_CLIENT_ID", "id")
    monkeypatch.setenv("OPENPANEL_CLIENT_SECRET", "secret")
    monkeypatch.setenv("OPENPANEL_TRACKED_EVENTS", "signup_completed")
    fake = _fake_urlopen({"count": 0})
    with patch("urllib.request.urlopen", return_value=fake):
        r = OpenPanelSource().fetch()
    sig = [m for m in r.metrics if m.name == "events_signup_completed_24h"][0]
    assert sig.severity == "warn"
    assert "regression" in sig.note.lower()


def test_openpanel_all_calls_fail(monkeypatch):
    monkeypatch.setenv("OPENPANEL_CLIENT_ID", "id")
    monkeypatch.setenv("OPENPANEL_CLIENT_SECRET", "secret")
    monkeypatch.setenv("OPENPANEL_TRACKED_EVENTS", "x,y")
    with patch("urllib.request.urlopen",
               side_effect=Exception("network")):
        r = OpenPanelSource().fetch()
    assert r.error is not None


# ─── HyperDXSource ────────────────────────────────────────────────

def test_hyperdx_missing_creds(monkeypatch):
    monkeypatch.delenv("HYPERDX_API_KEY", raising=False)
    r = HyperDXSource().fetch()
    assert r.error is not None


def test_hyperdx_low_errors_info(monkeypatch):
    monkeypatch.setenv("HYPERDX_API_KEY", "x")
    fake = _fake_urlopen({"total": 3})
    with patch("urllib.request.urlopen", return_value=fake):
        r = HyperDXSource().fetch()
    e = [m for m in r.metrics if m.name.startswith("errors_last_")][0]
    assert e.value == 3
    assert e.severity == "info"


def test_hyperdx_high_errors_alert(monkeypatch):
    monkeypatch.setenv("HYPERDX_API_KEY", "x")
    fake = _fake_urlopen({"total": 75})
    with patch("urllib.request.urlopen", return_value=fake):
        r = HyperDXSource().fetch()
    e = [m for m in r.metrics if m.name.startswith("errors_last_")][0]
    assert e.severity == "alert"


def test_hyperdx_401_helpful_message(monkeypatch):
    monkeypatch.setenv("HYPERDX_API_KEY", "ingestion-key-by-mistake")
    fake = _fake_urlopen(http_error=401)
    with patch("urllib.request.urlopen", new=fake):
        r = HyperDXSource().fetch()
    assert r.error is not None
    assert "QUERY key" in r.error or "401" in r.error
