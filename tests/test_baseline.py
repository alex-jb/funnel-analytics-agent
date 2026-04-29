"""Tests for baseline.py — 7-day median lookup, severity promotion, recording."""
from __future__ import annotations
import json
import os
import sys
from datetime import datetime, timezone, timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from funnel_analytics_agent.sources.base import MetricSample, SourceReport
from funnel_analytics_agent.baseline import (
    enrich_with_baseline,
    record_samples,
    _baseline_for,
    _load_samples,
)


@pytest.fixture(autouse=True)
def _redirect_log(tmp_path, monkeypatch):
    """Send the baseline log to a tmp file so tests never pollute the real
    ~/.funnel-analytics-agent/baseline.jsonl on the dev machine."""
    monkeypatch.setenv("BASELINE_LOG_PATH", str(tmp_path / "baseline.jsonl"))


def _seed(path, source: str, name: str, values: list[tuple[datetime, float]]):
    """Write seed rows to baseline.jsonl."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        for ts, v in values:
            f.write(json.dumps({
                "ts": ts.isoformat(), "source": source, "name": name,
                "value": v,
            }) + "\n")


def _report(source: str, metrics: list[MetricSample]) -> SourceReport:
    return SourceReport(source=source,
                        fetched_at=datetime.now(timezone.utc),
                        metrics=metrics)


# ─── lookup ────────────────────────────────────────────────────────

def test_baseline_returns_none_with_no_history():
    samples = []
    assert _baseline_for(samples, "vercel", "deployments_24h") is None


def test_baseline_returns_none_with_too_few_samples(tmp_path):
    samples = [{"ts": datetime.now(timezone.utc).isoformat(),
                "source": "v", "name": "m", "value": 5}] * 2
    assert _baseline_for(samples, "v", "m") is None


def test_baseline_median_over_recent_samples(tmp_path):
    now = datetime.now(timezone.utc)
    samples = [
        {"ts": (now - timedelta(days=1)).isoformat(),
         "source": "v", "name": "m", "value": 10},
        {"ts": (now - timedelta(days=2)).isoformat(),
         "source": "v", "name": "m", "value": 20},
        {"ts": (now - timedelta(days=3)).isoformat(),
         "source": "v", "name": "m", "value": 30},
    ]
    assert _baseline_for(samples, "v", "m", now=now) == 20.0


def test_baseline_excludes_samples_older_than_7_days(tmp_path):
    now = datetime.now(timezone.utc)
    samples = [
        {"ts": (now - timedelta(days=1)).isoformat(),
         "source": "v", "name": "m", "value": 10},
        {"ts": (now - timedelta(days=2)).isoformat(),
         "source": "v", "name": "m", "value": 12},
        {"ts": (now - timedelta(days=3)).isoformat(),
         "source": "v", "name": "m", "value": 14},
        # This one is too old — should be excluded
        {"ts": (now - timedelta(days=15)).isoformat(),
         "source": "v", "name": "m", "value": 9999},
    ]
    assert _baseline_for(samples, "v", "m", now=now) == 12.0


# ─── enrich_with_baseline ──────────────────────────────────────────

def test_enrich_does_nothing_in_bootstrap_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("BASELINE_LOG_PATH", str(tmp_path / "missing.jsonl"))
    m = MetricSample(name="x", value=10, severity="info")
    r = _report("v", [m])
    enrich_with_baseline([r])
    assert m.delta_pct is None
    assert m.severity == "info"


def test_enrich_populates_delta_pct(tmp_path, monkeypatch):
    log = tmp_path / "baseline.jsonl"
    monkeypatch.setenv("BASELINE_LOG_PATH", str(log))
    now = datetime.now(timezone.utc)
    _seed(log, "v", "x", [
        (now - timedelta(days=1), 100),
        (now - timedelta(days=2), 100),
        (now - timedelta(days=3), 100),
    ])
    m = MetricSample(name="x", value=150, severity="info")
    r = _report("v", [m])
    enrich_with_baseline([r])
    assert m.baseline == 100.0
    assert m.delta_pct == 50.0


def test_enrich_promotes_severity_on_big_drop(tmp_path, monkeypatch):
    log = tmp_path / "baseline.jsonl"
    monkeypatch.setenv("BASELINE_LOG_PATH", str(log))
    now = datetime.now(timezone.utc)
    # 7-day median = 100
    _seed(log, "openpanel", "events_signup_completed_24h", [
        (now - timedelta(days=1), 100),
        (now - timedelta(days=2), 100),
        (now - timedelta(days=3), 100),
    ])
    # Today: only 30 — that's a 70% drop
    m = MetricSample(name="events_signup_completed_24h", value=30,
                     severity="info", note="signup count")
    r = _report("openpanel", [m])
    enrich_with_baseline([r])
    assert m.severity == "warn"
    assert "below 7-day median" in m.note
    assert m.delta_pct < -50


def test_enrich_does_not_promote_critical(tmp_path, monkeypatch):
    log = tmp_path / "baseline.jsonl"
    monkeypatch.setenv("BASELINE_LOG_PATH", str(log))
    now = datetime.now(timezone.utc)
    _seed(log, "v", "x", [
        (now - timedelta(days=1), 100),
        (now - timedelta(days=2), 100),
        (now - timedelta(days=3), 100),
    ])
    m = MetricSample(name="x", value=30, severity="critical")
    r = _report("v", [m])
    enrich_with_baseline([r])
    # Critical should stay critical, not be 'promoted' to warn
    assert m.severity == "critical"


def test_enrich_skips_zero_baseline(tmp_path, monkeypatch):
    log = tmp_path / "baseline.jsonl"
    monkeypatch.setenv("BASELINE_LOG_PATH", str(log))
    now = datetime.now(timezone.utc)
    _seed(log, "v", "x", [
        (now - timedelta(days=1), 0),
        (now - timedelta(days=2), 0),
        (now - timedelta(days=3), 0),
    ])
    m = MetricSample(name="x", value=10, severity="info")
    enrich_with_baseline([_report("v", [m])])
    # Cannot compute % vs zero — leave it alone
    assert m.delta_pct is None


# ─── record_samples ────────────────────────────────────────────────

def test_record_appends_one_row_per_metric(tmp_path, monkeypatch):
    log = tmp_path / "baseline.jsonl"
    monkeypatch.setenv("BASELINE_LOG_PATH", str(log))
    metrics = [
        MetricSample(name="a", value=1, severity="info"),
        MetricSample(name="b", value=2, severity="info"),
    ]
    record_samples([_report("v", metrics)])
    rows = log.read_text().strip().splitlines()
    assert len(rows) == 2
    assert all("ts" in json.loads(r) for r in rows)


def test_record_skips_non_numeric_values(tmp_path, monkeypatch):
    log = tmp_path / "baseline.jsonl"
    monkeypatch.setenv("BASELINE_LOG_PATH", str(log))
    metrics = [
        MetricSample(name="a", value="not_a_number", severity="info"),
        MetricSample(name="b", value=42, severity="info"),
    ]
    record_samples([_report("v", metrics)])
    rows = log.read_text().strip().splitlines()
    assert len(rows) == 1
    assert json.loads(rows[0])["name"] == "b"
