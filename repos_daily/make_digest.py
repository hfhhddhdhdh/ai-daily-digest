#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub 每日精选 —— 润色 + 邮件（第 2 步）

读 fetch_repos.py 产出的候选 JSON，交给 DeepSeek-V4.1-Flash 写成「小白能看懂」的中文，
自己拼 HTML 邮件（不让模型写 HTML，避免它把排版写崩），再走 SMTP 发出去。

用法：
  python make_digest.py --dry-run            # 只生成 digest.html + 打印文字版，不发信
  python make_digest.py                      # 生成 + 真发
  python make_digest.py --input today.json   # 用指定的候选文件（默认 today.json）
"""
from __future__ import annotations

import argparse
import json
import os
import re
import smtplib
import ssl
import sys
import time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import requests

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = Path(__file__).parent
MODEL = "deepseek-flash"          # 用户 2026-11-17 定：全部只用这一个
API = "https://api.deepseek.com/chat/completions"


def log(*a):
    print(*a, file=sys.stderr)


# ─────────────────────────── 调用模型 ───────────────────────────

SYSTEM = """你是一个给"零基础小白"写科技推荐的人。读者不懂编程，不知道 star、框架、SDK 是什么。

写作铁律：
1. 说人话。不许出现这些词：赋能、助力、打造、生态、闭环、范式、基础设施、一站式、开箱即用、
   高可用、分布式、全链路、AI 原生、agentic、workflow。真要用术语，后面必须用括号解释成人话。
2. 先讲"它像什么"。能用生活里的东西打比方就用（比如"像给你的手机装了个管家"）。
3. 只写你确信的事。星数、涨星数只能用我给你的数字，绝不许自己编或估算。
   尤其禁止凭空写具体数量（有多少张图、多少种功能、几年、百分之几）。
   需要说"很多"的时候就用"上千""几十种"这种模糊说法，不要精确到 1439 这种数字。
4. 不确定它具体怎么用，就不要编操作步骤，说"得按它的说明文档走"。
5. 每条要写够：4-6 句，150-220 字。写细节，不写空话。
   比如"解决什么麻烦"要给出具体场景（什么时候你会用得上），不要写"提升效率""方便快捷"。
6. "怎么用"这一栏写清楚：要不要装东西、几步、要不要注册账号、收不收费。不知道就写"得看它的说明"。
7. "要注意"这一栏写真实门槛或风险，比如需要什么环境、会不会有兼容问题、适不适合小白。
   实在没什么坑就写"没什么特别的门槛"。

判断"要不要装"的标准（给建议时必须用这三个之一）：
- 值得试：不用写代码，装完/打开就能用出效果，且跟普通人生活有关（写作、看图、视频、文件、手机电脑优化）
- 看看就好：能用但需要一点动手能力，或者只有特定场景才用得上
- 别急：要写代码、要服务器、要开发者身份，或者它明显是给程序员用的工具/库

输出必须是严格的 JSON，不要 markdown 代码块，不要任何解释文字。"""


def _prompt(repos: list[dict], videos: list[dict], date_cn: str) -> str:
    lines = []
    for i, r in enumerate(repos, 1):
        st = f"总 {r['stars']:,} 星"
        if r.get("delta"):
            unit = {"daily": "今天", "weekly": "本周", "monthly": "本月"}.get(r["delta_unit"], "近期")
            st += f"，{unit}涨 {r['delta']:,} 星"
        elif r.get("days_old"):
            st += f"，创建 {r['days_old']} 天"
        lines.append(
            f"{i}. 仓库名 {r['full_name']}\n"
            f"   官方简介（英文原文，仅供你理解，别照抄）：{r['description'] or '（无）'}\n"
            f"   数据：{st}；语言 {r.get('language')}；来源 {r.get('source')}"
        )
    repo_txt = "\n".join(lines) if lines else "（今天没有）"

    vtxt = "\n".join(
        f"{i}. 标题《{v['title']}》｜UP主 {v['author']}｜播放 {v['play']:,}｜{v['pubdate']}｜简介：{v['desc'] or '（无）'}"
        for i, v in enumerate(videos, 1)) or "（今天没有）"

    return f"""今天日期：{date_cn}

下面是今天筛选出来的 GitHub 项目（已经按热度排好序，你不要改顺序）：

{repo_txt}

下面是今天找到的相关视频：

{vtxt}

