"""Push notifier adapters — re-exported from solo-founder-os.

Backward-compat shim so existing imports
`from funnel_analytics_agent.notifier import ...` keep working.
New code should:

    from solo_founder_os.notifier import fan_out, NtfyNotifier, ...
"""
from __future__ import annotations
from solo_founder_os.notifier import (
    Notifier,
    NtfyNotifier,
    TelegramNotifier,
    SlackNotifier,
    ALL_NOTIFIERS,
    fan_out,
    MAX_MESSAGE_CHARS,
)

__all__ = [
    "Notifier", "NtfyNotifier", "TelegramNotifier", "SlackNotifier",
    "ALL_NOTIFIERS", "fan_out", "MAX_MESSAGE_CHARS",
]
