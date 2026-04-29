"""Claude-powered narrative summary for the morning brief.

Takes the raw SourceReport list, dumps the metrics into a structured prompt,
and asks Claude for a 2-4 sentence executive summary. Surfaces the most
important thing first ("signup dropped 70% overnight; root cause likely
the Vercel deploy that errored at 21:34"), not just a list of numbers.

Designed to read in 10 seconds before the rest of the brief.

Graceful degradation: no ANTHROPIC_API_KEY → returns "" (caller skips the
summary section). LLM error → same. Never blocks the brief from rendering.

Cost: ~600 input tokens + ~150 output per run. Haiku 4.5 default = ~$0.0008
per brief. Daily cron = ~$0.024/month. Negligible.
"""
from __future__ import annotations
import os
from typing import Iterable

from .sources.base import SourceReport


DEFAULT_MODEL = os.getenv("FUNNEL_SUMMARY_MODEL", "claude-haiku-4-5")


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
              *, model: str = DEFAULT_MODEL) -> str:
    """Return a 2-4 sentence narrative summary of the reports, or "" if no
    LLM is available / the call fails."""
    if not os.getenv("ANTHROPIC_API_KEY"):
        return ""
    if not reports:
        return ""

    user_input = _build_input(reports)
    if not user_input.strip():
        return ""

    try:
        from anthropic import Anthropic
        client = Anthropic()
        resp = client.messages.create(
            model=model,
            max_tokens=300,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_input}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        return text
    except Exception:
        return ""
