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

from .brief import compose_brief, has_critical
from .sources import (
    VercelSource,
    ProductHuntSource,
    SupabaseAdvisorSource,
    OpenPanelSource,
    HyperDXSource,
)
from .sources.base import Source

ALL_SOURCES: dict[str, type[Source]] = {
    "vercel": VercelSource,
    "producthunt": ProductHuntSource,
    "supabase": SupabaseAdvisorSource,
    "openpanel": OpenPanelSource,
    "hyperdx": HyperDXSource,
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
    p.add_argument("--source", action="append", default=None,
                   choices=list(ALL_SOURCES.keys()),
                   help="Limit to specific source(s); default: all configured")
    p.add_argument("--out", default=None,
                   help="Write brief to file instead of stdout")
    p.add_argument("--title", default=None,
                   help="Custom brief title")
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

    if args.alert:
        # Real-time alert mode: exit 2 if any critical/alert
        if has_critical(reports):
            for r in reports:
                for m in r.metrics:
                    if m.severity in ("critical", "alert"):
                        print(f"[{r.source}] {m.severity.upper()}: {m.note}",
                              file=sys.stderr)
            return 2
        return 0

    # Default: brief mode
    text = compose_brief(reports, title=args.title)
    if args.out:
        Path(args.out).write_text(text)
        print(f"✓ brief written to {args.out}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
