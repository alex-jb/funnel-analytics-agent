"""CLI entry — funnel-analytics-agent.

Modes:
    --brief     compose a markdown brief and print to stdout (default)
    --alert     fetch sources, exit 0 normally, exit 2 if anything critical
    --out FILE  write brief to file instead of stdout

Sources can be selectively enabled via --source flag (default: all configured).

Example cron at 6:57am local on PH day for live monitoring:
    7,17,27,37,47,57 * * * 4 5 cd /opt/funnel && python3 -m funnel_analytics_agent --alert >> /tmp/funnel.log

Bypass: FUNNEL_AGENT_SKIP=1 stops any output (graceful degradation).
"""
from __future__ import annotations
import argparse
import os
import sys
from pathlib import Path

from .baseline import enrich_with_baseline, record_samples
from .brief import compose_brief, has_critical
from .notifier import ALL_NOTIFIERS, fan_out
from .summarizer import summarize
from .sources import (
    VercelSource,
    ProductHuntSource,
    SupabaseAdvisorSource,
    OpenPanelSource,
    HyperDXSource,
    BuildQualitySource,
    AgentSpendSource,
    VibexSource,
    GithubStarsSource,
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
    "vibex": VibexSource,
    "github_stars": GithubStarsSource,
}


def main(argv: list[str] | None = None) -> int:
    if os.getenv("FUNNEL_AGENT_SKIP") == "1":
        return 0

    p = argparse.ArgumentParser(
        prog="funnel-analytics-agent",
        description="Daily brief + real-time anomaly alerts for indie launches.",
    )
    p.add_argument("--brief", action="store_true",
                   help="Compose markdown brief (default mode)")
    p.add_argument("--alert", action="store_true",
                   help="Real-time mode — exit 2 if critical/alert severity found")
    p.add_argument("--retro", action="store_true",
                   help="Generate post-launch retrospective (markdown). Pulls "
                        "all sources, writes a 'what just happened' summary "
                        "fit for Obsidian / dev.to / X.")
    p.add_argument("--since-hours", type=int, default=24,
                   help="Window for --retro mode (default 24h = PH+24h post-mortem)")
    p.add_argument("--source", action="append", default=None,
                   choices=list(ALL_SOURCES.keys()),
                   help="Limit to specific source(s); default: all configured")
    p.add_argument("--out", default=None,
                   help="Write brief to file instead of stdout")
    p.add_argument("--title", default=None,
                   help="Custom brief title")
    p.add_argument("--no-baseline", action="store_true",
                   help="Skip 7-day baseline lookup + recording (useful for tests)")
    p.add_argument("--no-summary", action="store_true",
                   help="Skip the Claude-generated narrative summary at the top of the brief.")
    p.add_argument("--notify", default=None,
                   help="Comma-separated notifier list (ntfy,telegram,slack). "
                        "Default: NOTIFIER_DEFAULT env var or none.")
    args = p.parse_args(argv)

    selected = args.source or list(ALL_SOURCES.keys())
    sources = [ALL_SOURCES[name]() for name in selected]
    reports = []
    for s in sources:
        try:
            reports.append(s.fetch())
        except Exception as e:
            # Defensive: any source bug should not crash the agent.
            from .sources.base import SourceReport
            from datetime import datetime, timezone
            reports.append(SourceReport(
                source=s.name,
                fetched_at=datetime.now(timezone.utc),
                error=f"unhandled: {e}",
            ))

    # Enrich with 7-day baseline (mutates reports in place; populates
    # baseline + delta_pct, may promote severity on big drops)
    if not args.no_baseline:
        enrich_with_baseline(reports)
        record_samples(reports)

    # Resolve notifier list (CLI arg > env var > none)
    notify_str = args.notify or os.getenv("NOTIFIER_DEFAULT", "")
    notify_targets = [n.strip() for n in notify_str.split(",")
                      if n.strip() and n.strip() in ALL_NOTIFIERS]

    # ── Retro mode ───────────────────────────────────────────
    # Doesn't write to baseline (it's a one-shot post-mortem, not a sample).
    if args.retro:
        from .retro import render_retro
        text = render_retro(reports, since_hours=args.since_hours)
        if args.out:
            Path(args.out).write_text(text)
            print(f"✓ retro written to {args.out}", file=sys.stderr)
        else:
            print(text)
        return 0

    if args.alert:
        # Real-time alert mode: exit 2 if any critical/alert
        if has_critical(reports):
            critical_lines: list[str] = []
            for r in reports:
                for m in r.metrics:
                    if m.severity in ("critical", "alert"):
                        line = f"[{r.source}] {m.severity.upper()}: {m.note}"
                        critical_lines.append(line)
                        print(line, file=sys.stderr)
                        # Reflexion log: alerts during PH-day are the
                        # signal-richest moments. Per-source so we learn
                        # which sources tend to misfire vs catch real issues.
                        try:
                            from solo_founder_os import log_outcome
                            log_outcome(".funnel-analytics-agent",
                                        task=f"alert_{r.source}",
                                        outcome="FAILED",
                                        signal=f"{m.severity}: {m.note[:200]}")
                        except Exception:
                            pass
            # Push notification on critical/alert
            if notify_targets and critical_lines:
                results = fan_out(
                    notify_targets,
                    "\n".join(critical_lines),
                    title=f"funnel-agent · {len(critical_lines)} alert(s)",
                    priority="urgent",
                )
                for name, ok in results.items():
                    icon = "✓" if ok else "✗"
                    print(f"  notifier {icon} {name}", file=sys.stderr)
            return 2
        return 0

    # Default: brief mode — optionally prepend Claude narrative summary
    summary_text = None if args.no_summary else summarize(reports)
    text = compose_brief(reports, title=args.title, summary=summary_text)
    if args.out:
        Path(args.out).write_text(text)
        print(f"✓ brief written to {args.out}", file=sys.stderr)
    else:
        print(text)

    # Push the brief if any notifier configured
    if notify_targets:
        priority = "high" if has_critical(reports) else "default"
        results = fan_out(
            notify_targets,
            text,
            title=args.title or "morning brief",
            priority=priority,
        )
        for name, ok in results.items():
            icon = "✓" if ok else "✗"
            print(f"  notifier {icon} {name}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
