# 📡 AI Daily Digest

**每天早上 8 点，一封中文 AI 简报自动发到你的邮箱。**

自动聚合 AI 圈大新闻 + GitHub 高星新项目，用大白话说清楚"发生了什么、意味着什么"。
全程跑在 GitHub Actions 上：**免费、不需要服务器、不需要你开机或挂代理**。

> 本项目基于 [Yifannnnnnnnw/ai-dispatch](https://github.com/Yifannnnnnnnw/ai-dispatch)（MIT License）二次开发：
> 新增「⭐ GitHub 高星新项目」板块、中文直白文风、发信邮箱通用化（Outlook/Gmail/QQ 均可）。

---

## 每天收到什么

一封 HTML 邮件，六个板块：

| 板块 | 内容 |
|------|------|
| 📌 重点新闻 | 8–12 条精选，每条讲清「发生了什么 + 看点是什么」 |
| 📈 趋势分析 | 2–3 个值得注意的趋势 + 预判 |
| 🔬 值得深挖 | 2–3 篇值得精读的论文/报告 |
| 📖 今日推荐博客 | 1 篇深度好文，自动去重不重复 |
| ⭐ GitHub 高星新项目 | 近 24 小时新建、涨星快的 AI 相关仓库（独家新增） |
| 💡 今日信号 | 一句话总结今天最关键的事 |

文风：**中文、简洁直白、说人话**，给判断不给罗列。

---

## 怎么部署（约 10 分钟）

### 前置条件

- GitHub 账号（免费）
- 一个 **163 邮箱**作为发信人（需开启 SMTP 并生成授权码，见第 2 步）
- 一个收件邮箱（可以是任意邮箱，例如你常用的 Outlook）
- 一个 **Gemini API Key**（免费）— 在 <https://aistudio.google.com/apikey> 申请

### 第 1 步：把本项目放到你自己的 GitHub 上

1. 打开 <https://github.com/new>
2. 仓库名随意，比如 `ai-daily-digest`，**选 Public**
3. 点 **Create repository**
4. 把本文件夹里的所有文件推上去（git 推送，或网页上传都行）

### 第 2 步：准备发件邮箱（163 邮箱）

1. 网页登录你的 163 邮箱 → **设置 → POP3/SMTP/IMAP**
2. 开启 **SMTP 服务**（会要求短信验证，验证后**生成一串授权码**，记下来）
   > ⚠️ 授权码只显示一次。它不是你的登录密码，是给外部程序发信用的一串码。
   > 换 QQ 邮箱的话流程一样，在 QQ 邮箱「设置→账户→开启 POP3/SMTP 服务」里拿授权码。

### 第 3 步：添加密钥

打开你仓库的 **Settings → Secrets and variables → Actions → New repository secret**，添加：

| 密钥名 | 填什么 |
|--------|--------|
| `GEMINI_API_KEY` | Gemini API Key（<https://aistudio.google.com/apikey>） |
| `SMTP_USER` | 发件邮箱完整地址，如 `xxx@163.com` |
| `SMTP_PASSWORD` | 上面生成的**授权码** |
| `RECIPIENT_EMAIL` | 你的收件邮箱（如你的 Outlook 地址）；**留空 = 发给发件邮箱自己** |

### 第 4 步：验证并试收一封

仓库页面 → **Actions → ✅ 配置自检 → Run workflow**，等 1–2 分钟看结果。
全绿且收到测试邮件后，就全部完成了 🎉 每天北京时间 8:00 左右自动送达。

> 想立即手动试发一封正式的？**Actions → AI Daily Digest → Run workflow**（手动触发不受时间限制）。

---

## 稳定性设计（2026-09-24 加固）

- **模型降级链**：`gemini_model` 撞上 503（模型繁忙）/429（限流）时，自动依次尝试 `gemini_fallback_models`（两轮轮询），全部失败才放弃。可用模型清单可用「🔍 模型可用性探测」workflow 在云端实测更新。
- **失败不刷屏**：生成或发信失败时脚本以退出码 0 结束（GitHub 不会再发失败邮件），当天最多发一封"今日生成失败"提示，下一个整点 cron 自动重试。
- **重试窗口**：cron 在 **UTC 0–12 点**（北京 8:00–20:00）每 15 分钟检查一次；当天发出即停，失败则继续重试。
- **SMTP 三次重试**：163 偶发 535 风控，会间隔 20/40 秒重试 3 次。
- **网页备份**：每次生成的简报都会写入仓库 `last_digest.html`，即使邮件没发出去也能在这里看：
  <https://github.com/hfhhddhdhdh/ai-daily-digest/blob/main/last_digest.html>
- **并发锁**：同一时间只允许一个运行实例，避免多次并发登录 SMTP 被邮箱风控。

## 常见问题

**Q: 收不到邮件？**
先打开上面的 `last_digest.html` 看内容是否生成成功：有内容说明只是发信问题（多为 163 风控，重试或换发件邮箱即可）；空则跑一次「✅ 配置自检」。也检查垃圾邮件箱。GitHub Actions 定时任务偶尔延迟 15–30 分钟。

**Q: 邮件内容太少 / 新闻偏少？**
`config.yml` 里 `digest.news_target`（素材目标量）、`news_per_source`（每源条数）、`news_feeds`（源的数量）都可调大；窗口在 24h 抓不够时会自动放宽到 48h/72h。

**Q: 自检报 SMTP 失败？**
确认 `SMTP_PASSWORD` 填的是 163/QQ 邮箱的**授权码**而不是登录密码；确认已在邮箱设置里开启 SMTP 服务；163 对海外机房 IP 有风控，偶发 535 属正常，脚本会自动重试，持续失败建议换 Gmail 发件（需在 Gmail 开两步验证并生成应用密码）。

**Q: 想换发送时间？**
改 `config.yml` 里的 `send_hour_utc`：北京 8:00 = `0`，北京 7:00 = `23`（前一天），以此类推，改完推送到 GitHub 即生效。

**Q: 想换收件邮箱 / 发件邮箱？**
收件：改 `RECIPIENT_EMAIL` 密钥。发件：换 `SMTP_USER` + `SMTP_PASSWORD` 两个密钥即可；如果换了邮箱服务商（如 QQ / Gmail），还要同步改 `config.yml` 里的 `smtp` 服务器参数（163/QQ/Gmail 都是 465 + SSL）。

**Q: 怎么添加/删除新闻源？**
编辑 `config.yml` 的 `news_feeds` / `blog_feeds`：新增一行 `名称: RSS链接`，或行首加 `#` 停用。

**Q: 想换更强的模型？**
改 `config.yml`：`provider: gemini` + `digest.gemini_model`（如 `gemini-2.5-pro`）。也支持 `anthropic` / `deepseek`（需对应 API Key）。

**Q: GitHub 高星板块怎么调整？**
改 `config.yml` 的 `github` 段：`hours`（抓多少小时内新建）、`count`（每天条数）、`min_stars`（星级门槛）、`keywords`（AI 相关过滤词）。

**Q: 费用多少？**
GitHub Actions 免费；Gemini 免费额度对每天一封绰绰有余。**总成本 ¥0。**

---

## 文件说明

```
ai-daily-digest/
├── config.yml          ← 个性化配置（唯一需要编辑的文件）
├── fetch_news.py       ← 主程序：抓取 → AI 生成 → 发邮件
├── check_setup.py      ← 配置自检脚本
├── requirements.txt    ← Python 依赖
├── sent_history.json   ← 已推送记录（自动维护，防重复，勿手动改）
└── .github/workflows/
    ├── daily_news.yml  ← 每日定时任务（北京 8:00）
    └── check_setup.yml ← 一键自检
```

## License

[MIT](LICENSE)，基于 [ai-dispatch](https://github.com/Yifannnnnnnnw/ai-dispatch)（Copyright © 2025 Yifan Wang）修改。
