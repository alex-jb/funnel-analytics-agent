# funnel-analytics-agent

**English** | [中文](README.zh-CN.md)

> Daily morning brief + real-time anomaly alerts for indie launches. Reads Vercel + OpenPanel + HyperDX + Supabase + Product Hunt, surfaces what's broken before your users tell you.

[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](#)

Built by [Alex Ji](https://github.com/alex-jb) — solo founder shipping [VibeXForge](https://github.com/alex-jb/vibex). Born from this thought:

> *On Product Hunt launch day my dashboard tabs were Vercel + OpenPanel + HyperDX + Supabase + Product Hunt + GitHub. Cycling through them = 1 hour/day. Missing a 5xx for 2 hours = lost the launch.*

## What it does

Two modes, one agent:

**Brief mode** — runs every morning (cron), composes a markdown brief from all data sources, drops it in your Obsidian vault. You read it over coffee in 30 seconds.

**Alert mode** — runs every 10 minutes during your launch window, exits with code `2` if anything critical/alert severity is found. Your wrapper script pages you (Telegram, Slack, ntfy.sh).

Sources in v0.2:
- **Vercel** — latest deployment state, deployments in last 24h, failed deploys
- **Product Hunt** — live vote count, comment count, momentum check on launch day
- **Supabase advisor** — security + performance lints; surfaces every CRITICAL individually
- **OpenPanel** — count of tracked events (signup_completed, project_submit_completed, …) over last 24h; warns when an event drops to 0 (tracking regression)
- **HyperDX** — error log count over last N hours; severity climbs from info → warn → alert as count crosses 10 / 50 thresholds

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
- [ ] **v0.4** — Push notifier adapters (Telegram, ntfy.sh, Slack)
- [ ] **v0.5** — Claude-summarized brief — LLM rewrites raw metrics as plain-English narrative

## License

MIT.
