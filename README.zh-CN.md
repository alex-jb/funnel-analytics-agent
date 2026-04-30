# funnel-analytics-agent

[English](README.md) | **中文**

> 给独立开发者 launch 用的每日早晨简报 + 实时异常告警。读 Vercel + OpenPanel + HyperDX + Supabase + Product Hunt,在用户骂你之前先告诉你哪里挂了。

[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/funnel-analytics-agent.svg)](https://pypi.org/project/funnel-analytics-agent/)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](#)

作者 [Alex Ji](https://github.com/alex-jb) — 单人独立开发者,在做 [VibeXForge](https://github.com/alex-jb/vibex)。这工具诞生于这一句话:

> *Product Hunt launch 当天我的浏览器 tab 是 Vercel + OpenPanel + HyperDX + Supabase + Product Hunt + GitHub。一圈刷下来要 1 小时。漏看 5xx 两小时 = launch 凉了。*

## 它干什么

两种模式,一个 agent:

**Brief 模式** —— 每天早晨 cron 跑一次,从所有数据源生成一份 markdown 简报,写到你 Obsidian vault 里。你喝咖啡的时候 30 秒读完。

**Alert 模式** —— launch 窗口期间每 10 分钟跑一次,发现 critical / alert 级别问题就 exit 2。你的 cron wrapper 收到非 0 退出就给你发 Telegram / Slack / ntfy.sh。

v0.2 数据源:
- **Vercel** —— 最新部署状态、24 小时内部署次数、失败部署
- **Product Hunt** —— 实时票数、评论数、launch 当天动量检查
- **Supabase advisor** —— 安全 + 性能 lint;每个 CRITICAL 单独列一条
- **OpenPanel** —— 24 小时内被追踪事件的数量(signup_completed 等);事件归零时 warn(可能 tracking regression)
- **HyperDX** —— N 小时内 error log 数量;严重等级随数量爬阶 info → warn → alert(10 / 50 阈值)

## 安装

```bash
git clone https://github.com/alex-jb/funnel-analytics-agent.git
cd funnel-analytics-agent
pip install -e .
cp .env.example .env
# 填好 VERCEL_TOKEN, PH_DEV_TOKEN 等
```

## 使用

```bash
# 一次性 brief(默认)
funnel-analytics-agent

# Brief 写到文件(比如喂 Obsidian vault)
funnel-analytics-agent --out ~/Documents/alex-brain/morning-briefs/$(date +%Y-%m-%d).md

# 实时 alert 模式 —— 有 critical 就 exit 2
funnel-analytics-agent --alert

# 只查特定数据源
funnel-analytics-agent --source vercel --source producthunt
```

### Product Hunt launch 当天 cron 配置

```cron
# 每 7 分钟跑一次 alert 模式
7,17,27,37,47,57 * * * 1 /usr/local/bin/funnel-analytics-agent --alert || curl -d "PH alert" ntfy.sh/your-topic

# 每天 7:03 AM 出 daily brief(刚好过 cap 重置时间)
3 7 * * * /usr/local/bin/funnel-analytics-agent --out ~/Documents/alex-brain/morning-briefs/$(date +\%Y-\%m-\%d).md
```

## 设计取舍

- **每个数据源独立 fail。** Vercel API 挂了?你的 brief 仍然会有 PH 数据。挂掉的源被列在 brief 末尾,但绝对不会让整个 agent 崩。
- **零外部依赖(暂时)。** 纯标准库 `urllib` —— 不用 requests / httpx / 各家 API SDK。在锁死权限的机器上 pip install 也快。
- **Markdown 优先输出。** 输出是给人在 Obsidian / VS Code 里看的,不是喂 dashboard 服务。
- **靠 exit code 配 cron,不内置推送。** v0.1 不附 Telegram/Slack 适配器 —— 你的 cron wrapper 自己处理。保持 agent 的 API 表面最小。

## Roadmap

- [x] **v0.1** —— Vercel + Product Hunt 数据源 · brief 模式 · alert 模式 · cron 友好
- [x] **v0.2** —— OpenPanel + HyperDX + Supabase advisor 数据源(5 个 source · 30 个测试)
- [x] **v0.3** —— 7 天 baseline · `delta_pct` 自动计算 · 跌幅 >50% 自动升级到 warn · 41 个测试
- [x] **v0.4** —— 推送适配器(ntfy.sh / Telegram / Slack)+ macOS launchd 安装脚本(54 个测试)
- [x] **v0.5** —— Claude 合成 brief 顶部摘要(Haiku 4.5 默认,~$0.0008/run,无 key 自动降级)
- [x] **v0.8** —— MCP server:在 Claude Desktop 里直接询问"今早 brief"或"现在告警如何"

## MCP server(Claude Desktop / Cursor / Zed)

让 AI 助手直接调用 brief / alert / 单 source 数据。

```bash
pip install 'funnel-analytics-agent[mcp]'
```

然后在 `~/Library/Application Support/Claude/claude_desktop_config.json` 加上:

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

工具:
- `get_brief(include_summary)` —— 完整 markdown 早报
- `get_alerts()` —— alert 模式输出:`All clear` 或各 source 严重度
- `get_source(name)` —— 单个 source(vercel / producthunt / openpanel / hyperdx / supabase)
- `usage_summary()` —— 本地 usage log 的 token + $ 汇总

## 协议

MIT。
