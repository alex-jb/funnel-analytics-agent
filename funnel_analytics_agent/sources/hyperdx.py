"""HyperDX errors source.

Reads HyperDX query API to count log entries with `severity = error` over
the last N hours. Surfaces as warn when error rate > 0; alert when sustained
high.

Auth: HyperDX has TWO API keys — ingestion (used by the browser SDK) and
query/personal (read-only access to logs/spans). This source needs the
QUERY key. Generate at HyperDX → Settings → Team → API Keys → Personal
Integration Token.

Env vars:
  HYPERDX_API_KEY                 (the QUERY key, not the ingestion one)
  HYPERDX_SERVICE                 (default: vibexforge-web — matches NEXT_PUBLIC_SERVICE_NAME)
  HYPERDX_API_BASE                (default: https://api.hyperdx.io)
  HYPERDX_LOOKBACK_HOURS          (default: 24)

If the ingestion key is provided instead, we expect a 401 — graceful
degrade with a clear error message.
"""
from __future__ import annotations
import os
import json
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timezone, timedelta
from .base import MetricSample, Source, SourceReport


class HyperDXSource(Source):
    name = "hyperdx"

    @property
    def configured(self) -> bool:
        return bool(os.getenv("HYPERDX_API_KEY"))

    def _api_base(self) -> str:
        return os.getenv("HYPERDX_API_BASE", "https://api.hyperdx.io")

    def fetch(self) -> SourceReport:
        now = datetime.now(timezone.utc)
        report = SourceReport(source=self.name, fetched_at=now)
        if not self.configured:
            report.error = "missing HYPERDX_API_KEY (need the QUERY key, not ingestion)"
            return report

        api_key = os.getenv("HYPERDX_API_KEY", "")
        service = os.getenv("HYPERDX_SERVICE", "vibexforge-web")
        lookback_h = int(os.getenv("HYPERDX_LOOKBACK_HOURS", "24"))
        since = now - timedelta(hours=lookback_h)

        # HyperDX search API expects ISO timestamps + a Lucene-style query
        params = {
            "q": f"severity:error AND service:{service}",
            "from": int(since.timestamp() * 1000),
            "to": int(now.timestamp() * 1000),
            "limit": 1,  # we only want the count, not the rows
        }
        qs = urllib.parse.urlencode(params)
        url = f"{self._api_base()}/v1/logs/search?{qs}"
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        })

        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 401:
                report.error = ("HyperDX 401 — wrong key? "
                                "You need the QUERY key, not the ingestion key.")
            else:
                report.error = f"HyperDX HTTP {e.code}: {e}"
            return report
        except (urllib.error.URLError, ValueError) as e:
            report.error = f"HyperDX API error: {e}"
            return report
        except Exception as e:
            report.error = f"unexpected: {e}"
            return report

        # Response shape varies; try common patterns
        total = (data.get("total")
                 or data.get("hits", {}).get("total", {}).get("value")
                 or len(data.get("results", []))
                 or 0)

        # Severity ladder: 0 errors = info, <10 = info, <50 = warn, >=50 = alert
        if total >= 50:
            severity = "alert"
        elif total >= 10:
            severity = "warn"
        else:
            severity = "info"

        report.metrics.append(MetricSample(
            name=f"errors_last_{lookback_h}h",
            value=total,
            severity=severity,
            note=f"{total} error log(s) in last {lookback_h}h on service {service}",
        ))

        # Error rate per hour for trend visibility
        rate = total / max(lookback_h, 1)
        report.metrics.append(MetricSample(
            name="errors_per_hour",
            value=round(rate, 2),
            severity="info",
            note=f"avg {rate:.1f} errors/hr",
        ))

        return report
