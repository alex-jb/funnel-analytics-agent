"""Smoke tests for the brief re-export shim.

Full coverage lives in solo-founder-os.
"""
from __future__ import annotations
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from funnel_analytics_agent.brief import compose_brief, has_critical
from funnel_analytics_agent.sources.base import MetricSample, SourceReport


def _report(metrics, error=None):
    return SourceReport(source="v",
                         fetched_at=datetime.now(timezone.utc),
                         metrics=metrics, error=error)


def test_compose_brief_works():
    m = MetricSample(name="x", value=1)
    text = compose_brief([_report([m])], summary="all good")
    assert "🧠 Summary" in text
    assert "all good" in text
    assert "📊 Metrics by source" in text


def test_has_critical():
    crit = MetricSample(name="x", value=1, severity="critical")
    info = MetricSample(name="y", value=2, severity="info")
    assert has_critical([_report([crit])])
    assert not has_critical([_report([info])])
