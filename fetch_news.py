"""
AI Daily Digest — 每日 AI 简报主程序
基于 ai-dispatch (github.com/Yifannnnnnnnw/ai-dispatch, MIT) 定制：
  + 新增「⭐ GitHub 高星新项目」板块（GitHub Search API）
  + 中文直白文风
  + 发信邮箱通用化（Outlook / Gmail / QQ 均可）
  + 支持 gemini / anthropic / deepseek 三种 LLM
"""

import feedparser
import smtplib
import json
import os
import re
import ssl
import sys
import yaml
import requests
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone
from pathlib import Path

HISTORY_PATH = Path(__file__).parent / "sent_history.json"
HISTORY_MAX = 2000  # 最多保留最近 2000 条，防止文件无限增长


def load_config() -> dict:
    path = Path(__file__).parent / "config.yml"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_history() -> dict:
    if HISTORY_PATH.exists():
        return json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    return {"urls": [], "last_sent_date": ""}


def save_history(history: dict, new_urls) -> None:
    """把本次已推送的链接写入历史。new_urls 可以是单个字符串或字符串列表。"""
    urls = set(history.get("urls", []))
    if isinstance(new_urls, str):
        new_urls = [new_urls]
    for u in (new_urls or []):
        if u:
            urls.add(u)
    updated = list(urls)
    if len(updated) > HISTORY_MAX:
        updated = updated[-HISTORY_MAX:]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    HISTORY_PATH.write_text(
        json.dumps({"urls": updated, "last_sent_date": today}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def extract_recommended_url(html: str) -> str | None:
    """从 AI 输出的 HTML 中提取「今日推荐博客」块里的链接（用于去重）。"""
    match = re.search(r'<div class="blog-pick">.*?<a href="([^"]+)"', html, re.DOTALL)
    return match.group(1) if match else None


# ─────────────────────────── 抓取 RSS 新闻 / 博客 ───────────────────────────

def _fetch_feeds(feeds: dict, hours: int, per_source: int,
                 arxiv_keywords: list[str]) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    articles = []

    for source, url in feeds.items():
        try:
            feed = feedparser.parse(url, request_headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
            })
            for entry in feed.entries[:per_source]:
                published = None
                for attr in ("published_parsed", "updated_parsed"):
                    t = getattr(entry, attr, None)
                    if t:
                        published = datetime(*t[:6], tzinfo=timezone.utc)
                        break

                if published and published < cutoff:
                    continue

                title = entry.get("title", "")
                summary = entry.get("summary", "")
                text = (title + " " + summary).lower()

                if source.lower().startswith("arxiv") and not any(kw in text for kw in arxiv_keywords):
                    continue

                articles.append({
                    "source": source,
                    "title": title,
                    "url": entry.get("link", ""),
                    "summary": summary[:1000] if summary else "",
                    "published": published.strftime("%Y-%m-%d %H:%M UTC") if published else "Unknown",
                })
        except Exception as e:
            print(f"[WARN] {source}: {e}", file=sys.stderr)

    return articles


def fetch_recent_articles(cfg: dict) -> list[dict]:
    d = cfg["digest"]
    return _fetch_feeds(
        cfg["news_feeds"], d["news_hours"], d["news_per_source"], cfg["arxiv_keywords"]
    )


def fetch_blog_candidates(cfg: dict, history: set[str]) -> list[dict]:
    """抓取近 blog_days 天的博客文章 + 经典列表，过滤已推送过的。"""
    d = cfg["digest"]
    blog_hours = d["blog_days"] * 24

    rss_blogs = _fetch_feeds(
        cfg["blog_feeds"], blog_hours, d["blog_per_source"], cfg["arxiv_keywords"]
    )

    classics = [
        {
            "source": f"{c.get('type', 'classic').title()} · {c.get('author', '')}",
            "title": c["title"],
            "url": c["url"],
            "summary": c.get("note", ""),
            "published": str(c.get("year", "经典")),
        }
        for c in (cfg.get("classics") or [])
    ]

    all_candidates = rss_blogs + classics
    return [a for a in all_candidates if a["url"] not in history]


# ─────────────────────────── ⭐ 抓取 GitHub 高星新项目 ───────────────────────────

def _github_search(query: str, per_page: int, headers: dict) -> list[dict]:
    resp = requests.get(
        "https://api.github.com/search/repositories",
        params={"q": query, "sort": "stars", "order": "desc", "per_page": per_page},
        headers=headers, timeout=20,
    )
    resp.raise_for_status()
    return resp.json().get("items", [])


def fetch_github_trending(cfg: dict) -> list[dict]:
    """抓最近 N 小时新建、星数够高的仓库，用关键词过滤出 AI 相关的。"""
    gh = cfg.get("github") or {}
    if not gh.get("enabled", True):
        return []

    keywords = [str(k).lower() for k in gh.get("keywords", [])]
    hours = int(gh.get("hours", 24))
    count = int(gh.get("count", 8))
    candidates = int(gh.get("candidates", 50))
    min_stars = int(gh.get("min_stars", 20))

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "ai-daily-digest (GitHub Actions)",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    def _search_created_after(dt: datetime) -> list[dict]:
        since = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        query = f"created:>{since} stars:>={min_stars}"
        return _github_search(query, min(candidates, 100), headers)

    items = []
    try:
        items = _search_created_after(datetime.now(timezone.utc) - timedelta(hours=hours))
    except Exception as e:
        print(f"[WARN] GitHub 24h 搜索失败（{e}），回退到近 7 天…", file=sys.stderr)
        try:
            items = _search_created_after(datetime.now(timezone.utc) - timedelta(days=7))
        except Exception as e2:
            print(f"[WARN] GitHub 搜索也失败: {e2}", file=sys.stderr)
            return []

    def _is_ai(item: dict) -> bool:
        hay = " ".join([
            item.get("full_name", ""),
            item.get("description") or "",
            " ".join(item.get("topics") or []),
        ]).lower()
        return any(k in hay for k in keywords)

    ai_items = [i for i in items if _is_ai(i)]
    pool = ai_items if ai_items else items  # 实在没有 AI 相关的就用最热的兜底

    repos = []
    for item in pool:
        if len(repos) >= count:
            break
        desc = (item.get("description") or "").strip()[:280]
        repos.append({
            "full_name": item.get("full_name", ""),
            "url": item.get("html_url", ""),
            "stars": item.get("stargazers_count", 0),
            "language": item.get("language") or "—",
            "description": desc or "（暂无简介）",
        })

    print(f"GitHub: 候选 {len(items)} 个 | AI 相关 {len(ai_items)} 个 | 选用 {len(repos)} 个")
    return repos


# ─────────────────────────── AI 生成简报 ───────────────────────────

def summarize(articles: list[dict], blog_candidates: list[dict],
              repos: list[dict], cfg: dict) -> str:
    provider = cfg.get("provider", "gemini")
    d = cfg["digest"]
    topics_str = "、".join(cfg["topics"])
    lang = d.get("output_language", "中文")

    articles_text = "\n\n---\n\n".join(
        f"[{a['source']}] ({a['published']})\n标题: {a['title']}\n链接: {a['url']}\n摘要: {a['summary']}"
        for a in articles
    )
    blogs_text = "\n\n---\n\n".join(
        f"[{b['source']}] ({b['published']})\n标题: {b['title']}\n链接: {b['url']}\n简介: {b['summary']}"
        for b in blog_candidates
    ) if blog_candidates else "（暂无候选，所有文章均已推送过）"

    repos_text = "\n\n---\n\n".join(
        f"{r['full_name']} | ⭐{r['stars']} | {r['language']}\n链接: {r['url']}\n简介: {r['description']}"
        for r in repos
    ) if repos else "（今天没有抓到大体量的 AI 新项目，这一板块可简单说明后跳过）"

    today = datetime.now().strftime("%Y年%m月%d日")

    if repos:
        gh_pick_guide = (f"从【GitHub 高星新项目】里挑值得关注的"
                         f"（最多 {len(repos)} 个，可少给，宁缺毋滥），"
                         f"每个：一句话这项目是干嘛的 + 一句话为什么值得关注。")
        gh_html_guide = """
<div class="section-title">⭐ GitHub 高星新项目</div>
<div class="repo">
  <h3><a href="URL">owner/repo</a></h3>
  <span class="meta">⭐ 星数 · 语言</span>
  <p><strong>是什么：</strong>……</p>
  <p><strong>为什么值得看：</strong>……</p>
</div>"""
    else:
        gh_pick_guide = "今天没有抓到值得单独推荐的新项目，直接跳过这一板块，不要编造。"
        gh_html_guide = ""

    prompt = f"""你是「AI Daily Digest」的主编，为一个关心 AI 动态的中文读者写每日简报。
读者不是研究者，是圈内关注者：需要知道发生了什么、意味着什么，用大白话讲清楚，不要堆术语。
用户重点关注方向：{topics_str}。
所有内容用{lang}输出。

【文风硬性要求】
1. 中文、简洁直白、说人话，像靠谱朋友给你划重点。
2. 每条给出判断，不要罗列、不要空话套话；非用术语就顺带一句人话解释。
3. 标题要具体、抓重点，不标题党。

【新闻资讯】过去 {d['news_hours']} 小时共 {len(articles)} 条：

{articles_text}

【博客/经典文章候选池】共 {len(blog_candidates)} 篇（近期博客、经典文章、访谈等，均未推送过）：

{blogs_text}

【GitHub 高星新项目】共 {len(repos)} 个（均为最近新建且星数增长快的仓库，含 AI 相关候选）：

{repos_text}

请按以下六个部分组织内容，严格输出 HTML（不要 markdown 代码块、不要 ```html 标记、不要任何前言后语）：

第一部分：📌 重点新闻（8-12 条，选最重要最有信息量的，优先与你关注方向相关的）
每条包含：「事件」1 句讲清楚发生了什么；「看点」1-2 句说清为什么值得关注、影响是什么（有判断，说人话）；有关联就补一句「关联」。
宁缺毋滥，没什么含金量的不要硬凑。

第二部分：📈 趋势分析
2-3 个值得注意的趋势，每个：现状证据 + 一句话预判，简洁。

第三部分：🔬 值得深挖
2-3 篇值得精读的论文/报告（优先 arXiv），每篇说明核心贡献 + 值得关注的点。

第四部分：📖 今日推荐博客
从候选池挑 1 篇最值得读的，给：为什么今天推荐它 + 3 个核心观点（bullet）+ 适合谁 + 大概阅读时间。

第五部分：⭐ GitHub 高星新项目
{gh_pick_guide}

第六部分：💡 今日信号
今天最重要的一条判断/一句话，不超过 60 字。

HTML 模板如下（样式 class 必须原样保留，内容替换为你写的）：
<h2>📡 AI Daily Digest · {today}</h2>
<p class="intro">新闻 {len(articles)} 条 · 新项目 {len(repos)} 个 · 聚焦 {topics_str}</p>

<div class="section-title">📌 重点新闻</div>
<div class="item">
  <h3><a href="URL">标题</a></h3>
  <span class="meta">来源：XXX · 时间</span>
  <p><strong>事件：</strong>……</p>
  <p><strong>看点：</strong>……</p>
  <p class="tag">关联：……</p>
</div>

<div class="section-title">📈 趋势分析</div>
<div class="trend">
  <h3>趋势名称</h3>
  <p>……</p>
</div>

<div class="section-title">🔬 值得深挖</div>
<div class="deep-read">
  <h3><a href="URL">论文/报告标题</a></h3>
  <p>……</p>
</div>

<div class="section-title">📖 今日推荐博客</div>
<div class="blog-pick">
  <h3><a href="URL">文章标题</a></h3>
  <span class="meta">作者/来源 · 时间</span>
  <p class="blog-why">……为什么值得读……</p>
  <ul>
    <li>核心观点一</li>
    <li>核心观点二</li>
    <li>核心观点三</li>
  </ul>
  <p class="blog-audience">适合：…… · 阅读时间：约 XX 分钟</p>
</div>

{gh_html_guide}

<div class="closing"><strong>今日信号：</strong>……</div>"""

    if provider == "gemini":
        from google import genai as google_genai
        from google.genai import types as genai_types
        model = d.get("gemini_model", "gemini-2.0-flash")
        client = google_genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=genai_types.GenerateContentConfig(max_output_tokens=d["max_tokens"]),
        )
        text = response.text
        if not text:
            finish = (response.candidates[0].finish_reason if response.candidates else "no candidates")
            raise RuntimeError(f"Gemini 返回空内容 (finish_reason={finish})")
        return text

    if provider == "anthropic":
        import anthropic
        model = d.get("anthropic_model", "claude-sonnet-4-6")
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        msg = client.messages.create(
            model=model, max_tokens=d["max_tokens"],
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text

    # deepseek（OpenAI 兼容接口）
    if provider == "deepseek":
        key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not key:
            raise RuntimeError("provider=deepseek 但缺少 DEEPSEEK_API_KEY 环境变量")
        resp = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": d.get("deepseek_model", "deepseek-chat"),
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": d["max_tokens"],
            },
            timeout=180,
        )
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"].strip()
        if not text:
            raise RuntimeError("DeepSeek 返回空内容")
        return text

    raise RuntimeError(f"未知 provider: {provider}")


