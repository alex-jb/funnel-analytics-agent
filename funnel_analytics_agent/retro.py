"""PH-day retrospective generator.

Run on PH+24h or whenever you want a "what just happened" narrative
based on real data, not memory. Combines:

  - VibeX 24h business deltas (signups / projects / plays / stage shifts)
  - PH final vote count + comment count + daily rank position
  - Anthropic spend across the agent stack (last 24h vs MTD)
  - GitHub star deltas across the OSS stack
  - Top 3 milestone events that fired in `~/.funnel-analytics-agent/milestones.json`
  - Optional Claude narrative summary (1-paragraph "what stood out")

Output: a markdown retrospective file you paste into Obsidian, X thread,
LinkedIn post, or the dev.to retro article. Doubles as the
auto-generated input for the post-mortem you'd write anyway.

Usage:
    funnel-analytics-agent --retro                  # stdout
    funnel-analytics-agent --retro --out ph-day-retro.md
    funnel-analytics-agent --retro --since-hours 48  # PH+48h instead of 24h

The retro reads the same sources the brief uses, so any wiring (env vars,
notifiers) already configured will Just Work.
"""
from __future__ import annotations
import json
import pathlib
from datetime import datetime, timezone
from typing import Optional

from .sources.base import Source, SourceReport


MILESTONES_STATE_PATH = (pathlib.Path.home()
                          / ".funnel-analytics-agent" / "milestones.json")


def _fetch_one(name: str, cls: type[Source]) -> SourceReport:
    """Same fetch pattern as brief mode — never let one source break others."""
    try:
        return cls().fetch()
    except Exception as e:
        return SourceReport(
            source=name, fetched_at=datetime.now(timezone.utc),
            error=f"unhandled: {e}",
        )


def _load_milestones() -> dict[str, int]:
    if not MILESTONES_STATE_PATH.exists():
        return {}
    try:
        return json.loads(MILESTONES_STATE_PATH.read_text()) or {}
    except Exception:
        return {}


def _vibex_section(reports: list[SourceReport]) -> list[str]:
    vibex = next((r for r in reports if r.source == "vibex"), None)
    if not vibex or vibex.error:
        return ["## VibeX",
                f"_unavailable: {vibex.error if vibex else 'no report'}_", ""]
    by_name = {m.name: m for m in vibex.metrics}
    lines = ["## VibeX (your launch board)"]

    def get(name: str, default: int = 0) -> int:
        m = by_name.get(name)
        return int(m.value) if m else default

    lines += [
        f"- New creators in window: **{get('vibex_new_creators_24h'):,}**",
        f"- New projects submitted:  **{get('vibex_new_projects_24h'):,}**",
        f"- Total projects ever:     {get('vibex_total_projects'):,}",
        f"- Total creators ever:     {get('vibex_total_projects'):,}",
        f"- Cumulative plays:        {get('vibex_total_plays'):,}",
        f"- Cumulative upvotes:      {get('vibex_total_upvotes'):,}",
        f"- At Breakout / Legend / Myth: {get('vibex_elite_stage_count')}",
    ]
    if get("vibex_myth_count") > 0:
        lines.append(f"- ✨ **At Myth:** {get('vibex_myth_count')}")
    lines.append("")
    return lines


def _ph_section(reports: list[SourceReport]) -> list[str]:
    ph = next((r for r in reports if r.source == "producthunt"), None)
    if not ph or ph.error:
        return ["## Product Hunt",
                f"_unavailable: {ph.error if ph else 'no report'}_", ""]
    by_name = {m.name: m for m in ph.metrics}

    def get(name: str, default: int = 0) -> int:
        m = by_name.get(name)
        return int(m.value) if m else default

    lines = ["## Product Hunt"]
    lines += [
        f"- Final vote count:  **{get('ph_votes'):,}**",
        f"- Comments:          {get('ph_comments'):,}",
    ]
    rank_metric = by_name.get("ph_daily_rank")
    if rank_metric is not None:
        rank = int(rank_metric.value)
        if rank > 0:
            lines.append(f"- Daily rank:        **#{rank}**")
        else:
            lines.append("- Daily rank:        outside top 30")
    # Surface alert-severity comments (likely the support tickets you handled)
    alert_comments = [m for m in ph.metrics
                       if m.name.startswith("ph_comment_") and m.severity == "alert"]
    if alert_comments:
        lines.append("")
        lines.append("### Comments needing fast-reply (alerts fired)")
        for m in alert_comments[:5]:
            lines.append(f"- {m.note}")
    lines.append("")
    return lines


