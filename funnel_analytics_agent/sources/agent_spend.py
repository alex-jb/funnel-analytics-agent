"""Agent spend source — aggregate Anthropic $ across all solo-founder-os agents.

Cross-agent integration: scans every ~/.<agent>/usage.jsonl that exists,
sums today's spend, surfaces it as a daily metric in the funnel brief.

Why this lives in funnel and not cost-audit: cost-audit reports MONTHLY
to a markdown file you read once. Funnel reports DAILY in the morning
brief — different cadence, different consumer. The shared lib's PRICES
table makes the calculation trivial in both places.

Metrics:
- anthropic_spend_24h_usd: total $ spent on Claude calls in last 24h
                          across all agent logs. Severity climbs at $1
                          and $5 thresholds (typical indie founder
                          baseline: $0.05/day).
- anthropic_calls_24h: total # of LLM calls
- spend_by_agent: one info-severity metric per agent (so you see which
                  one's burning tokens)
"""
from __future__ import annotations
import json
import os
import pathlib
from datetime import datetime, timezone, timedelta

from solo_founder_os.source import MetricSample, Source, SourceReport
from solo_founder_os.usage_log import PRICES


# Agents whose usage.jsonl we scan. Mirrors cost-audit-agent's LOCAL_LOG_AGENTS
# but kept independent so funnel doesn't depend on cost-audit's internal list.
KNOWN_AGENT_DIRS = [
    ".build-quality-agent",
    ".funnel-analytics-agent",
    ".vc-outreach-agent",
    ".customer-discovery-agent",
    ".bilingual-content-sync-agent",
]


def _cost_for(model: str, in_tok: int, out_tok: int) -> float:
    """Use the canonical PRICES table from solo_founder_os."""
    in_p, out_p = PRICES.get(model, (1.0, 5.0))
    return (in_tok * in_p + out_tok * out_p) / 1_000_000


class AgentSpendSource(Source):
    name = "agent_spend"

    @property
    def configured(self) -> bool:
        """Always configured — empty if no agents installed yet."""
        return True

    def fetch(self) -> SourceReport:
        now = datetime.now(timezone.utc)
        report = SourceReport(source=self.name, fetched_at=now)
        cutoff = now - timedelta(hours=24)
        home = pathlib.Path.home()

        per_agent_cost: dict[str, float] = {}
        per_agent_calls: dict[str, int] = {}

        for agent_dir in KNOWN_AGENT_DIRS:
            log = home / agent_dir / "usage.jsonl"
            if not log.exists():
                continue
            try:
                for line in log.read_text().splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                        ts = datetime.fromisoformat(
                            row["ts"].replace("Z", "+00:00"))
                    except Exception:
                        continue
                    if ts < cutoff:
                        continue
                    model = row.get("model", "unknown")
                    in_tok = row.get("input_tokens", 0)
                    out_tok = row.get("output_tokens", 0)
                    cost = _cost_for(model, in_tok, out_tok)
                    per_agent_cost[agent_dir] = (
                        per_agent_cost.get(agent_dir, 0.0) + cost)
                    per_agent_calls[agent_dir] = (
                        per_agent_calls.get(agent_dir, 0) + 1)
            except Exception:
                continue  # one bad log doesn't kill the source

        total_cost = sum(per_agent_cost.values())
        total_calls = sum(per_agent_calls.values())

        # Severity ladder — opinionated indie-founder thresholds.
        # $0.05/day baseline → $1/day = unusual → $5/day = something running away
        if total_cost >= 5.0:
            sev = "alert"
        elif total_cost >= 1.0:
            sev = "warn"
        else:
            sev = "info"

        report.metrics.append(MetricSample(
            name="anthropic_spend_24h_usd",
            value=round(total_cost, 4),
            severity=sev,
            note=f"${total_cost:.4f} across {total_calls} LLM call(s) in last 24h",
        ))
        report.metrics.append(MetricSample(
            name="anthropic_calls_24h",
            value=total_calls,
            severity="info",
            note=f"{total_calls} LLM call(s) total across stack",
        ))

        # Per-agent breakdown — info severity (visibility, not alerting)
        for agent_dir, cost in sorted(per_agent_cost.items(),
                                       key=lambda kv: -kv[1]):
            calls = per_agent_calls.get(agent_dir, 0)
            display_name = agent_dir.lstrip(".")
            report.metrics.append(MetricSample(
                name=f"spend_{display_name.replace('-', '_')}_24h_usd",
                value=round(cost, 4),
                severity="info",
                note=f"{display_name}: ${cost:.4f} across {calls} call(s)",
            ))

        return report