请输出这个 JSON（字段名一字不改）：
{{
  "headline": "整个邮件的一句话开场，25字以内，说今天最值得看的东西是什么，不要写'本期'",
  "repos": [
    {{
      "i": 1,
      "what": "它到底是干什么的，一句话，30字以内，像跟朋友说话",
      "pain": "它替你解决了什么具体的麻烦，给一个真实场景，50-70字",
      "how": "怎么用：装什么、几步、要不要账号、收不收费，40-60字",
      "usage": "多少人用、涨得多快，用我给的数字，一句话",
      "caveat": "要注意什么（门槛/风险/不适合谁），30-50字",
      "verdict": "值得试 / 看看就好 / 别急",
      "verdict_why": "为什么给这个判断，25字以内"
    }}
  ],
  "videos": [{{"i": 1, "why": "这条视频值得看的理由，20字以内；如果跟 GitHub 项目无关就写'与开源项目无关'"}}]
}}
repos 数组必须正好 {len(repos)} 条，videos 正好 {len(videos)} 条。不要写开场白、结尾寄语、总结陈词。"""


def call_model(prompt: str, api_key: str) -> dict:
    body = {
        "model": MODEL,
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": prompt}],
        "temperature": 0.6,
        "max_tokens": 8000,
        "response_format": {"type": "json_object"},
    }
    last = None
    for attempt in range(3):
        try:
            r = requests.post(API, headers={"Authorization": f"Bearer {api_key}",
                                            "Content-Type": "application/json"},
                              json=body, timeout=180)
            if r.status_code != 200:
                last = f"HTTP {r.status_code}: {r.text[:200]}"
                log(f"    [LLM] 第 {attempt+1} 次失败 {last}")
                time.sleep(8 * (attempt + 1))
                continue
            txt = r.json()["choices"][0]["message"]["content"]
            txt = re.sub(r"^```(?:json)?|```$", "", txt.strip(), flags=re.M).strip()
            return json.loads(txt)
        except Exception as e:
            last = f"{type(e).__name__}: {str(e)[:150]}"
            log(f"    [LLM] 第 {attempt+1} 次异常 {last}")
            time.sleep(8 * (attempt + 1))
    raise RuntimeError(f"模型调用失败：{last}")


# ─────────────────────────── 渲染 HTML ───────────────────────────

CSS = """
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Microsoft YaHei',sans-serif;
 background:#f2f2f5;margin:0;padding:20px;color:#1f2430}
.wrap{max-width:680px;margin:auto;background:#fff;border-radius:14px;overflow:hidden;
 box-shadow:0 3px 16px rgba(0,0,0,.08)}
