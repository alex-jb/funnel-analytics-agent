"""Source ABC + dataclasses — re-exported from solo-founder-os.

These names live here as a backward-compatibility shim. New code should
import from solo_founder_os directly:

    from solo_founder_os import Source, SourceReport, MetricSample

This module exists so existing test imports
`from funnel_analytics_agent.sources.base import ...` keep working.
v0.7+ may deprecate the shim.
"""
from __future__ import annotations
from solo_founder_os.source import (
    Source,
    SourceReport,
    MetricSample,
)

__all__ = ["Source", "SourceReport", "MetricSample"]
