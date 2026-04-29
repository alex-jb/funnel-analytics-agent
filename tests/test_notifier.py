"""Tests for notifier.py — ntfy, Telegram, Slack adapters + fan_out."""
from __future__ import annotations
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from funnel_analytics_agent.notifier import (
    NtfyNotifier,
    TelegramNotifier,
    SlackNotifier,
    fan_out,
    ALL_NOTIFIERS,
    MAX_MESSAGE_CHARS,
)


def _ok():
    """Mock urlopen returning a 200-ish response."""
    fake = MagicMock()
    fake.status = 200
    fake.__enter__ = lambda s: s
    fake.__exit__ = lambda *a: None
    return fake


def _http_error():
    fake = MagicMock()
    fake.status = 500
    fake.__enter__ = lambda s: s
    fake.__exit__ = lambda *a: None
    return fake


# ─── NtfyNotifier ────────────────────────────────────────────

def test_ntfy_not_configured_without_topic(monkeypatch):
    monkeypatch.delenv("NTFY_TOPIC", raising=False)
    n = NtfyNotifier()
    assert n.configured is False
    assert n.send("hi") is False


def test_ntfy_send_success(monkeypatch):
    monkeypatch.setenv("NTFY_TOPIC", "my-topic")
    with patch("urllib.request.urlopen", return_value=_ok()) as urlopen:
        ok = NtfyNotifier().send("hello", title="t", priority="urgent")
    assert ok is True
    # Verify URL + headers in the request
    req = urlopen.call_args[0][0]
    assert "ntfy.sh/my-topic" in req.full_url
    assert req.headers.get("Title") == "t"
    assert req.headers.get("Priority") == "5"  # urgent


def test_ntfy_custom_server(monkeypatch):
    monkeypatch.setenv("NTFY_TOPIC", "x")
    monkeypatch.setenv("NTFY_SERVER", "https://my.ntfy.io/")
    with patch("urllib.request.urlopen", return_value=_ok()) as urlopen:
        NtfyNotifier().send("hi")
    req = urlopen.call_args[0][0]
    assert req.full_url == "https://my.ntfy.io/x"


def test_ntfy_network_error_returns_false(monkeypatch):
    monkeypatch.setenv("NTFY_TOPIC", "x")
    with patch("urllib.request.urlopen", side_effect=Exception("network")):
        assert NtfyNotifier().send("hi") is False


def test_ntfy_truncates_long_messages(monkeypatch):
    monkeypatch.setenv("NTFY_TOPIC", "x")
    big = "A" * (MAX_MESSAGE_CHARS + 5000)
    with patch("urllib.request.urlopen", return_value=_ok()) as urlopen:
        NtfyNotifier().send(big)
    req = urlopen.call_args[0][0]
    assert len(req.data) <= MAX_MESSAGE_CHARS


# ─── TelegramNotifier ────────────────────────────────────────

def test_telegram_not_configured(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert TelegramNotifier().configured is False


def test_telegram_send_success(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "bot:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    with patch("urllib.request.urlopen", return_value=_ok()) as urlopen:
        ok = TelegramNotifier().send("body", title="brief")
    assert ok is True
    req = urlopen.call_args[0][0]
    assert "api.telegram.org/botbot:abc/sendMessage" in req.full_url
    import json
    payload = json.loads(req.data)
    assert payload["chat_id"] == "12345"
    # Plain text — title is just newline-separated, no markdown wrappers
    assert payload["text"].startswith("brief\n\nbody")
    # parse_mode must NOT be set (Markdown V1 rejects our **bold**)
    assert "parse_mode" not in payload


def test_telegram_network_error_returns_false(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    with patch("urllib.request.urlopen", side_effect=Exception("e")):
        assert TelegramNotifier().send("hi") is False


# ─── SlackNotifier ────────────────────────────────────────────

def test_slack_not_configured(monkeypatch):
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    assert SlackNotifier().configured is False


def test_slack_send_success(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/X")
    with patch("urllib.request.urlopen", return_value=_ok()) as urlopen:
        ok = SlackNotifier().send("hello", title="brief")
    assert ok is True
    req = urlopen.call_args[0][0]
    assert req.full_url == "https://hooks.slack.com/services/X"


# ─── fan_out ──────────────────────────────────────────────────

def test_fan_out_sends_to_all_configured(monkeypatch):
    monkeypatch.setenv("NTFY_TOPIC", "x")
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/x")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    with patch("urllib.request.urlopen", return_value=_ok()):
        results = fan_out(["ntfy", "telegram", "slack"], "msg", title="t")
    assert results["ntfy"] is True
    assert results["telegram"] is False  # not configured
    assert results["slack"] is True


def test_fan_out_unknown_notifier_silently_skipped(monkeypatch):
    monkeypatch.setenv("NTFY_TOPIC", "x")
    with patch("urllib.request.urlopen", return_value=_ok()):
        results = fan_out(["ntfy", "carrier_pigeon"], "msg")
    assert results["ntfy"] is True
    assert results["carrier_pigeon"] is False


def test_fan_out_swallows_unexpected_exceptions(monkeypatch):
    """A buggy notifier subclass should not propagate exceptions out of fan_out."""
    monkeypatch.setenv("NTFY_TOPIC", "x")
    with patch("urllib.request.urlopen", side_effect=RuntimeError("kaboom")):
        results = fan_out(["ntfy"], "msg")
    assert results["ntfy"] is False