.head{background:#101018;color:#fff;padding:26px 30px}
.head h1{margin:0;font-size:20px;letter-spacing:-.2px}
.head p{margin:8px 0 0;font-size:14px;color:#b9bcd0;line-height:1.6}
.body{padding:26px 30px}
.sec{font-weight:700;font-size:13px;letter-spacing:.06em;color:#8a8fa3;
 margin:30px 0 14px;padding-bottom:7px;border-bottom:2px solid #eee}
.card{border:1px solid #ececf2;border-left:4px solid #4f46e5;border-radius:0 10px 10px 0;
 padding:15px 18px;margin-bottom:14px;background:#fbfbfe}
.card h3{margin:0 0 4px;font-size:16px;line-height:1.45}
.card h3 a{color:#191933;text-decoration:none}
.card h3 a:hover{text-decoration:underline}
.meta{font-size:12px;color:#9aa;margin-bottom:9px;display:block}
.card p{margin:7px 0 0;font-size:14.5px;line-height:1.75;color:#39404f}
.card p b{color:#151a24}
.tag{display:inline-block;font-size:12px;padding:2px 9px;border-radius:20px;margin-top:10px}
.ok{background:#e8f7ee;color:#116b3a}
.mid{background:#fff5e6;color:#8a5a00}
.no{background:#fdecec;color:#9b1c1c}
.vid{border-left:4px solid #db2777;background:#fdf5f9;border-radius:0 10px 10px 0;
 padding:13px 17px;margin-bottom:12px}
.vid a{color:#831843;text-decoration:none;font-size:14.5px;line-height:1.6}
.vid p{margin:6px 0 0;font-size:13.5px;color:#5b4a54;line-height:1.7}
.empty{background:#f7f7fa;border-radius:10px;padding:18px;font-size:14px;color:#5c6270;line-height:1.8}
"""

VERDICT_CLASS = {"值得试": "ok", "看看就好": "mid", "别急": "no"}


def render(repos: list[dict], data: dict, videos: list[dict], date_cn: str) -> tuple[str, str]:
    head = data.get("headline", "")
    items = {int(x["i"]): x for x in data.get("repos", []) if str(x.get("i", "")).isdigit()}

    # 按「推荐程度」重排：值得试 → 看看就好 → 别急；同一档里保持原有热度顺序
    rank = {"值得试": 0, "看看就好": 1, "别急": 2}
    order = sorted(range(1, len(repos) + 1),
                   key=lambda i: (rank.get(items.get(i, {}).get("verdict", "看看就好"), 1), i))

    cards = []
    for pos, src_i in enumerate(order, 1):
        r = repos[src_i - 1]
        it = items.get(src_i, {})
        what = it.get("what") or r["description"][:40]
        pain = it.get("pain", "")
        how = it.get("how", "")
        usage = it.get("usage", "")
        caveat = it.get("caveat", "")
        verdict = it.get("verdict", "看看就好")
        vwhy = it.get("verdict_why", "")
        stat = f"⭐ {r['stars']:,}"
        if r.get("delta"):
            unit = {"daily": "今天", "weekly": "本周", "monthly": "本月"}.get(r["delta_unit"], "近期")
            stat += f"・{unit} +{r['delta']:,}"
        elif r.get("days_old"):
            stat += f"・{r['days_old']} 天新项目"
        cls = VERDICT_CLASS.get(verdict, "mid")
        rows = [f"<p><b>它是干啥的：</b>{what}</p>",
                f"<p><b>解决什么麻烦：</b>{pain}</p>"]
        if how:
            rows.append(f"<p><b>怎么用：</b>{how}</p>")
        rows.append(f"<p><b>多少人用：</b>{usage}</p>")
        if caveat:
            rows.append(f"<p><b>要注意：</b>{caveat}</p>")
        cards.append(f"""<div class="card">
  <h3>{pos}. <a href="{r['url']}">{r['full_name']}</a></h3>
  <span class="meta">{stat}・{r.get('language','')}</span>
  {''.join(rows)}
  <span class="tag {cls}">{verdict}｜{vwhy}</span>
</div>""")

    vwhy = {int(x["i"]): x.get("why", "") for x in data.get("videos", []) if str(x.get("i", "")).isdigit()}
    vcards = [f"""<div class="vid">
  <a href="{v['url']}">{v['title']}</a>
  <p>{vwhy.get(i, '')}　<span style="color:#a08">UP：{v['author']}｜播放 {v['play']:,}｜{v['pubdate']}</span></p>
</div>""" for i, v in enumerate(videos, 1)]

    body = f"""<div class="wrap">
  <div class="head"><h1>🔭 GitHub 今日精选</h1><p>{date_cn}　{head}</p></div>
  <div class="body">
    <div class="sec">今天值得看的 {len(repos)} 个 · 按推荐程度排</div>
    {''.join(cards) if cards else '<div class="empty">今天没有够格的项目。按约定：不拿小项目凑数，明天见。</div>'}
    {('<div class="sec">📺 顺便看到有人讲</div>' + ''.join(vcards)) if vcards else ''}
  </div>
</div>"""

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>{CSS}</style></head><body>{body}</body></html>"""

    plain = head + "\n\n" + "\n\n".join(
        f"{pos}. {repos[src_i-1]['full_name']}（{repos[src_i-1]['stars']:,} 星）· "
        f"{items.get(src_i, {}).get('verdict', '')}\n"
        f"   干啥的：{items.get(src_i, {}).get('what','')}\n"
        f"   解决：{items.get(src_i, {}).get('pain','')}\n"
        f"   怎么用：{items.get(src_i, {}).get('how','')}\n"
        f"   多少人用：{items.get(src_i, {}).get('usage','')}\n"
        f"   要注意：{items.get(src_i, {}).get('caveat','')}\n"
        f"   {repos[src_i-1]['url']}" for pos, src_i in enumerate(order, 1))
    return html, plain


# ─────────────────────────── 发信 ───────────────────────────

def senders() -> list[dict]:
    out = []
    if os.environ.get("SMTP_USER") and os.environ.get("SMTP_PASSWORD"):
        out.append({"name": "163 主通道", "host": "smtp.163.com", "port": 465, "ssl": True,
                    "user": os.environ["SMTP_USER"], "pwd": os.environ["SMTP_PASSWORD"]})
    if os.environ.get("SMTP2_USER") and os.environ.get("SMTP2_PASSWORD"):
        h2 = os.environ.get("SMTP2_HOST", "smtp.gmail.com")
        out.append({"name": "Gmail 备用", "host": h2, "port": int(os.environ.get("SMTP2_PORT", 465)),
                    "ssl": True, "user": os.environ["SMTP2_USER"],
                    "pwd": os.environ["SMTP2_PASSWORD"]})
    return out


def send(html: str, subject: str) -> None:
    ss = senders()
    if not ss:
        raise RuntimeError("没有任何发信通道（缺 SMTP_USER / SMTP_PASSWORD）")
    to = os.environ.get("RECIPIENT_EMAIL") or ss[0]["user"]
    errs = []
    for s in ss:
        msg = MIMEMultipart("alternative")
        msg["Subject"], msg["From"], msg["To"] = subject, s["user"], to
        msg.attach(MIMEText(html, "html", "utf-8"))
        for attempt in range(2):
            try:
                if s["ssl"]:
                    with smtplib.SMTP_SSL(s["host"], s["port"], timeout=60) as srv:
                        srv.login(s["user"], s["pwd"])
                        srv.sendmail(s["user"], to, msg.as_string())
                else:
                    with smtplib.SMTP(s["host"], s["port"], timeout=60) as srv:
                        srv.ehlo()
                        srv.starttls(context=ssl.create_default_context())
                        srv.login(s["user"], s["pwd"])
                        srv.sendmail(s["user"], to, msg.as_string())
                log(f"    ✅ 已发送 → {to}（{s['name']}）")
                return
            except Exception as e:
                errs.append(f"{s['name']}: {str(e)[:110]}")
                log(f"    [smtp][{s['name']}] 第 {attempt+1} 次失败：{str(e)[:110]}")
                if attempt == 0:
                    time.sleep(12)
    raise RuntimeError("所有通道都失败：" + " | ".join(errs))


# ─────────────────────────── 主流程 ───────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="today.json")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    src = Path(args.input)
    if not src.is_absolute() and not src.exists():
        src = HERE / args.input
    if not src.exists():
        log(f"找不到候选文件 {src}，先跑 fetch_repos.py --json {args.input}")
        return 2
    data_in = json.loads(src.read_text(encoding="utf-8"))
    repos, videos = data_in.get("repos", []), data_in.get("videos", [])
    # 视频区默认关闭（用户 2026-11-17：B 站抓出来的多是网盘/背单词这类，跟仓库无关，算废话）
    # 想开：workflow 里加环境变量 SHOW_VIDEO=1，或者本地 SHOW_VIDEO=1 python make_digest.py
    if os.environ.get("SHOW_VIDEO") != "1":
        videos = []
    if not repos and not videos:
        log("候选为空，今天不发信")
        return 0

    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        log("缺 DEEPSEEK_API_KEY")
        return 2

    date_cn = datetime.now().strftime("%Y 年 %m 月 %d 日")
    log(f"[1/3] 让 {MODEL} 写 {len(repos)} 条项目 + {len(videos)} 条视频 …")
    digest = call_model(_prompt(repos, videos, date_cn), key)

    log("[2/3] 渲染邮件 …")
    html, plain = render(repos, digest, videos, date_cn)
    (HERE / "digest.html").write_text(html, encoding="utf-8")

    print("\n" + "=" * 60)
    print(f"主题：🔭 GitHub 今日精选 · {datetime.now().strftime('%m-%d')}")
    print("=" * 60)
    print(plain)
    if videos:
        print("\n【视频】")
        for i, v in enumerate(videos, 1):
            why = next((x.get("why", "") for x in digest.get("videos", [])
                        if str(x.get("i")) == str(i)), "")
            print(f"  {i}. {v['title']}（UP {v['author']}，播放 {v['play']:,}）")
            print(f"     {why}\n     {v['url']}")
    print("=" * 60 + "\n")

    if args.dry_run:
        log("[3/3] --dry-run：不发信。HTML 已存 digest.html")
        return 0

    log("[3/3] 发信 …")
    send(html, f"🔭 GitHub 今日精选 · {datetime.now().strftime('%m-%d')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
