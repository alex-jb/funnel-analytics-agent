"""Baseline tracker — funnel-analytics-agent's wrapper over solo-founder-os.

Why this wrapper exists: solo_founder_os.baseline is generic over
log_path. This module bakes in the funnel-specific default path
(`~/.funnel-analytics-agent/baseline.jsonl`) and honors the legacy
`BASELINE_LOG_PATH` env override that older deploys may have set.

All real logic lives in solo_founder_os.baseline. We just delegate.
"""
from __future__ import annotations
import os
import pathlib
from datetime import datetime
from typing import Iterable

from solo_founder_os.baseline import (
    enrich_with_baseline as _enrich,
    record_samples as _record,
    _baseline_for,
    _rotate_if_needed,
    BASELINE_WINDOW_DAYS,
    ANOMALY_DROP_PCT,
    ROTATE_THRESHOLD_BYTES,
    ROTATE_KEEP_DAYS,
)
from solo_founder_os.source import SourceReport


DEFAULT_LOG_PATH = (pathlib.Path.home()
                    / ".funnel-analytics-agent" / "baseline.jsonl")


def _log_path() -> pathlib.Path:
    """Honor BASELINE_LOG_PATH env (used by tests + custom deploys),
    else fall back to the funnel-specific default."""
    override = os.getenv("BASELINE_LOG_PATH")
    if override:
        return pathlib.Path(override)
    return DEFAULT_LOG_PATH


def enrich_with_baseline(reports: Iterable[SourceReport],
                         *, now: datetime | None = None) -> None:
    _enrich(reports, log_path=_log_path(), now=now)


def record_samples(reports: Iterable[SourceReport],
                   *, now: datetime | None = None) -> None:
    _record(reports, log_path=_log_path(), now=now)


__all__ = [
    "enrich_with_baseline", "record_samples",
    "BASELINE_WINDOW_DAYS", "ANOMALY_DROP_PCT",
    "ROTATE_THRESHOLD_BYTES", "ROTATE_KEEP_DAYS",
    "_baseline_for", "_rotate_if_needed", "_log_path", "DEFAULT_LOG_PATH",
]
