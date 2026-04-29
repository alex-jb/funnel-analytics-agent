"""7-day baseline tracking for anomaly detection.

Storage:
    ~/.funnel-analytics-agent/baseline.jsonl
        {"ts": "2026-04-29T15:00:00Z", "source": "vercel",
         "name": "deployments_24h", "value": 8}

Lookup:
    For metric (source, name), median of all samples in the last
    BASELINE_WINDOW_DAYS (default 7) days.

Anomaly:
    delta_pct = (current - baseline) / baseline * 100
    If baseline > 0 and delta_pct < -50%, severity is promoted to "warn"
    (unless already at "alert"/"critical").

Bootstrapping:
    No samples → no baseline → metric passes through unchanged. After 24h
    of deployment the file has data; after 7 days the baseline is solid.

Override path via BASELINE_LOG_PATH env (used by tests). Best-effort I/O —
read/write failures are silently swallowed; baseline is a nice-to-have, not
load-bearing.
"""
from __future__ import annotations
import json
import os
import pathlib
import statistics
from datetime import datetime, timezone, timedelta
from typing import Iterable

from .sources.base import MetricSample, SourceReport


BASELINE_WINDOW_DAYS = 7
ANOMALY_DROP_PCT = -50.0  # delta_pct below this triggers severity promotion


def _log_path() -> pathlib.Path:
    override = os.getenv("BASELINE_LOG_PATH")
    if override:
        return pathlib.Path(override)
    return pathlib.Path.home() / ".funnel-analytics-agent" / "baseline.jsonl"


def _load_samples() -> list[dict]:
    """Return all rows from the baseline log. Returns [] on any read error."""
    path = _log_path()
    if not path.exists():
        return []
    try:
        out = []
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
        return out
    except Exception:
        return []


def _baseline_for(samples: list[dict], source: str, name: str,
                  *, now: datetime | None = None) -> float | None:
    """Median of values for (source, name) within the last 7 days. None if
    fewer than 3 samples — too noisy to call a baseline."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=BASELINE_WINDOW_DAYS)
    values: list[float] = []
    for row in samples:
        if row.get("source") != source or row.get("name") != name:
            continue
        try:
            ts = datetime.fromisoformat(row["ts"].replace("Z", "+00:00"))
        except Exception:
            continue
        if ts < cutoff:
            continue
        try:
            values.append(float(row["value"]))
        except Exception:
            continue
    if len(values) < 3:
        return None
    return statistics.median(values)


def enrich_with_baseline(reports: Iterable[SourceReport],
                         *, now: datetime | None = None) -> None:
    """In-place: populate MetricSample.baseline + delta_pct, and promote
    severity to 'warn' on >50% drops vs baseline.

    Numeric metrics only. Baseline must be > 0 for delta to be computed
    (avoids division-by-zero on bootstrap).
    """
    now = now or datetime.now(timezone.utc)
    samples = _load_samples()
    if not samples:
        return  # bootstrap mode — nothing to compare against

    for r in reports:
        for m in r.metrics:
            try:
                current = float(m.value)
            except (TypeError, ValueError):
                continue
            base = _baseline_for(samples, r.source, m.name, now=now)
            if base is None or base == 0:
                continue
            delta = (current - base) / base * 100.0
            m.baseline = base
            m.delta_pct = delta
            # Promote severity on big drops, only if not already higher
            if delta < ANOMALY_DROP_PCT and m.severity == "info":
                m.severity = "warn"
                drop = abs(delta)
                m.note = (m.note or "") + (
                    f" ⚠ {drop:.0f}% below 7-day median ({base:.0f})")


def record_samples(reports: Iterable[SourceReport],
                   *, now: datetime | None = None) -> None:
    """Append the current run's metrics to the baseline log. Best-effort —
    a hook firing every 7min during PH would write ~200 rows/day, which is
    fine; rotation is a v0.4 problem.
    """
    now = now or datetime.now(timezone.utc)
    try:
        path = _log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            for r in reports:
                for m in r.metrics:
                    try:
                        value = float(m.value)
                    except (TypeError, ValueError):
                        continue
                    f.write(json.dumps({
                        "ts": now.isoformat(),
                        "source": r.source,
                        "name": m.name,
                        "value": value,
                    }) + "\n")
    except Exception:
        pass