# ─────────────────────────── 发送邮件 ───────────────────────────

EMAIL_CSS = """
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Microsoft YaHei', sans-serif;
       background: #f0f0f5; margin: 0; padding: 20px; color: #222; }
.wrapper { max-width: 700px; margin: auto; background: #fff;
           border-radius: 10px; overflow: hidden;
           box-shadow: 0 2px 12px rgba(0,0,0,.10); }
.header { background: #0f0f1a; color: #fff; padding: 28px 36px; }
.header h1 { margin: 0; font-size: 22px; letter-spacing: -.3px; }
.body { padding: 28px 36px; }
h2 { color: #0f0f1a; margin-top: 0; font-size: 20px; }
.intro { color: #666; font-size: 13px; margin-bottom: 28px; }
.section-title { font-weight: 700; font-size: 11px; text-transform: uppercase;
                 letter-spacing: .1em; color: #999; margin: 32px 0 14px;
                 padding-bottom: 6px; border-bottom: 1px solid #eee; }
.item { border-left: 3px solid #4f46e5; padding: 14px 18px;
        margin-bottom: 18px; background: #fafafa; border-radius: 0 8px 8px 0; }
.item h3 { margin: 0 0 4px; font-size: 15px; line-height: 1.4; }
.item h3 a { color: #1a1a2e; text-decoration: none; }
.item h3 a:hover { text-decoration: underline; }
.meta { font-size: 11px; color: #aaa; display: block; margin-bottom: 8px; }
.item p { margin: 6px 0 0; font-size: 14px; line-height: 1.7; color: #444; }
.item p.tag { font-size: 12px; color: #7c6fcd; margin-top: 8px; }
.trend { border-left: 3px solid #059669; padding: 14px 18px;
         margin-bottom: 18px; background: #f0fdf4; border-radius: 0 8px 8px 0; }
.trend h3 { margin: 0 0 8px; font-size: 15px; color: #065f46; }
.trend p { margin: 0; font-size: 14px; line-height: 1.7; color: #444; }
.deep-read { border-left: 3px solid #d97706; padding: 14px 18px;
             margin-bottom: 18px; background: #fffbeb; border-radius: 0 8px 8px 0; }
.deep-read h3 { margin: 0 0 8px; font-size: 15px; }
.deep-read h3 a { color: #92400e; text-decoration: none; }
.deep-read p { margin: 0; font-size: 14px; line-height: 1.7; color: #444; }
.blog-pick { border-left: 3px solid #db2777; padding: 14px 18px;
             margin-bottom: 18px; background: #fdf2f8; border-radius: 0 8px 8px 0; }
.blog-pick h3 { margin: 0 0 4px; font-size: 15px; }
.blog-pick h3 a { color: #831843; text-decoration: none; }
.blog-why { margin: 10px 0 8px; font-size: 14px; line-height: 1.7; color: #444; }
.blog-pick ul { margin: 8px 0; padding-left: 20px; font-size: 14px; line-height: 1.8; color: #444; }
.blog-audience { font-size: 12px; color: #9d174d; margin: 8px 0 0; }
.repo { border-left: 3px solid #0ea5e9; padding: 14px 18px;
        margin-bottom: 18px; background: #f0f9ff; border-radius: 0 8px 8px 0; }
.repo h3 { margin: 0 0 4px; font-size: 15px; }
.repo h3 a { color: #075985; text-decoration: none; }
.repo p { margin: 6px 0 0; font-size: 14px; line-height: 1.7; color: #444; }
.closing { background: #1a1a2e; color: #e0e0ff; border-radius: 8px;
           padding: 16px 20px; margin-top: 28px; font-size: 14px; line-height: 1.6; }
.closing strong { color: #fff; }
.footer { padding: 16px 36px; font-size: 12px; color: #bbb;
          border-top: 1px solid #eee; text-align: center; }
"""


