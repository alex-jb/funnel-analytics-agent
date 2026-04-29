"""Build quality source — read build-quality-agent's review log.

Cross-agent integration: this funnel source consumes build-quality-agent's
~/.build-quality-agent/usage.jsonl. Each row written by BQA represents
one pre-push review with `verdict` ∈ {"PASS", "BLOCK"}.

Metrics produced:
- bqa_pass_count_24h:   # of PASS verdicts in last 24h
- bqa_block_count_24h:  # of BLOCK verdicts in last 24h
- bqa_block_rate_pct:   100 * blocks / (passes + blocks)
                        — alerts when > 30% (you're shipping a lot of bad commits)

Note: BQA skips (BUILD_AGENT_SKIP=1) don't write a row, so this source
can't see them. That's intentional — skips are deliberate, not a quality
signal.
"""
from __future__ import annotations
import json
import os
import pathlib
from datetime import datetime, timezone, timedelta

from solo_founder_os.source import MetricSample, Source, SourceReport


DEFAULT_BQA_LOG = pathlib.Path.home() / ".build-quality-agent" / "usage.jsonl"


class BuildQualitySource(Source):
    name = "build_quality"

    @property
    def configured(self) -> bool:
        """Always treated as 'configured' — the source falls back to a
        clean empty report if the log doesn't exist (e.g. user never
        installed BQA). It's harmless data noise, not a config error.
        """
        return True

    def _log_path(self) -> pathlib.Path:
        override = os.getenv("BUILD_AGENT_USAGE_LOG")
        return pathlib.Path(override) if override else DEFAULT_BQA_LOG

    def fetch(self) -> SourceReport:
        now = datetime.now(timezone.utc)
        report = SourceReport(source=self.name, fetched_at=now)
        log = self._log_path()

        if not log.exists():
            # Not an error — BQA may not be installed yet on this machine
            report.metrics.append(MetricSample(
                name="bqa_log_present",
                value=0,
                severity="info",
                note="(no BQA log found — install build-quality-agent to populate)",
            ))
            return report

        cutoff = now - timedelta(hours=24)
        passes = 0
        blocks = 0

        try:
            for line in log.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    ts = datetime.fromisoformat(row["ts"].replace("Z", "+00:00"))
                except Exception:
                    continue
                if ts < cutoff:
                    continue
                verdict = (row.get("verdict") or "").upper()
                if verdict == "PASS":
                    passes += 1
                elif verdict == "BLOCK":
                    blocks += 1
        except Exception as e:
            report.error = f"could not read BQA log: {e}"
            return report

        report.metrics.append(MetricSample(
            name="bqa_pass_count_24h",
            value=passes,
            severity="info",
            note=f"{passes} push(es) PASSed BQA review in last 24h",
        ))
        report.metrics.append(MetricSample(
            name="bqa_block_count_24h",
            value=blocks,
            severity=("alert" if blocks >= 5 else
                      "warn" if blocks >= 2 else "info"),
            note=f"{blocks} push(es) BLOCKed by BQA in last 24h",
        ))

        total = passes + blocks
        if total > 0:
            block_rate = 100.0 * blocks / total
            report.metrics.append(MetricSample(
                name="bqa_block_rate_pct",
                value=round(block_rate, 1),
                severity=("alert" if block_rate > 30 else
                          "warn" if block_rate > 15 else "info"),
                note=f"{block_rate:.1f}% block rate across {total} review(s) "
                     f"— code quality trend",
            ))

        return report
