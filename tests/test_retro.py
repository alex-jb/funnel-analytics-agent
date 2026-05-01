"""Tests for the PH+24h retrospective generator."""
from __future__ import annotations
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from funnel_analytics_agent.retro import render_retro
from funnel_analytics_agent.sources.base import MetricSample, SourceReport


def _vibex_report(*, new_creators=14, new_projects=8, total_projects=132,
                   total_plays=1247, elite=3, myth=1):
    return SourceReport(
        source="vibex",
        fetched_at=datetime.now(timezone.utc),
        metrics=[
            MetricSample(name="vibex_new_creators_24h", value=new_creators,
                         severity="info", note=f"{new_creators} new creators"),
            MetricSample(name="vibex_new_projects_24h", value=new_projects,
                         severity="info", note=f"{new_projects} new projects"),
            MetricSample(name="vibex_total_projects", value=total_projects,
                         severity="info", note=""),
            MetricSample(name="vibex_total_plays", value=total_plays,
                         severity="info", note=""),
            MetricSample(name="vibex_total_upvotes", value=320,
                         severity="info", note=""),
            MetricSample(name="vibex_elite_stage_count", value=elite,
                         severity="info", note=""),
            MetricSample(name="vibex_myth_count", value=myth,
                         severity="alert" if myth else "info", note=""),
        ],
    )


def _ph_report(*, votes=347, comments=15, rank=4, alert_comment=False):
    metrics = [
        MetricSample(name="ph_votes", value=votes, severity="info",
                      note=f"PH upvotes: {votes}"),
        MetricSample(name="ph_comments", value=comments, severity="info",
                      note=f"PH comments: {comments}"),
        MetricSample(name="ph_daily_rank", value=rank, severity="info",
                      note=f"PH daily rank: #{rank}"),
    ]
    if alert_comment:
        metrics.append(MetricSample(
            name="ph_comment_c1", value=1, severity="alert",
            note="@user: signup is broken — possible issue, reply fast"))
    return SourceReport(
        source="producthunt",
        fetched_at=datetime.now(timezone.utc),
        metrics=metrics,
    )


def test_renders_full_retro_with_all_sections():
    reports = [_vibex_report(), _ph_report()]
    out = render_retro(reports)
    assert "# Launch retrospective" in out
    assert "## VibeX" in out
    assert "## Product Hunt" in out
    # vibex numbers shown (with thousands separator)
    assert "**14**" in out  # new creators
    assert "1,247" in out   # cumulative plays
    # PH numbers shown
    assert "**347**" in out
    assert "**#4**" in out


def test_myth_count_surfaced_when_present():
    reports = [_vibex_report(myth=2)]
    out = render_retro(reports)
    assert "✨" in out
    assert "**At Myth:** 2" in out


def test_myth_count_skipped_when_zero():
    reports = [_vibex_report(myth=0)]
    out = render_retro(reports)
    assert "**At Myth:**" not in out


def test_alert_comments_surface_in_retro():
    reports = [_ph_report(alert_comment=True)]
    out = render_retro(reports)
    assert "needing fast-reply" in out
    assert "signup is broken" in out


def test_outside_top_30_rendered():
    reports = [_ph_report(rank=0)]
    out = render_retro(reports)
    assert "outside top 30" in out


def test_failed_sources_listed_at_bottom():
    failed = SourceReport(
        source="vercel",
        fetched_at=datetime.now(timezone.utc),
        error="missing VERCEL_TOKEN",
    )
    reports = [_vibex_report(), failed]
    out = render_retro(reports)
    assert "Sources unavailable" in out
    assert "vercel" in out
    assert "missing VERCEL_TOKEN" in out


def test_retro_includes_milestones_when_state_exists(tmp_path, monkeypatch):
    state = tmp_path / "milestones.json"
    state.write_text(json.dumps({
        "vibex_total_upvotes": 547,
        "vibex_total_plays": 12_300,
    }))
    monkeypatch.setattr("funnel_analytics_agent.retro.MILESTONES_STATE_PATH",
                        state)
    out = render_retro([_vibex_report()])
    assert "Milestones crossed" in out
    assert "547" in out
    assert "12,300" in out


def test_retro_renders_when_state_missing(tmp_path, monkeypatch):
    """No milestones.json → still renders cleanly with 'no milestones recorded'."""
    state = tmp_path / "missing.json"
    monkeypatch.setattr("funnel_analytics_agent.retro.MILESTONES_STATE_PATH",
                        state)
    out = render_retro([])
    assert "no milestones recorded" in out


def test_unconfigured_sources_show_unavailable():
    """When vibex/ph reports are missing entirely, sections still render."""
    out = render_retro([])
    assert "## VibeX" in out
    assert "_unavailable" in out


def test_since_hours_param_appears_in_header():
    out = render_retro([], since_hours=48)
    assert "last 48h" in out
