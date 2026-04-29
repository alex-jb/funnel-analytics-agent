# funnel-analytics-agent

[English](README.md) | **中文**

> 给独立开发者 launch 用的每日早晨简报 + 实时异常告警。读 Vercel + OpenPanel + HyperDX + Supabase + Product Hunt,在用户骂你之前先告诉你哪里挂了。

[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](#)

作者 [Alex Ji](https://github.com/alex-jb) — 单人独立开发者,在做 [VibeXForge](https://github.com/alex-jb/vibex)。这工具诞生于这一句话:

> *Product Hunt launch 当天我的浏览器 tab 是 Vercel + OpenPanel + HyperDX + Supabase + Product Hunt + GitHub。一圈刷下来要 1 小时。漏看 5xx 两小时 = launch 凉了。*

## 它干什么

两种模式,一个 agent:

**Brief 模式** —— 每天早晨 cron 跑一次,从所有数据源生成一份 markdown 简报,写到你 Obsidian vault 里。你喝咖啡的时候 30 秒读完。

**Alert 模式** —— launch 窗口期间每 10 分钟跑一次,发现 critical / alert 级别问题就 exit 2。你的 cron wrapper 收到非 0 退出就给你发 Telegram / Slack / ntfy.sh。

v0.1 数据源:
- **Vercel** —— 最新部署状态、24 小时内部署次数、失败部署
- **Product Hunt** —— 实时票数、评论数、launch 当天动量检查

v0.2 即将加入(这周):OpenPanel, HyperDX, Supabase advisor。

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
- [ ] **v0.2** —— OpenPanel, HyperDX, Supabase advisor 数据源
- [ ] **v0.3** —— 异常检测(z-score / 7 天基线 / 区分星期几)
- [ ] **v0.4** —— 推送适配器(Telegram / ntfy.sh / Slack)
- [ ] **v0.5** —— Claude 合成 brief —— LLM 把原始指标改写成自然语言摘要

## 协议

MIT。
