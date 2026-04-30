"""Tests for MCP server tools.

The `mcp` package is an optional dep — only test the underlying tool
logic by importing the module's tool functions directly. The FastMCP
decorator returns the original callable unchanged (registration is a
side-effect on the FastMCP instance), so we just call them like
regular functions.
"""
from __future__ import annotations
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Skip the whole module if mcp isn't installed (optional dep)
mcp_available = True
try:
    from mcp.server.fastmcp import FastMCP  # noqa: F401
except ImportError:
    mcp_available = False

pytestmark = pytest.mark.skipif(not mcp_available,
                                  reason="mcp optional dep not installed")


@pytest.fixture
def mod():
    """Import mcp_server fresh after confirming `mcp` is available."""
    from funnel_analytics_agent import mcp_server
    return mcp_server


def test_get_brief_renders_markdown(mod, monkeypatch, tmp_path):
    """All 7 sources unconfigured → brief still produces unavailable section."""
    for k in ("VERCEL_TOKEN", "VERCEL_PROJECT_ID", "PH_DEV_TOKEN",
              "PH_LAUNCH_SLUG", "SUPABASE_PERSONAL_ACCESS_TOKEN",
              "SUPABASE_PROJECT_REF", "OPENPANEL_CLIENT_ID",
              "OPENPANEL_CLIENT_SECRET", "HYPERDX_API_KEY",
              "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("BASELINE_LOG_PATH", str(tmp_path / "baseline.jsonl"))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    out = mod.get_brief(include_summary=False)
    assert "Brief —" in out or "Morning Brief" in out
    assert "Sources unavailable" in out


def test_get_alerts_all_clear(mod, monkeypatch, tmp_path):
    for k in ("VERCEL_TOKEN", "PH_DEV_TOKEN", "SUPABASE_PERSONAL_ACCESS_TOKEN",
              "OPENPANEL_CLIENT_ID", "HYPERDX_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("BASELINE_LOG_PATH", str(tmp_path / "baseline.jsonl"))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    out = mod.get_alerts()
    # All sources unavailable → no metrics → no alerts
    assert "All clear" in out


def test_get_source_unknown(mod):
    out = mod.get_source("nonexistent_source")
    assert "Unknown source" in out
    assert "vercel" in out  # available list


def test_get_source_unconfigured(mod, monkeypatch):
    monkeypatch.delenv("VERCEL_TOKEN", raising=False)
    monkeypatch.delenv("VERCEL_PROJECT_ID", raising=False)
    out = mod.get_source("vercel")
    assert "vercel" in out
    assert "unavailable" in out


def test_usage_summary_no_log(mod, monkeypatch, tmp_path):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    out = mod.usage_summary()
    assert "No usage logged" in out


def test_main_skips_when_skip_env_set(mod, monkeypatch):
    monkeypatch.setenv("FUNNEL_AGENT_SKIP", "1")
    # main() should return without calling mcp.run() — verify by mocking it
    with patch.object(mod.mcp, "run") as fake_run:
        mod.main()
    fake_run.assert_not_called()


def test_mcp_instance_is_fastmcp(mod):
    """Sanity: mcp object is a real FastMCP instance with tools registered."""
    from mcp.server.fastmcp import FastMCP
    assert isinstance(mod.mcp, FastMCP)
