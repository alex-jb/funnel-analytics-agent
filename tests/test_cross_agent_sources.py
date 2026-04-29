"""Tests for the v0.7 cross-agent sources: BuildQualitySource + AgentSpendSource.

These sources read OTHER agents' usage logs as input. Tests use
monkeypatched home dir to point at tmp logs, never touch the real ones.
"""
from __future__ import annotations
import json
import os
import pathlib
import sys
from datetime import datetime, timezone, timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from funnel_analytics_agent.sources.buildquality import BuildQualitySource
from funnel_analytics_agent.sources.agent_spend import AgentSpendSource


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _old_iso() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()


# ─── BuildQualitySource ─────────────────────────────────────

def test_bqa_no_log_returns_info_metric(tmp_path, monkeypatch):
    monkeypatch.setenv("BUILD_AGENT_USAGE_LOG", str(tmp_path / "absent.jsonl"))
    r = BuildQualitySource().fetch()
    assert r.error is None
    names = [m.name for m in r.metrics]
    assert "bqa_log_present" in names


def test_bqa_counts_pass_and_block(tmp_path, monkeypatch):
    log = tmp_path / "u.jsonl"
    log.write_text("\n".join([
        json.dumps({"ts": _now_iso(), "model": "claude-haiku-4-5",
                    "verdict": "PASS", "input_tokens": 10, "output_tokens": 5}),
        json.dumps({"ts": _now_iso(), "model": "claude-haiku-4-5",
                    "verdict": "PASS", "input_tokens": 10, "output_tokens": 5}),
        json.dumps({"ts": _now_iso(), "model": "claude-haiku-4-5",
                    "verdict": "BLOCK", "input_tokens": 10, "output_tokens": 5}),
    ]))
    monkeypatch.setenv("BUILD_AGENT_USAGE_LOG", str(log))
    r = BuildQualitySource().fetch()
    by = {m.name: m for m in r.metrics}
    assert by["bqa_pass_count_24h"].value == 2
    assert by["bqa_block_count_24h"].value == 1
    assert by["bqa_block_rate_pct"].value == round(100/3, 1)
    # 33% block rate → alert
    assert by["bqa_block_rate_pct"].severity == "alert"


def test_bqa_excludes_old_rows(tmp_path, monkeypatch):
    log = tmp_path / "u.jsonl"
    log.write_text("\n".join([
        json.dumps({"ts": _old_iso(), "model": "x",
                    "verdict": "BLOCK", "input_tokens": 1, "output_tokens": 1}),
        json.dumps({"ts": _now_iso(), "model": "x",
                    "verdict": "PASS", "input_tokens": 1, "output_tokens": 1}),
    ]))
    monkeypatch.setenv("BUILD_AGENT_USAGE_LOG", str(log))
    r = BuildQualitySource().fetch()
    by = {m.name: m for m in r.metrics}
    assert by["bqa_pass_count_24h"].value == 1
    assert by["bqa_block_count_24h"].value == 0


def test_bqa_block_rate_severity_thresholds(tmp_path, monkeypatch):
    """Below 15% → info, 15-30% → warn, > 30% → alert."""
    # 1 block out of 10 = 10% → info
    rows = [json.dumps({"ts": _now_iso(), "model": "x",
                         "verdict": "PASS", "input_tokens": 1, "output_tokens": 1})
            for _ in range(9)]
    rows.append(json.dumps({"ts": _now_iso(), "model": "x",
                              "verdict": "BLOCK",
                              "input_tokens": 1, "output_tokens": 1}))
    log = tmp_path / "u.jsonl"
    log.write_text("\n".join(rows))
    monkeypatch.setenv("BUILD_AGENT_USAGE_LOG", str(log))
    r = BuildQualitySource().fetch()
    by = {m.name: m for m in r.metrics}
    assert by["bqa_block_rate_pct"].severity == "info"