def send_email(html_body: str, cfg: dict) -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    subject = f"📡 AI Daily Digest · {today}"

    full_html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>{EMAIL_CSS}</style>
</head>
<body>
<div class="wrapper">
  <div class="header"><h1>📡 AI Daily Digest</h1></div>
  <div class="body">{html_body}</div>
  <div class="footer">AI Daily Digest · Gemini + GitHub Actions · 每天早上自动发送</div>
</div>
</body></html>"""

    smtp_cfg = cfg.get("smtp") or {}
    host = smtp_cfg.get("host", "smtp-mail.outlook.com")
    port = int(smtp_cfg.get("port", 587))
    use_ssl = bool(smtp_cfg.get("ssl", False))

    sender = os.environ["SMTP_USER"]
    password = os.environ["SMTP_PASSWORD"]
    recipient = os.environ.get("RECIPIENT_EMAIL") or sender

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.attach(MIMEText(full_html, "html", "utf-8"))

    if use_ssl:
        with smtplib.SMTP_SSL(host, port, timeout=60) as server:
            server.login(sender, password)
            server.sendmail(sender, recipient, msg.as_string())
    else:
        with smtplib.SMTP(host, port, timeout=60) as server:
            server.ehlo()
            server.starttls(context=ssl.create_default_context())
            server.ehlo()
            server.login(sender, password)
            server.sendmail(sender, recipient, msg.as_string())


# ─────────────────────────── 主流程 ───────────────────────────

if __name__ == "__main__":
    cfg = load_config()
    history = load_history()
    sent_urls = set(history.get("urls", []))

    print("1/4 抓取新闻...")
    articles = fetch_recent_articles(cfg)
    print(f"    新闻 {len(articles)} 条")

    print("2/4 抓取博客/经典候选...")
    blog_candidates = fetch_blog_candidates(cfg, sent_urls)
    print(f"    候选 {len(blog_candidates)} 篇")

    print("3/4 抓取 GitHub 高星新项目...")
    repos = fetch_github_trending(cfg)
    print(f"    {len(repos)} 个")

    if not articles and not blog_candidates and not repos:
        print("今天没有抓到任何内容，跳过发送。")
        sys.exit(0)

    provider = cfg.get("provider", "gemini")
    print(f"4/4 用 {provider} 生成简报...")
    summary = summarize(articles, blog_candidates, repos, cfg)

    print("发送邮件...")
    send_email(summary, cfg)

    # 记录已推送链接（推荐博客 + GitHub 新项目），避免重复
    new_urls = []
    recommended = extract_recommended_url(summary)
    if recommended:
        new_urls.append(recommended)
    new_urls += [r["url"] for r in repos]
    save_history(history, new_urls)

    print(f"完成！已发送并记录 {len(new_urls)} 条链接。")
