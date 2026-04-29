"""Push notifier adapters — fan out alerts to ntfy.sh / Telegram / Slack.

Same graceful-degrade contract as Source: missing creds = `configured = False`,
agent skips. Network/API failure = logged but doesn't crash.

Usage in CLI:
    --notify ntfy,telegram      explicit list
    NOTIFIER_DEFAULT=ntfy       default if --notify not given

In `--alert` mode: short compact message (severity+count summary). In default
brief mode: first 10 lines of brief (Telegram caps at 4096 chars, ntfy ~4kB
practical, Slack at 40kB but UX better with short blocks).
"""
from __future__ import annotations
import json
import os
import urllib.request
import urllib.error


# Truncate long messages for transports that don't handle multi-paragraph well
MAX_MESSAGE_CHARS = 3500


class Notifier:
    name: str = "base"

    @property
    def configured(self) -> bool:
        return False

    def send(self, message: str, *, title: str = "",
             priority: str = "default") -> bool:
        """Send a message. Returns True on success, False on failure (logged
        to stderr, never raises)."""
        raise NotImplementedError


class NtfyNotifier(Notifier):
    """ntfy.sh — free, no signup. Pick a topic name and subscribe via app.

    Env: NTFY_TOPIC (required), NTFY_SERVER (default: https://ntfy.sh)

    Priority maps: default → 3, high → 4, urgent → 5.
    """
    name = "ntfy"
    PRIORITY_MAP = {"default": "3", "high": "4", "urgent": "5"}

    @property
    def configured(self) -> bool:
        return bool(os.getenv("NTFY_TOPIC"))

    def send(self, message: str, *, title: str = "",
             priority: str = "default") -> bool:
        if not self.configured:
            return False
        topic = os.getenv("NTFY_TOPIC", "")
        server = os.getenv("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
        url = f"{server}/{topic}"

        body = message[:MAX_MESSAGE_CHARS].encode("utf-8")
        headers = {
            "Title": title or "funnel-analytics-agent",
            "Priority": self.PRIORITY_MAP.get(priority, "3"),
            "Tags": "rotating_light" if priority == "urgent" else "bell",
            "Markdown": "yes",
        }
        req = urllib.request.Request(url, data=body, headers=headers,
                                      method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status < 400
        except Exception:
            return False


class TelegramNotifier(Notifier):
    """Telegram via Bot API. Create a bot at @BotFather, get bot token, then
    message your bot once and grab your chat_id from
    https://api.telegram.org/bot<TOKEN>/getUpdates.

    Env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

    Sends as plain text (no parse_mode) on purpose: our briefs use
    `**bold**` (CommonMark) which Telegram's legacy "Markdown" mode rejects
    with HTTP 400, and the noise of escaping every special char for
    MarkdownV2 (_*[]()~`>#+-=|{}.!) isn't worth it for an alert. Plain text
    renders fine on every Telegram client.
    """
    name = "telegram"

    @property
    def configured(self) -> bool:
        return bool(os.getenv("TELEGRAM_BOT_TOKEN")) \
           and bool(os.getenv("TELEGRAM_CHAT_ID"))

    def send(self, message: str, *, title: str = "",
             priority: str = "default") -> bool:
        if not self.configured:
            return False
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        url = f"https://api.telegram.org/bot{token}/sendMessage"

        body = message[:MAX_MESSAGE_CHARS]
        if title:
            body = f"{title}\n\n{body}"
        payload = json.dumps({
            "chat_id": chat_id,
            "text": body,
            "disable_web_page_preview": True,
        }).encode()
        req = urllib.request.Request(url, data=payload,
                                      headers={"Content-Type": "application/json"},
                                      method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status < 400
        except Exception:
            return False


class SlackNotifier(Notifier):
    """Slack via incoming webhook. Get URL at api.slack.com/apps → your app
    → Incoming Webhooks → Add new webhook to workspace.

    Env: SLACK_WEBHOOK_URL
    """
    name = "slack"

    @property
    def configured(self) -> bool:
        return bool(os.getenv("SLACK_WEBHOOK_URL"))

    def send(self, message: str, *, title: str = "",
             priority: str = "default") -> bool:
        if not self.configured:
            return False
        webhook = os.getenv("SLACK_WEBHOOK_URL", "")

        body = message[:MAX_MESSAGE_CHARS]
        text = f"*{title}*\n\n{body}" if title else body
        payload = json.dumps({"text": text, "mrkdwn": True}).encode()
        req = urllib.request.Request(webhook, data=payload,
                                      headers={"Content-Type": "application/json"},
                                      method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status < 400
        except Exception:
            return False


ALL_NOTIFIERS: dict[str, type[Notifier]] = {
    "ntfy": NtfyNotifier,
    "telegram": TelegramNotifier,
    "slack": SlackNotifier,
}


def fan_out(notifier_names: list[str], message: str, *,
            title: str = "", priority: str = "default") -> dict[str, bool]:
    """Send the same message to all named notifiers. Returns
    {name: success_bool} so the caller can log who got it."""
    results: dict[str, bool] = {}
    for name in notifier_names:
        cls = ALL_NOTIFIERS.get(name)
        if cls is None:
            results[name] = False
            continue
        n = cls()
        if not n.configured:
            results[name] = False
            continue
        try:
            results[name] = n.send(message, title=title, priority=priority)
        except Exception:
            results[name] = False
    return results
