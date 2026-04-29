"""Claude-powered narrative summary for the morning brief.

Uses solo_founder_os.AnthropicClient for graceful degrade + automatic
cost log to ~/.funnel-analytics-agent/usage.jsonl. cost-audit-agent
reads that file and aggregates monthly spend.

The prompt is unchanged from v0.5; the only refactor is wiring through
the shared client.
"""
from __future__ import annotations
import os
import pathlib
from typing import Iterable

from solo_founder_os.anthropic_client import (
    AnthropicClient,
    DEFAULT_HAIKU_MODEL,
)
from solo_founder_os.source import SourceReport


DEFAULT_MODEL = os.getenv("FUNNEL_SUMMARY_MODEL", DEFAULT_HAIKU_MODEL)
USAGE_LOG_PATH = (pathlib.Path.home()
                  / ".funnel-analytics-agent" / "usage.jsonl")


SYSTEM_PROMPT = """You are an indie founder's morning briefing analyst.

Given a structured snapshot of metrics from Vercel / Product Hunt / Supabase
advisors / OpenPanel / HyperDX, write a 2-4 sentence executive summary
covering ONLY what matters this morning.

Rules:
1. Lead with the most important signal — anomalies / drops / failures FIRST.
2. If everything looks normal, say so plainly in one sentence — don't pad.
3. Use concrete numbers. "Signups -70% vs 7-day median" beats "down significantly".
4. Connect dots across sources when possible. "Errors spiked at 21:34 around
   the Vercel deploy that completed in ERROR state at 21:32."
5. End with the ONE action the founder should take (or "no action needed").
6. NO markdown, NO bullets, NO emoji. Plain sentences. < 100 words total.
7. NEVER hallucinate values. Use only what's in the input.

Output the summary directly. No preamble, no quotation marks, no header."""


def _build_input(reports: Iterable[SourceReport]) -> str:
    """Render the source reports as a flat key:value list Claude can scan."""
    lines: list[str] = []
    for r in reports:
        if r.error:
            lines.append(f"[{r.source}] UNAVAILABLE: {r.error}")
            continue
        lines.append(f"[{r.source}]")
        for m in r.metrics:
            row = f"  - {m.name}={m.value} ({m.severity})"
            if m.baseline is not None and m.delta_pct is not None:
                sign = "+" if m.delta_pct >= 0 else ""
                row += f" baseline={m.baseline} delta={sign}{m.delta_pct:.1f}%"
            if m.note:
                row += f" — {m.note}"
            lines.append(row)
    return "\n".join(lines)


def summarize(reports: list[SourceReport],
              *, model: str = DEFAULT_MODEL,
              client: AnthropicClient | None = None) -> str:
    """Return a 2-4 sentence narrative summary of the reports, or "" if no
    LLM is available / the call fails.

    `client` is injectable for tests. In production, leave it None and the
    function constructs an AnthropicClient pointed at the funnel usage log.
    """
    if not reports:
        return ""

    user_input = _build_input(reports)
    if not user_input.strip():
        return ""

    if client is None:
        client = AnthropicClient(usage_log_path=USAGE_LOG_PATH)

    if not client.configured:
        return ""

    resp, err = client.messages_create(
        model=model,
        max_tokens=300,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_input}],
    )
    if err is not None:
        return ""
    return AnthropicClient.extract_text(resp)
