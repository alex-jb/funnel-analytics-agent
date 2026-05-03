# funnel-analytics-agent

**English** | [中文](README.zh-CN.md)

> Daily morning brief + real-time anomaly alerts for indie launches. Reads Vercel + OpenPanel + HyperDX + Supabase + Product Hunt, surfaces what's broken before your users tell you.

[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/funnel-analytics-agent.svg)](https://pypi.org/project/funnel-analytics-agent/)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](#)

Built by [Alex Ji](https://github.com/alex-jb) — solo founder shipping [VibeXForge](https://github.com/alex-jb/vibex). Born from this thought:

> *On Product Hunt launch day my dashboard tabs were Vercel + OpenPanel + HyperDX + Supabase + Product Hunt + GitHub. Cycling through them = 1 hour/day. Missing a 5xx for 2 hours = lost the launch.*

## What it does

Two modes, one agent:

**Brief mode** — runs every morning (cron), composes a markdown brief from all data sources, drops it in your Obsidian vault. You read it over coffee in 30 seconds.

**Alert mode** — runs every 10 minutes during your launch window, exits with code `2` if anything critical/alert severity is found. Your wrapper script pages you (Telegram, Slack, ntfy.sh).

Sources (v0.9, 8 total):
- **Vercel** — latest deployment state, deployments in last 24h, failed deploys
- **Product Hunt** — live vote count, comment count, momentum check on launch day
- **Supabase advisor** — security + performance lints; surfaces every CRITICAL individually
- **OpenPanel** — count of tracked events (signup_completed, project_submit_completed, …) over last 24h; warns when an event drops to 0 (tracking regression)
- **HyperDX** — error log count over last N hours; severity climbs from info → warn → alert as count crosses 10 / 50 thresholds
- **Build Quality** — last 24h of pre-push reviews from build-quality-agent's local log (verdicts, BLOCK count, token spend)
- **Agent Spend** — cross-agent Anthropic $ MTD aggregated across `~/.<agent>/usage.jsonl` files
- **VibeX** — direct SQL pull of core launch-board metrics (new creators / submissions / cumulative plays / stage distribution); zero Claude calls. Configure via `VIBEX_PROJECT_REF` (or reuse `SUPABASE_PROJECT_REF` if it's the same project)

## Install

```bash
git clone https://github.com/alex-jb/funnel-analytics-agent.git
cd funnel-analytics-agent
pip install -e .
cp .env.example .env
# fill in VERCEL_TOKEN, PH_DEV_TOKEN, etc
```

## Usage

```bash
# One-shot brief (default)
funnel-analytics-agent

# Write brief to file (e.g. for Obsidian vault)
funnel-analytics-agent --out ~/Documents/alex-brain/morning-briefs/$(date +%Y-%m-%d).md

# Real-time alert mode — exits 2 if anything critical
funnel-analytics-agent --alert

# Limit to specific source
funnel-analytics-agent --source vercel --source producthunt
```

### Cron setup for Product Hunt launch day

```cron
# Every 7 minutes during the 24h launch window — alert mode
7,17,27,37,47,57 * * * 1 /usr/local/bin/funnel-analytics-agent --alert || curl -d "PH alert" ntfy.sh/your-topic

# Daily brief at 7:03 AM (post-cap-reset)
3 7 * * * /usr/local/bin/funnel-analytics-agent --out ~/Documents/alex-brain/morning-briefs/$(date +\%Y-\%m-\%d).md
```

## Design choices

- **Each source fails independently.** Vercel API down? Your brief still gets PH stats. The failed source is listed at the bottom of the brief; never kills the whole agent.
- **No external dependencies (yet).** Pure stdlib `urllib` — no requests, no httpx, no API client SDKs. Keeps install fast and pip-install-friendly on locked-down boxes.
- **Markdown-first output.** Output is meant to be human-readable in Obsidian / VS Code, not piped through a dashboard service.
- **Exit codes for cron, not push notifications.** v0.1-v0.3 don't ship a Telegram/Slack adapter — your cron wrapper does that. Keeps the agent's surface tiny.
- **7-day baseline auto-built from your own runs.** No need to seed historical data. After 24h of cron runs the baseline starts forming; after 7 days it's solid. Bootstrap mode (no history) just skips delta calculation — never blocks output.

## Roadmap

- [x] **v0.1** — Vercel + Product Hunt sources · brief mode · alert mode · cron-friendly
- [x] **v0.2** — OpenPanel, HyperDX, Supabase advisor sources (5 sources total, 30 tests)
- [x] **v0.3** — 7-day baseline · `delta_pct` enrichment · severity promotion on >50% drops · 41 tests
- [x] **v0.4** — Push notifier adapters (ntfy.sh / Telegram / Slack) + macOS launchd installer (54 tests)
- [x] **v0.5** — Claude-summarized brief at top of every report (Haiku 4.5 default; ~$0.0008/run; falls back gracefully)
- [x] **v0.8** — MCP server: query the morning brief / live alerts / per-source state from Claude Desktop

## MCP server (Claude Desktop / Cursor / Zed)

Expose the brief, alert state, and individual sources as tools your AI assistant can call.

```bash
pip install 'funnel-analytics-agent[mcp]'
```

Then add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "funnel-analytics": {
      "command": "funnel-analytics-mcp",
      "env": {
        "VERCEL_TOKEN": "...",
        "VERCEL_PROJECT_ID": "...",
        "PH_DEV_TOKEN": "...",
        "PH_LAUNCH_SLUG": "your-launch-slug",
        "OPENPANEL_CLIENT_ID": "...",
        "OPENPANEL_CLIENT_SECRET": "...",
        "HYPERDX_API_KEY": "...",
        "SUPABASE_PERSONAL_ACCESS_TOKEN": "...",
        "SUPABASE_PROJECT_REF": "...",
        "ANTHROPIC_API_KEY": "..."
      }
    }
  }
}
```

Tools:
- `get_brief(include_summary)` — full markdown morning brief
- `get_alerts()` — alert-mode output: `All clear` or per-source severity
- `get_source(name)` — single source (vercel / producthunt / openpanel / hyperdx / supabase)
- `usage_summary()` — Anthropic token + $ totals from local usage log

## License

MIT.
---

## 🧩 Part of the [Solo Founder OS](https://github.com/alex-jb/solo-founder-os) stack

A growing collection of MIT-licensed agents that share `solo-founder-os` as their base — Source/MetricSample contracts, HITL queue, AnthropicClient, notifiers, scheduler. Each agent is independently useful; together they cover the full solo-founder workflow.

| Agent | What it does |
|---|---|
| [solo-founder-os](https://github.com/alex-jb/solo-founder-os) | The shared base lib (Source/MetricSample, AnthropicClient, HITL queue, notifiers, sfos-doctor / sfos-evolver / sfos-eval / sfos-retro / sfos-bus / sfos-inbox) |
| [build-quality-agent](https://github.com/alex-jb/build-quality-agent) | Pre-push diff reviewer + local build runner — catches CI-killing changes before they ship |
| [customer-discovery-agent](https://github.com/alex-jb/customer-discovery-agent) | Reddit pain-point scraper + Claude clustering for product validation |
| [vc-outreach-agent](https://github.com/alex-jb/vc-outreach-agent) | Investor cold email drafter with HITL queue + SMTP sender |
| [cost-audit-agent](https://github.com/alex-jb/cost-audit-agent) | Monthly bill audit across 6 providers with dollar-tagged waste findings |
| [bilingual-content-sync-agent](https://github.com/alex-jb/bilingual-content-sync-agent) | EN ⇄ ZH i18n diff + Claude translate + HITL apply |
| [orallexa-marketing-agent](https://github.com/alex-jb/orallexa-marketing-agent) | AI marketing agent for OSS founders — auto-generate platform-specific marketing posts |

*Each agent's own row is omitted from its README. Install whichever solve real problems for you.*
