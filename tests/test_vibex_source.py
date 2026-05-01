"""Tests for VibexSource — pulls business metrics from VibeX Supabase.

Mirrors the v0.2 source test pattern: graceful-degradation paths +
mocked happy paths. No real API calls made.
"""
from __future__ import annotations
import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest  # noqa: F401  (kept for parity with other test modules)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from funnel_analytics_agent.sources.vibex import VibexSource


def _fake_urlopen(payload):
    """Build a context-manager-compatible mock for urllib.request.urlopen."""
    fake = MagicMock()
    fake.read.return_value = json.dumps(payload).encode()
    fake.__enter__ = lambda s: s
    fake.__exit__ = lambda *a: None
    return fake


def test_vibex_unconfigured_no_token(monkeypatch):
    monkeypatch.delenv("SUPABASE_PERSONAL_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("VIBEX_PROJECT_REF", raising=False)
    monkeypatch.delenv("SUPABASE_PROJECT_REF", raising=False)
    r = VibexSource().fetch()
    assert r.error is not None
    assert r.metrics == []


def test_vibex_falls_back_to_shared_supabase_ref(monkeypatch):
    """If only SUPABASE_PROJECT_REF is set (no VIBEX_PROJECT_REF), the
    source uses it — covers the common 'one Supabase project' case."""
    monkeypatch.setenv("SUPABASE_PERSONAL_ACCESS_TOKEN", "tok")
    monkeypatch.delenv("VIBEX_PROJECT_REF", raising=False)
    monkeypatch.setenv("SUPABASE_PROJECT_REF", "yjqmquesxwlsmqowoahl")
    src = VibexSource()
    assert src.configured
    assert src._project_ref() == "yjqmquesxwlsmqowoahl"


def test_vibex_specific_ref_wins(monkeypatch):
    monkeypatch.setenv("SUPABASE_PERSONAL_ACCESS_TOKEN", "tok")
    monkeypatch.setenv("VIBEX_PROJECT_REF", "vibex_ref")
    monkeypatch.setenv("SUPABASE_PROJECT_REF", "other_ref")
    assert VibexSource()._project_ref() == "vibex_ref"


def test_vibex_renders_all_metrics(monkeypatch):
    monkeypatch.setenv("SUPABASE_PERSONAL_ACCESS_TOKEN", "tok")
    monkeypatch.setenv("VIBEX_PROJECT_REF", "abc")
    fake = _fake_urlopen([{
        "new_creators_24h": 14,
        "new_projects_24h": 8,
        "total_projects": 132,
        "total_creators": 87,
        "total_plays": 1247,
        "total_upvotes": 320,
        "total_views": 4501,
        "elite_projects": 3,
        "myth_projects": 0,
    }])
    with patch("urllib.request.urlopen", return_value=fake):
        r = VibexSource().fetch()
    assert r.error is None
    by_name = {m.name: m for m in r.metrics}
    # 24h flow
    assert by_name["vibex_new_creators_24h"].value == 14
    assert by_name["vibex_new_creators_24h"].severity == "info"
    assert by_name["vibex_new_projects_24h"].value == 8
    # gauges
    assert by_name["vibex_total_projects"].value == 132
    assert by_name["vibex_total_plays"].value == 1247
    assert by_name["vibex_total_upvotes"].value == 320
    assert by_name["vibex_total_views"].value == 4501
    assert by_name["vibex_elite_stage_count"].value == 3
    # No myth → no alert metric
    assert "vibex_myth_count" not in by_name


def test_vibex_zero_signups_warns(monkeypatch):
    """0 signups in 24h is a possible-regression signal — promote to warn."""
    monkeypatch.setenv("SUPABASE_PERSONAL_ACCESS_TOKEN", "tok")
    monkeypatch.setenv("VIBEX_PROJECT_REF", "abc")
    fake = _fake_urlopen([{
        "new_creators_24h": 0, "new_projects_24h": 0,
        "total_projects": 100, "total_creators": 50,
        "total_plays": 0, "total_upvotes": 0, "total_views": 0,
        "elite_projects": 0, "myth_projects": 0,
    }])
    with patch("urllib.request.urlopen", return_value=fake):
        r = VibexSource().fetch()
    creators = [m for m in r.metrics if m.name == "vibex_new_creators_24h"][0]
    assert creators.severity == "warn"
    assert "auth flow" in creators.note.lower() or "rls" in creators.note.lower()


def test_vibex_myth_promotes_to_alert(monkeypatch):
    """First Myth-stage project should fire an alert metric so the brief
    surfaces it loudly. Once-per-project special event."""
    monkeypatch.setenv("SUPABASE_PERSONAL_ACCESS_TOKEN", "tok")
    monkeypatch.setenv("VIBEX_PROJECT_REF", "abc")
    fake = _fake_urlopen([{
        "new_creators_24h": 5, "new_projects_24h": 2,
        "total_projects": 200, "total_creators": 100,
        "total_plays": 50_000, "total_upvotes": 5000, "total_views": 100_000,
        "elite_projects": 7, "myth_projects": 1,
    }])
    with patch("urllib.request.urlopen", return_value=fake):
        r = VibexSource().fetch()
    by_name = {m.name: m for m in r.metrics}
    assert by_name["vibex_myth_count"].severity == "alert"
    assert by_name["vibex_myth_count"].value == 1


def test_vibex_handles_dict_response_shape(monkeypatch):
    """Some Supabase API revisions return {'result': [...]} — exercise that
    path so we don't break on schema drift."""
    monkeypatch.setenv("SUPABASE_PERSONAL_ACCESS_TOKEN", "tok")
    monkeypatch.setenv("VIBEX_PROJECT_REF", "abc")
    fake = _fake_urlopen({"result": [{
        "new_creators_24h": 1, "new_projects_24h": 1,
        "total_projects": 1, "total_creators": 1,
        "total_plays": 1, "total_upvotes": 1, "total_views": 1,
        "elite_projects": 0, "myth_projects": 0,
    }]})
    with patch("urllib.request.urlopen", return_value=fake):
        r = VibexSource().fetch()
    assert r.error is None
    assert any(m.name == "vibex_new_creators_24h" for m in r.metrics)


def test_vibex_empty_response_returns_error(monkeypatch):
    monkeypatch.setenv("SUPABASE_PERSONAL_ACCESS_TOKEN", "tok")
    monkeypatch.setenv("VIBEX_PROJECT_REF", "abc")
    fake = _fake_urlopen([])
    with patch("urllib.request.urlopen", return_value=fake):
        r = VibexSource().fetch()
    assert r.error is not None
    assert "no rows" in r.error.lower()


def test_vibex_api_failure(monkeypatch):
    monkeypatch.setenv("SUPABASE_PERSONAL_ACCESS_TOKEN", "tok")
    monkeypatch.setenv("VIBEX_PROJECT_REF", "abc")
    with patch("urllib.request.urlopen", side_effect=Exception("net")):
        r = VibexSource().fetch()
    assert r.error is not None
    assert "unexpected" in r.error.lower() or "supabase api error" in r.error.lower()