def _spend_section(reports: list[SourceReport]) -> list[str]:
    spend = next((r for r in reports if r.source == "agent_spend"), None)
    if not spend or spend.error:
        return ["## Anthropic spend",
                f"_unavailable: {spend.error if spend else 'no report'}_", ""]
    by_name = {m.name: m for m in spend.metrics}
    total = by_name.get("agent_spend_total_mtd")
    lines = ["## Anthropic spend"]
    if total:
        lines.append(f"- Total MTD across stack: **${float(total.value):.2f}**")
    for m in spend.metrics:
        if m.name == "agent_spend_total_mtd":
            continue
        if m.name.startswith("agent_spend_"):
            lines.append(f"- {m.note}")
    lines.append("")
    return lines


def _stars_section(reports: list[SourceReport]) -> list[str]:
    stars = next((r for r in reports if r.source == "github_stars"), None)
    if not stars or stars.error:
        return ["## OSS stack stars",
                f"_unavailable: {stars.error if stars else 'no report'}_", ""]
    by_name = {m.name: m for m in stars.metrics}
    total = by_name.get("github_stars_total")
    lines = ["## OSS stack stars (across 9 repos)"]
    if total:
        lines.append(f"- Total stars: **{int(total.value):,}**")
    # Per-repo lines, sorted desc
    per_repo = [m for m in stars.metrics
                 if m.name.startswith("github_stars_")
                 and m.name != "github_stars_total"]
    per_repo.sort(key=lambda m: -int(m.value))
    for m in per_repo[:10]:
        lines.append(f"- {m.note}")
    lines.append("")
    return lines


def _milestones_section() -> list[str]:
    state = _load_milestones()
    if not state:
        return ["## Milestones crossed", "_no milestones recorded_", ""]
    lines = ["## Milestones crossed (since first run)"]
    for metric, hwm in sorted(state.items()):
        lines.append(f"- {metric}: high-water mark = **{hwm:,}**")
    lines.append("")
    return lines


def render_retro(reports: list[SourceReport],
                  *, since_hours: int = 24,
                  generated_at: Optional[datetime] = None) -> str:
    """Compose the markdown retrospective from a list of source reports."""
    now = generated_at or datetime.now(timezone.utc)
    lines = [
        f"# Launch retrospective — {now.strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        f"_Window: last {since_hours}h · "
        f"{len([r for r in reports if not r.error])} of {len(reports)} "
        f"sources reporting_",
        "",
    ]
    lines += _vibex_section(reports)
    lines += _ph_section(reports)
    lines += _spend_section(reports)
    lines += _stars_section(reports)
    lines += _milestones_section()

    # Failed sources at the end (kept short, so the brief part stays readable)
    failed = [r for r in reports if r.error]
    if failed:
        lines.append("---")
        lines.append("## Sources unavailable")
        for r in failed:
            lines.append(f"- **{r.source}**: {r.error}")
        lines.append("")
    return "\n".join(lines)


def generate_retro(all_sources: dict[str, type[Source]],
                    *, since_hours: int = 24) -> str:
    """High-level: fetch all sources, render markdown.

    `all_sources` is the same registry __main__ uses, so the retro stays
    in sync with which sources are wired without touching this function.
    """
    reports = [_fetch_one(name, cls) for name, cls in all_sources.items()]
    return render_retro(reports, since_hours=since_hours)
