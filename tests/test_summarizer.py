"""Tests for summarizer.py — narrative summary via shared AnthropicClient."""
from __future__ import annotations
import os
import sys
from datetime import datetime, timezone


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from funnel_analytics_agent.sources.base import MetricSample, SourceReport
from funnel_analytics_agent.summarizer import summarize, _build_input
from solo_founder_os.anthropic_client import AnthropicClient
from solo_founder_os.testing import fake_anthropic, fake_anthropic_raises


def _report(source: str, metrics=None, error=None):
    return SourceReport(
        source=source,
        fetched_at=datetime.now(timezone.utc),
        metrics=metrics or [],
        error=error,
    )


def _client_with_fake(monkeypatch, fake_sdk_client) -> AnthropicClient:
    """Helper: build an AnthropicClient and pre-load it with a mocked SDK client."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    c = AnthropicClient(usage_log_path=None)
    c._client = fake_sdk_client  # bypass lazy import
    return c


def test_build_input_includes_baseline_delta():
    m = MetricSample(name="signups", value=30, baseline=100, delta_pct=-70.0,
                     severity="warn", note="dropped")
    text = _build_input([_report("openpanel", [m])])
    assert "[openpanel]" in text
    assert "signups=30" in text
    assert "baseline=100" in text
    assert "-70.0%" in text


def test_build_input_unavailable_source():
    text = _build_input([_report("vercel", error="API down")])
    assert "[vercel] UNAVAILABLE: API down" in text


def test_summarize_empty_when_no_reports():
    """Empty input → empty output (no LLM call needed)."""
    assert summarize([]) == ""


def test_summarize_empty_when_client_unconfigured(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    m = MetricSample(name="x", value=1)
    assert summarize([_report("v", [m])]) == ""


def test_summarize_returns_text_on_success(monkeypatch):
    m = MetricSample(name="x", value=1)
    fake = fake_anthropic("Signups dropped 70% overnight. No action needed.")
    client = _client_with_fake(monkeypatch, fake)
    out = summarize([_report("v", [m])], client=client)
    assert "Signups dropped" in out


def test_summarize_swallows_llm_errors(monkeypatch):
    m = MetricSample(name="x", value=1)
    fake = fake_anthropic_raises(Exception("rate limit"))
    client = _client_with_fake(monkeypatch, fake)
    assert summarize([_report("v", [m])], client=client) == ""
