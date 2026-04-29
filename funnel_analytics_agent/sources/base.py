"""Abstract base class for data sources.

Each source produces a SourceReport — a dict of metric name → MetricSample.
The brief composer aggregates all reports into a daily markdown brief; the
alerter checks each MetricSample against thresholds for anomalies.

Sources are independent: one source failing (e.g. Vercel API down) MUST NOT
prevent other sources from running. Failures surface in the brief as a
"source: unavailable" line, not an exception.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class MetricSample:
    """A single metric reading at one point in time."""
    name: str                       # e.g. "signup_count_24h"
    value: float | int              # current value
    baseline: float | int | None = None     # 7-day avg or similar
    delta_pct: float | None = None  # (value - baseline) / baseline * 100
    severity: str = "info"          # "info", "warn", "alert", "critical"
    note: str = ""                  # one-line human explanation
    raw: dict = field(default_factory=dict)  # source-specific extras


@dataclass
class SourceReport:
    """Output from one Source.fetch() call."""
    source: str                     # e.g. "vercel"
    fetched_at: datetime
    metrics: list[MetricSample] = field(default_factory=list)
    error: Optional[str] = None     # set when source fetch failed; metrics empty


class Source:
    """Subclass per data provider. Implement fetch() to return a SourceReport."""

    name: str = "base"

    def fetch(self) -> SourceReport:
        raise NotImplementedError

    @property
    def configured(self) -> bool:
        """Whether this source has the env vars / credentials it needs."""
        return True
