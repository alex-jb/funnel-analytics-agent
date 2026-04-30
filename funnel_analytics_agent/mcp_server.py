"""MCP (Model Context Protocol) server for funnel-analytics-agent.

Exposes the agent's core operations as MCP tools so Claude Desktop /
Cursor / Zed users can query the funnel state from inside their AI
assistant without ever leaving it.

Tools exposed:
  - get_brief() → markdown morning brief (same content as the daily cron)
  - get_alerts() → list of critical/alert metrics, or "all clear"
  - get_source(name) → single source's metrics for ad-hoc deep dives
  - usage_summary() → token + cost totals from local usage.jsonl

Install:
    pip install funnel-analytics-agent[mcp]

Wire to Claude Desktop (~/Library/Application Support/Claude/claude_desktop_config.json):

    {
      "mcpServers": {
        "funnel-analytics": {
          "command": "funnel-analytics-mcp",
          "env": {
            "VERCEL_TOKEN": "...",
            "PH_DEV_TOKEN": "...",
            "ANTHROPIC_API_KEY": "...",
            ...
          }
        }
      }
    }

Restart Claude Desktop. Now you can ask "show me today's funnel brief"
and the model gets the structured report directly.
"""
from __future__ import annotations
import os
import sys
from datetime import datetime, timezone

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as e:
    print("funnel-analytics-mcp requires the `mcp` package. "
          "Install with: pip install 'funnel-analytics-agent[mcp]'",
          file=sys.stderr)
    raise SystemExit(1) from e

from .baseline import enrich_with_baseline, record_samples
from .brief import compose_brief, has_critical
from .summarizer import summarize
from .sources import (
    VercelSource,
    ProductHuntSource,
    SupabaseAdvisorSource,
    OpenPanelSource,
    HyperDXSource,
    BuildQualitySource,
    AgentSpendSource,
)
from .sources.base import Source

ALL_SOURCES: dict[str, type[Source]] = {
    "vercel": VercelSource,
    "producthunt": ProductHuntSource,
    "supabase": SupabaseAdvisorSource,
    "openpanel": OpenPanelSource,
    "hyperdx": HyperDXSource,
    "build_quality": BuildQualitySource,
    "agent_spend": AgentSpendSource,
}


mcp = FastMCP("funnel-analytics")


def _fetch_all_reports() -> list:
    """Helper: fetch all configured sources, with baseline enrichment.
    Returns a list of SourceReport objects ready for the brief composer."""
    reports = []
    for name, cls in ALL_SOURCES.items():
        source = cls()
        try:
            reports.append(source.fetch())
        except Exception as e:
            from .sources.base import SourceReport
            reports.append(SourceReport(
                source=name,
                fetched_at=datetime.now(timezone.utc),
                error=f"unhandled: {e}",
            ))
    enrich_with_baseline(reports)
    record_samples(reports)
    return reports


@mcp.tool()
def get_brief(include_summary: bool = True) -> str:
    """Generate the funnel-analytics morning brief — the same markdown
    report the daily cron writes to your Obsidian vault.

    Reads Vercel deployments, Product Hunt votes, Supabase advisors,
    OpenPanel events, HyperDX errors, build-quality-agent review log,
    and aggregate Anthropic spend across the agent stack. Surfaces
    anomalies vs the 7-day baseline.

    Args:
        include_summary: if True (default), prepends a 2-4 sentence
            Claude-generated narrative summary. Set False for raw metrics.

    Returns: markdown brief.
    """
    reports = _fetch_all_reports()
    summary_text = summarize(reports) if include_summary else None
    return compose_brief(reports, summary=summary_text)


@mcp.tool()
def get_alerts() -> str:
    """Return only critical / alert / warn metrics. Skips the noise.

    Returns: short markdown listing each high-severity metric, or
    "All clear — no critical alerts" if nothing fires.
    """
    reports = _fetch_all_reports()
    if not has_critical(reports):
        warns = [(r.source, m) for r in reports for m in r.metrics
                 if m.severity == "warn"]
        if not warns:
            return "All clear — no critical alerts, no warnings."
        out = ["## 🟡 Warnings", ""]
        for s, m in warns:
            out.append(f"- **[{s}]** {m.note}")
        return "\n".join(out)

    out = []
    for r in reports:
        for m in r.metrics:
            if m.severity == "critical":
                out.append(f"🚨 **[{r.source}]** {m.note}")
            elif m.severity == "alert":
                out.append(f"❗ **[{r.source}]** {m.note}")
    return "\n".join(out)


@mcp.tool()
def get_source(name: str) -> str:
    """Run a single source by name and return its metrics as markdown.

    Args:
        name: one of vercel, producthunt, supabase, openpanel, hyperdx,
              build_quality, agent_spend.

    Returns: markdown report for that one source.
    """
    cls = ALL_SOURCES.get(name)
    if cls is None:
        avail = ", ".join(ALL_SOURCES.keys())
        return f"Unknown source: {name!r}. Available: {avail}"
    try:
        report = cls().fetch()
    except Exception as e:
        return f"Source {name!r} failed: {e}"
    if report.error:
        return f"**{name}** unavailable: {report.error}"
    out = [f"## {name}", ""]
    for m in report.metrics:
        line = f"- `{m.name}` = **{m.value}** ({m.severity})"
        if m.note:
            line += f" — {m.note}"
        out.append(line)
    return "\n".join(out)


@mcp.tool()
def usage_summary() -> str:
    """Return token + dollar usage from this agent's local log.

    Reads ~/.funnel-analytics-agent/usage.jsonl and reports total runs,
    cumulative input/output tokens, estimated $ spend at current Anthropic
    prices.

    Returns: formatted summary string.
    """
    from solo_founder_os.usage_log import usage_report
    import pathlib
    log = pathlib.Path.home() / ".funnel-analytics-agent" / "usage.jsonl"
    return usage_report(log)


def main() -> None:
    """Console-script entry point. Runs the MCP server over stdio."""
    if os.getenv("FUNNEL_AGENT_SKIP") == "1":
        return
    mcp.run()


if __name__ == "__main__":
    main()