def test_bqa_skips_corrupt_lines(tmp_path, monkeypatch):
    log = tmp_path / "u.jsonl"
    log.write_text("\n".join([
        "this is not json",
        json.dumps({"ts": _now_iso(), "model": "x",
                    "verdict": "PASS", "input_tokens": 1, "output_tokens": 1}),
        "{",
    ]))
    monkeypatch.setenv("BUILD_AGENT_USAGE_LOG", str(log))
    r = BuildQualitySource().fetch()
    by = {m.name: m for m in r.metrics}
    assert by["bqa_pass_count_24h"].value == 1


# ─── AgentSpendSource ───────────────────────────────────────

def _seed_agent_log(home: pathlib.Path, agent_dir: str, rows: list[dict]) -> None:
    d = home / agent_dir
    d.mkdir(parents=True, exist_ok=True)
    log = d / "usage.jsonl"
    log.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def test_agent_spend_no_logs_returns_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    r = AgentSpendSource().fetch()
    by = {m.name: m for m in r.metrics}
    assert by["anthropic_spend_24h_usd"].value == 0.0
    assert by["anthropic_calls_24h"].value == 0


def test_agent_spend_aggregates_across_logs(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    _seed_agent_log(tmp_path, ".build-quality-agent", [
        {"ts": _now_iso(), "model": "claude-haiku-4-5",
         "input_tokens": 1000, "output_tokens": 200},
    ])
    _seed_agent_log(tmp_path, ".funnel-analytics-agent", [
        {"ts": _now_iso(), "model": "claude-haiku-4-5",
         "input_tokens": 500, "output_tokens": 100},
    ])
    r = AgentSpendSource().fetch()
    by = {m.name: m for m in r.metrics}
    # haiku: ($1/MTok in + $5/MTok out)
    # bqa: 1000*1/M + 200*5/M = 0.001 + 0.001 = 0.002
    # funnel: 500*1/M + 100*5/M = 0.0005 + 0.0005 = 0.001
    # total: 0.003
    assert by["anthropic_spend_24h_usd"].value == 0.003
    assert by["anthropic_calls_24h"].value == 2
    # Per-agent breakdown
    assert "spend_build_quality_agent_24h_usd" in by
    assert "spend_funnel_analytics_agent_24h_usd" in by


def test_agent_spend_severity_thresholds(tmp_path, monkeypatch):
    """$1+ → warn, $5+ → alert."""
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    # $1.50 of haiku usage = 1.5M tokens with right ratio
    # $1 = 1M output tokens × $5/MTok = 200k output tokens. Let's just use 250k out.
    _seed_agent_log(tmp_path, ".build-quality-agent", [
        {"ts": _now_iso(), "model": "claude-haiku-4-5",
         "input_tokens": 0, "output_tokens": 300_000},  # $1.50 in haiku output
    ])
    r = AgentSpendSource().fetch()
    by = {m.name: m for m in r.metrics}
    assert by["anthropic_spend_24h_usd"].severity == "warn"


def test_agent_spend_excludes_old(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    _seed_agent_log(tmp_path, ".build-quality-agent", [
        {"ts": _old_iso(), "model": "claude-haiku-4-5",
         "input_tokens": 9_999_999, "output_tokens": 9_999_999},  # huge but old
        {"ts": _now_iso(), "model": "claude-haiku-4-5",
         "input_tokens": 100, "output_tokens": 50},
    ])
    r = AgentSpendSource().fetch()
    by = {m.name: m for m in r.metrics}
    assert by["anthropic_calls_24h"].value == 1


def test_agent_spend_one_bad_log_doesnt_kill_source(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    # Good log
    _seed_agent_log(tmp_path, ".build-quality-agent", [
        {"ts": _now_iso(), "model": "claude-haiku-4-5",
         "input_tokens": 100, "output_tokens": 50},
    ])
    # Corrupt log (just garbage)
    bad = tmp_path / ".funnel-analytics-agent"
    bad.mkdir()
    (bad / "usage.jsonl").write_text("garbage\n{not json}\n")

    r = AgentSpendSource().fetch()
    # Source still produces metrics (good log gets counted; bad lines skipped silently)
    by = {m.name: m for m in r.metrics}
    assert by["anthropic_calls_24h"].value >= 1
    assert r.error is None
