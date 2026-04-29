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


# ─── rotation ──────────────────────────────────────────────────────

def test_rotate_skips_when_under_threshold(tmp_path, monkeypatch):
    """Don't rotate if the file is small. Verify the live file is unchanged."""
    from funnel_analytics_agent.baseline import _rotate_if_needed
    log = tmp_path / "baseline.jsonl"
    monkeypatch.setenv("BASELINE_LOG_PATH", str(log))
    log.write_text(json.dumps({
        "ts": datetime.now(timezone.utc).isoformat(),
        "source": "v", "name": "x", "value": 1,
    }) + "\n")
    before = log.read_text()
    _rotate_if_needed(log)
    assert log.read_text() == before
    # No archive file created
    assert list(tmp_path.glob("baseline-*.jsonl.gz")) == []


def test_rotate_archives_old_samples(tmp_path, monkeypatch):
    """Force rotation by patching the threshold; verify old rows go to .gz
    and recent rows stay in the live file."""
    from funnel_analytics_agent import baseline as bl
    log = tmp_path / "baseline.jsonl"
    monkeypatch.setenv("BASELINE_LOG_PATH", str(log))
    monkeypatch.setattr(bl, "ROTATE_THRESHOLD_BYTES", 1)  # force rotate

    now = datetime.now(timezone.utc)
    old_ts = (now - timedelta(days=30)).isoformat()
    new_ts = (now - timedelta(days=2)).isoformat()
    log.write_text("\n".join([
        json.dumps({"ts": old_ts, "source": "v", "name": "x", "value": 1}),
        json.dumps({"ts": old_ts, "source": "v", "name": "x", "value": 2}),
        json.dumps({"ts": new_ts, "source": "v", "name": "x", "value": 99}),
    ]) + "\n")

    bl._rotate_if_needed(log, now=now)

    # Live file: only the 2-day-old row remains (within 14-day keep window)
    live = log.read_text().strip().splitlines()
    assert len(live) == 1
    assert json.loads(live[0])["value"] == 99

    # Archive file: 2 old rows
    archives = list(tmp_path.glob("baseline-*.jsonl.gz"))
    assert len(archives) == 1
    import gzip as _gz
    with _gz.open(archives[0], "rb") as f:
        archived = f.read().decode().strip().splitlines()
    assert len(archived) == 2
    assert all(json.loads(r)["value"] in (1, 2) for r in archived)


def test_rotate_appends_to_existing_archive(tmp_path, monkeypatch):
    """If an archive for the same month already exists, append to it."""
    from funnel_analytics_agent import baseline as bl
    log = tmp_path / "baseline.jsonl"
    monkeypatch.setenv("BASELINE_LOG_PATH", str(log))
    monkeypatch.setattr(bl, "ROTATE_THRESHOLD_BYTES", 1)

    now = datetime.now(timezone.utc)
    old_ts = (now - timedelta(days=30)).isoformat()
    archive_path = tmp_path / f"baseline-{datetime.fromisoformat(old_ts).strftime('%Y-%m')}.jsonl.gz"
    import gzip as _gz
    with _gz.open(archive_path, "wb") as f:
        f.write(json.dumps({"ts": old_ts, "source": "v", "name": "x",
                              "value": 999}).encode() + b"\n")

    log.write_text(json.dumps({
        "ts": old_ts, "source": "v", "name": "x", "value": 1,
    }) + "\n")
    bl._rotate_if_needed(log, now=now)

    with _gz.open(archive_path, "rb") as f:
        archived = f.read().decode().strip().splitlines()
    # Pre-existing 999 + newly archived 1
    assert len(archived) == 2
    values = sorted(json.loads(r)["value"] for r in archived)
    assert values == [1, 999]


def test_rotate_corrupt_lines_kept_in_live(tmp_path, monkeypatch):
    """Unparseable lines stay in the live file (don't get silently dropped)."""
    from funnel_analytics_agent import baseline as bl
    log = tmp_path / "baseline.jsonl"
    monkeypatch.setenv("BASELINE_LOG_PATH", str(log))
    monkeypatch.setattr(bl, "ROTATE_THRESHOLD_BYTES", 1)

    now = datetime.now(timezone.utc)
    old_ts = (now - timedelta(days=30)).isoformat()
    log.write_text(
        json.dumps({"ts": old_ts, "source": "v", "name": "x", "value": 1}) + "\n"
        + "this line is corrupt\n"
        + json.dumps({"ts": (now - timedelta(days=2)).isoformat(),
                       "source": "v", "name": "x", "value": 99}) + "\n"
    )
    bl._rotate_if_needed(log, now=now)
    live = log.read_text().splitlines()
    # Corrupt line + recent row both in live file
    assert "this line is corrupt" in live
    assert any('"value": 99' in r for r in live)


def test_record_triggers_rotation(tmp_path, monkeypatch):
    """Integration: record_samples should call rotation before appending."""
    from funnel_analytics_agent import baseline as bl
    log = tmp_path / "baseline.jsonl"
    monkeypatch.setenv("BASELINE_LOG_PATH", str(log))
    monkeypatch.setattr(bl, "ROTATE_THRESHOLD_BYTES", 1)

    now = datetime.now(timezone.utc)
    old_ts = (now - timedelta(days=30)).isoformat()
    log.write_text(json.dumps({
        "ts": old_ts, "source": "v", "name": "old_metric", "value": 100,
    }) + "\n")

    metrics = [MetricSample(name="new_metric", value=42, severity="info")]
    record_samples([_report("v", metrics)], now=now)

    # Live file should now have just the new metric (old rotated out)
    live = log.read_text().strip().splitlines()
    names = [json.loads(r).get("name") for r in live]
    assert "new_metric" in names
    assert "old_metric" not in names
    # Old metric in archive
    archives = list(tmp_path.glob("baseline-*.jsonl.gz"))
    assert len(archives) == 1
