"""Smoke tests for the funnel-analytics-agent baseline shim.

Full coverage of baseline logic (rotation, median, promotion, etc.) lives
in solo-founder-os's test suite. This file just verifies the funnel-
specific wrapper:
- log path resolution honors BASELINE_LOG_PATH env
- public functions delegate to solo_founder_os and behave end-to-end
"""
from __future__ import annotations
import json
import os
import sys
from datetime import datetime, timezone, timedelta


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from funnel_analytics_agent.baseline import (
    enrich_with_baseline,
    record_samples,
    _log_path,
    DEFAULT_LOG_PATH,
)
from funnel_analytics_agent.sources.base import MetricSample, SourceReport


def _report(metrics):
    return SourceReport(source="v",
                         fetched_at=datetime.now(timezone.utc),
                         metrics=metrics)


def test_default_log_path_is_funnel_specific(monkeypatch):
    monkeypatch.delenv("BASELINE_LOG_PATH", raising=False)
    assert _log_path() == DEFAULT_LOG_PATH
    assert ".funnel-analytics-agent" in str(DEFAULT_LOG_PATH)
    assert str(DEFAULT_LOG_PATH).endswith("baseline.jsonl")


def test_env_override_wins(monkeypatch, tmp_path):
    custom = tmp_path / "elsewhere.jsonl"
    monkeypatch.setenv("BASELINE_LOG_PATH", str(custom))
    assert _log_path() == custom


def test_record_then_enrich_roundtrip(tmp_path, monkeypatch):
    """End-to-end: record three values, run enrich on a low value,
    verify delta_pct is computed correctly."""
    log = tmp_path / "baseline.jsonl"
    monkeypatch.setenv("BASELINE_LOG_PATH", str(log))

    # Seed with 3 days of samples at value=100
    now = datetime.now(timezone.utc)
    for offset in (1, 2, 3):
        ts = now - timedelta(days=offset)
        with log.open("a") as f:
            f.write(json.dumps({
                "ts": ts.isoformat(), "source": "v", "name": "x", "value": 100,
            }) + "\n")

    m = MetricSample(name="x", value=20, severity="info")
    enrich_with_baseline([_report([m])])
    assert m.baseline == 100.0
    assert m.delta_pct == -80.0
    # Severity promoted because <-50%
    assert m.severity == "warn"


def test_record_then_enrich_via_public_api(tmp_path, monkeypatch):
    """record_samples + enrich_with_baseline should work together."""
    log = tmp_path / "baseline.jsonl"
    monkeypatch.setenv("BASELINE_LOG_PATH", str(log))

    # Three runs of value=50
    for _ in range(3):
        record_samples([_report([MetricSample(name="x", value=50)])])

    # Now enrich a metric — needs samples in the past, but record_samples
    # uses now. With three "now" samples baseline_for needs ≥3 samples,
    # so even with all-now timestamps we get a baseline of 50.
    m = MetricSample(name="x", value=10, severity="info")
    enrich_with_baseline([_report([m])])
    assert m.baseline == 50.0
    assert m.delta_pct == -80.0
