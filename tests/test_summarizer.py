"""Tests for summarizer.py — narrative summary via Claude."""
from __future__ import annotations
import os
import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from funnel_analytics_agent.sources.base import MetricSample, SourceReport
from funnel_analytics_agent.summarizer import summarize, _build_input
from funnel_analytics_agent.brief import compose_brief


def _report(source: str, metrics=None, error=None):
    return SourceReport(
        source=source,
        fetched_at=datetime.now(timezone.utc),
        metrics=metrics or [],
        error=error,
    )


def _fake_anthropic(text: str):
    block = MagicMock()
    block.text = text
    block.type = "text"
    resp = MagicMock()
    resp.content = [block]
    client = MagicMock()
    client.messages.create.return_value = resp
    return client


# ─── _build_input ─────────────────────────────────────────────

def test_build_input_includes_baseline_delta():
    m = MetricSample(name="signups", value=30, baseline=100, delta_pct=-70.0,
                     severity="warn", note="signups dropped")
    text = _build_input([_report("openpanel", [m])])
    assert "[openpanel]" in text
    assert "signups=30" in text
    assert "baseline=100" in text
    assert "-70.0%" in text


def test_build_input_marks_unavailable_sources():
    text = _build_input([_report("vercel", error="API down")])
    assert "[vercel] UNAVAILABLE: API down" in text


# ─── summarize ─────────────────────────────────────────────────

def test_summarize_returns_empty_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    m = MetricSample(name="x", value=10, severity="info")
    assert summarize([_report("v", [m])]) == ""


def test_summarize_returns_empty_with_no_reports(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert summarize([]) == ""


def test_summarize_calls_claude_and_returns_text(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    m = MetricSample(name="signups", value=30, baseline=100,
                     delta_pct=-70.0, severity="warn")
    fake = _fake_anthropic("Signups dropped 70% overnight. Investigate the Vercel deploy that errored at 21:32. No action needed elsewhere.")
    with patch("anthropic.Anthropic", return_value=fake):
        result = summarize([_report("openpanel", [m])])
    assert "70%" in result
    assert "Vercel" in result


def test_summarize_swallows_llm_errors(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    m = MetricSample(name="x", value=1, severity="info")
    fake = MagicMock()
    fake.messages.create.side_effect = Exception("rate limited")
    with patch("anthropic.Anthropic", return_value=fake):
        result = summarize([_report("v", [m])])
    assert result == ""


# ─── brief integration ────────────────────────────────────────

def test_brief_renders_summary_section_when_provided():
    m = MetricSample(name="x", value=1, severity="info")
    text = compose_brief([_report("v", [m])],
                         summary="All systems normal. No action needed.")
    assert "🧠 Summary" in text
    assert "All systems normal" in text
    # Summary appears before the metrics section
    assert text.index("🧠 Summary") < text.index("📊 Metrics by source")


def test_brief_omits_summary_section_when_none():
    m = MetricSample(name="x", value=1, severity="info")
    text = compose_brief([_report("v", [m])], summary=None)
    assert "🧠 Summary" not in text


def test_brief_omits_summary_section_when_empty_string():
    m = MetricSample(name="x", value=1, severity="info")
    text = compose_brief([_report("v", [m])], summary="")
    assert "🧠 Summary" not in text
