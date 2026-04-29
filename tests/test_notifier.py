"""Smoke tests for the notifier re-export shim.

Full coverage lives in solo-founder-os. This file just verifies the
re-exports work and ALL_NOTIFIERS contains the expected names.
"""
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from funnel_analytics_agent.notifier import (
    NtfyNotifier, TelegramNotifier, SlackNotifier,
    ALL_NOTIFIERS, fan_out,
)


def test_re_exports_are_classes():
    assert NtfyNotifier().name == "ntfy"
    assert TelegramNotifier().name == "telegram"
    assert SlackNotifier().name == "slack"


def test_all_notifiers_keys():
    assert set(ALL_NOTIFIERS.keys()) == {"ntfy", "telegram", "slack"}


def test_fan_out_unconfigured(monkeypatch):
    """Sanity: with no env, fan_out returns False for all notifiers and
    doesn't raise."""
    for k in ("NTFY_TOPIC", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
              "SLACK_WEBHOOK_URL"):
        monkeypatch.delenv(k, raising=False)
    results = fan_out(["ntfy", "telegram", "slack"], "msg")
    assert all(v is False for v in results.values())
