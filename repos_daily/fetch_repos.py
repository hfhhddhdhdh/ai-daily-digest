#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub 每日精选 —— 取数层（第 1 步：只负责抓 + 筛，不润色、不发信）

三路数据：
  1. GitHub Trending 日榜 / 周榜  —— 页面自带「今天/本周涨了多少星」，真实数字
  2. GitHub Search              —— 新建就爆的项目（7 天 / 30 天通道）
  3. B 站搜索                    —— 「GitHub 好项目」类视频（需先访问主页拿 buvid3 cookie，否则 412）

用法：
  python fetch_repos.py                    # 打印今天的候选清单
  python fetch_repos.py --json out.json    # 另存 JSON 给润色脚本
  python fetch_repos.py --no-history       # 调试：忽略去重记录
  python fetch_repos.py --offline          # 调试：改用本地 trending_*.html
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import requests

for _s in (sys.stdout, sys.stderr):      # Windows 控制台默认 GBK，emoji 会直接崩
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = Path(__file__).parent
HISTORY_PATH = HERE / "sent_repos.json"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

CFG = {
    # ── 门槛 ──────────────────────────────────────────────────────────
    "min_total_stars": 3000,     # 总星低于这个不要（用户：小仓库别推）
    "min_week_heat": 300,        # 折算成「一周涨 300 星」以下不要
    "max_items": 10,
    "history_days": 30,          # 推过之后 30 天内不重复
    # 新仓库爆发通道
    "newborn_days": 30,
    "newborn_stars": 1000,
    # ── 视频 ──────────────────────────────────────────────────────────
    "video_keywords": ["GitHub 开源项目", "GitHub 好项目"],
    "video_days": 45,
    "video_max": 3,
    "video_min_play": 3000,
}


def log(*a):
    print(*a, file=sys.stderr)


# ─────────────────────────── HTTP ───────────────────────────

_session = requests.Session()
_session.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})


def http_get(url, *, headers=None, params=None, retries=3, timeout=30,
             session=None, ok_codes=(200,)):
    s = session or _session
    for i in range(retries):
        try:
            r = s.get(url, headers=headers, params=params, timeout=timeout)
            if r.status_code in ok_codes:
                return r
            log(f"    [http {r.status_code}] {url}")
            time.sleep(5 * (i + 1) if r.status_code in (403, 412, 429) else 3 * (i + 1))
        except Exception as e:
            log(f"    [http err {i+1}/{retries}] {type(e).__name__}: {str(e)[:110]}")
            time.sleep(4 * (i + 1))
    return None


def strip_html(x: str) -> str:
    x = re.sub(r"<script.*?</script>", " ", x, flags=re.S)
    x = re.sub(r"<svg.*?</svg>", " ", x, flags=re.S)
    x = re.sub(r"<[^>]+>", " ", x)
    for a, b in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                 ("&quot;", '"'), ("&#39;", "'"), ("&nbsp;", " ")):
        x = x.replace(a, b)
    return re.sub(r"\s+", " ", x).strip()


# ─────────────────────────── 1. Trending ───────────────────────────

STATS_RE = re.compile(
    r"(?:([A-Za-z0-9#+.\-]{1,20})\s+)?([\d,]+)\s+([\d,]+)\s+Built by\s+([\d,]+)\s+stars?\s+"
    r"(?:this\s+)?(today|week|month)", re.I)
NAME_RE = re.compile(r"Star\s+([A-Za-z0-9_.\-]+)\s*/\s*([A-Za-z0-9_.\-]+)")


def _parse_trending(html: str, since: str) -> list[dict]:
    out = []
    for block in html.split('<article class="Box-row"')[1:]:
        t = strip_html(block)
        mn, ms = NAME_RE.search(t), STATS_RE.search(t)
        if not mn or not ms:
            continue
        name = f"{mn.group(1)}/{mn.group(2)}"
        lang = (ms.group(1) or "").strip()
        stars, forks = int(ms.group(2).replace(",", "")), int(ms.group(3).replace(",", ""))
        delta = int(ms.group(4).replace(",", ""))
        unit = {"today": "daily", "week": "weekly", "month": "monthly"}[ms.group(5).lower()]
        desc = t[mn.end():ms.start()].strip(" -·|")
        out.append({"full_name": name, "url": f"https://github.com/{name}",
                    "description": desc, "language": lang or "—",
                    "stars": stars, "forks": forks, "delta": delta,
                    "delta_unit": unit, "source": f"trending/{since}", "days_old": None})
    return out


def fetch_trending(since: str, spoken: str | None = None, offline: bool = False) -> list[dict]:
    """抓 GitHub Trending。since: daily|weekly|monthly；spoken: 语言过滤（zh=中文项目）"""
    tag = since + (f"/{spoken}" if spoken else "")
    url = f"https://github.com/trending?since={since}"
    if spoken:
        url += f"&spoken_language_code={spoken}"
    if offline:
        p = HERE / f"trending_{tag.replace('/', '-')}.html"
        if not p.exists():
            log(f"  [trending/{tag}] 本地文件不存在")
            return []
        out = _parse_trending(p.read_text(encoding="utf-8"), tag)
    else:
        r = http_get(url, retries=4, timeout=45)
        if not r:
            log(f"  [trending/{tag}] 抓取失败")
            return []
        out = _parse_trending(r.text, tag)
    log(f"  [trending/{tag}] {len(out)} 个（带真实涨星数："
        f"{sum(1 for x in out if x['delta'] > 0)}）")
    return out


# ─────────────────────────── 2. 新仓库爆发 ───────────────────────────

def fetch_newborns() -> list[dict]:
    now = datetime.now(timezone.utc)
    headers = {"Accept": "application/vnd.github+json"}
    if os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"

    out, seen = [], set()
    for label, days, floor in (("7天新建", 7, 500),
                               (f"{CFG['newborn_days']}天新建", CFG["newborn_days"], CFG["newborn_stars"])):
        since = (now - timedelta(days=days)).strftime("%Y-%m-%d")
        r = http_get("https://api.github.com/search/repositories", headers=headers,
                     params={"q": f"created:>{since} stars:>={floor}",
                             "sort": "stars", "order": "desc", "per_page": 30})
        if not r:
            continue
        try:
            items = r.json().get("items", [])
        except Exception:
            items = []
        for it in items:
            fn = it.get("full_name", "")
            if not fn or fn in seen:
                continue
            seen.add(fn)
            created = it.get("created_at", "")
            days_old = None
            if created:
                try:
                    d = datetime.strptime(created, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                    days_old = max(1, (now - d).days)
                except Exception:
                    pass
            out.append({
                "full_name": fn, "url": it.get("html_url", ""),
                "description": (it.get("description") or "").strip(),
                "language": it.get("language") or "—",
                "stars": it.get("stargazers_count", 0),
                "forks": it.get("forks_count", 0),
                "delta": 0, "delta_unit": "newborn",
                "created_at": created, "days_old": days_old,
                "topics": it.get("topics") or [], "source": label,
            })
        log(f"  [newborn/{label}] {len(items)} 个")
    return out


# ─────────────────────────── 3. B 站视频 ───────────────────────────

def _bili_session() -> requests.Session:
    """必须先访问主页拿 buvid3 cookie，否则搜索接口 412。"""
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"})
    try:
        s.get("https://www.bilibili.com/", timeout=25)
    except Exception as e:
        log(f"    [bili] 预热失败：{type(e).__name__}")
    return s


def _video_relevant(v: dict) -> bool:
    """B 站搜索是模糊匹配，会混进游戏/抽卡/搬运视频，必须过一遍相关性。"""
    hay = (v.get("title", "") + " " + v.get("desc", "")).lower()
    junk = ("代肝", "抽卡", "原神", "崩坏", "王者荣耀", "代练", "私服", "加速器")
    if any(j in hay for j in junk):
        return False
    strong = ("github", "开源项目", "开源 项目", "开源的", "star", "仓库", "up主自荐")
    return any(k in hay for k in strong)


def fetch_bilibili() -> list[dict]:
    s = _bili_session()
    out, seen = [], set()
    cutoff = time.time() - CFG["video_days"] * 86400
    for kw in CFG["video_keywords"]:
        ref = "https://search.bilibili.com/all?keyword=" + quote(kw)
        r = http_get("https://api.bilibili.com/x/web-interface/search/type",
                     headers={"Referer": ref, "Origin": "https://search.bilibili.com"},
                     params={"search_type": "video", "keyword": kw,
                             "order": "pubdate", "page": 1},
                     session=s, retries=3, timeout=25)
        if not r:
            log(f"    [bili] 「{kw}」抓取失败")
            continue
        try:
            d = r.json()
        except Exception:
            continue
        if d.get("code") != 0:
            log(f"    [bili] 「{kw}」code={d.get('code')} {d.get('message')}")
            continue
        for v in (d.get("data") or {}).get("result") or []:
            bvid, pub = v.get("bvid"), v.get("pubdate") or 0
            if not bvid or bvid in seen or pub < cutoff:
                continue
            seen.add(bvid)
            out.append({
                "bvid": bvid,
                "title": strip_html(v.get("title", "")),
                "author": v.get("author", ""),
                "play": v.get("play", 0),
                "pubdate": datetime.fromtimestamp(pub).strftime("%Y-%m-%d"),
                "desc": strip_html(v.get("description", ""))[:180],
                "url": f"https://www.bilibili.com/video/{bvid}",
            })
        time.sleep(2)
    out = [v for v in out if v["play"] >= CFG["video_min_play"] and _video_relevant(v)]
    out.sort(key=lambda v: v["play"], reverse=True)
    log(f"  [bilibili] 相关性+播放量过滤后 {len(out)} 个")
    return out[: CFG["video_max"] * 3]


# ─────────────────────────── 合并 / 门槛 / 排序 ───────────────────────────

def weekly_heat(r: dict) -> float:
    """统一折算成「一周涨多少星」，让日榜/周榜/新仓库能放在一起比。"""
    u, d = r.get("delta_unit"), r.get("delta", 0)
    if u == "daily":
        return d * 5
    if u == "weekly":
        return float(d)
    if u == "monthly":
        return d / 4.3
    if u == "newborn":
        days = r.get("days_old") or CFG["newborn_days"]
        return r.get("stars", 0) * 7 / max(days, 3)
    return 0.0


HOT_KW = ("下载", "播放器", "输入法", "翻译", "字幕", "截图", "图片", "视频", "压缩", "网盘",
          "笔记", "阅读", "音乐", "电视", "安卓", "手机", "客户端", "桌面", "文档", "表格",
          "download", "player", "wallpaper", "screenshot", "subtitle", "translate", "convert",
          "editor", "reader", "music", "video", "image", "photo", "pdf", "note", "clipboard")
DEV_KW = ("sdk", "library", "framework", "protocol", "embedding", "kernel", "compiler",
          "runtime", "mcp", "agent", "skill", "plugin for", "api client", "orm", "linter")
GOOD_TOPICS = ("awesome", "self-hosted", "tool", "tools", "utility", "gui", "windows",
               "android", "desktop", "video", "image", "downloader", "productivity")


def usability(r: dict) -> int:
    """猜「普通人装完就能用」的程度。纯规则，不问模型，省钱又快。"""
    hay = " ".join([r.get("description", ""), " ".join(r.get("topics") or [])]).lower()
    score = 0
    score += sum(2 for k in HOT_KW if k in hay)
    score -= sum(2 for k in DEV_KW if k in hay)
    score += sum(1 for t in GOOD_TOPICS if t in (r.get("topics") or []))
    if re.search(r"[\u4e00-\u9fa5]", r.get("description", "")):
        score += 3          # 有中文简介，说明作者面向中文用户
    if r.get("stars", 0) >= 20000:
        score += 2
    if r.get("delta_unit") == "newborn":
        score -= 1          # 太新的项目通常还没做完善
    return score


def merge(repo_lists: list[list[dict]]) -> list[dict]:
    """同一仓库可能同时出现在日榜/周榜/搜索：合并，涨星取最大，总星取最大。"""
    order = {"daily": 4, "weekly": 3, "monthly": 2, "newborn": 1}
    best: dict[str, dict] = {}
    for lst in repo_lists:
        for r in lst:
            k = r["full_name"].lower()
            cur = best.get(k)
            if cur is None:
                best[k] = dict(r)
                continue
            if order.get(r["delta_unit"], 0) >= order.get(cur.get("delta_unit"), 0):
                if r["delta"] >= cur.get("delta", 0):
                    cur["delta"], cur["delta_unit"] = r["delta"], r["delta_unit"]
            cur["stars"] = max(cur.get("stars", 0), r.get("stars", 0))
            cur["forks"] = max(cur.get("forks", 0), r.get("forks", 0))
            cur["description"] = cur.get("description") or r.get("description", "")
            cur["days_old"] = cur.get("days_old") or r.get("days_old")
            cur["source"] = " / ".join(sorted({s for s in
                                              (cur.get("source", ""), r.get("source", "")) if s}))
    for r in best.values():
        r["heat"] = round(weekly_heat(r), 1)
    return list(best.values())


def qualify(r: dict) -> tuple[bool, str]:
    stars, heat = r.get("stars", 0), r.get("heat", 0)
    if r.get("delta_unit") == "newborn":
        if stars >= CFG["newborn_stars"] and (r.get("days_old") or 99) <= CFG["newborn_days"]:
            d = r.get("days_old") or CFG["newborn_days"]
            return True, f"新项目 {d} 天拿到 {stars:,} 星"
        return False, "新项目星数不够"
    if stars < CFG["min_total_stars"]:
        return False, f"总星不够（{stars:,}）"
    if heat < CFG["min_week_heat"]:
        return False, f"涨得不够快（约每周 {heat:,.0f}）"
    unit = {"daily": "今天", "weekly": "本周", "monthly": "本月"}[r["delta_unit"]]
    return True, f"{unit}涨 {r['delta']:,} 星（共 {stars:,}）"


# ─────────────────────────── 历史去重 ───────────────────────────

def load_history() -> dict:
    if HISTORY_PATH.exists():
        try:
            h = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
            return {"repos": h.get("repos", {}), "videos": h.get("videos", {})}
        except Exception:
            pass
    return {"repos": {}, "videos": {}}


def save_history(h: dict) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=CFG["history_days"])).strftime("%Y-%m-%d")
    h["repos"] = {k: v for k, v in h.get("repos", {}).items() if v >= cutoff}
    h["videos"] = {k: v for k, v in h.get("videos", {}).items() if v >= cutoff}
    HISTORY_PATH.write_text(json.dumps(h, indent=2, ensure_ascii=False), encoding="utf-8")


# ─────────────────────────── 主流程 ───────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    ap.add_argument("--no-history", action="store_true")
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()

    log(f"=== {datetime.now().strftime('%Y-%m-%d %H:%M')} 抓取开始 ===")
    log("[1/3] GitHub Trending（4 个榜：日/周/中文周/月）")
    trending = []
    for since, spoken in (("daily", None), ("weekly", None),
                          ("weekly", "zh"), ("monthly", None)):
        trending.append(fetch_trending(since, spoken, args.offline))
    log("[2/3] GitHub 新仓库爆发")
    newborn = [] if args.offline else fetch_newborns()
    log("[3/3] B 站视频")
    videos = [] if args.offline else fetch_bilibili()

    history = {"repos": {}, "videos": {}} if args.no_history else load_history()
    today = datetime.now().strftime("%Y-%m-%d")

    pool = merge([*trending, newborn])
    log(f"  合并去重后 {len(pool)} 个候选")

    picked, rejected, dup = [], 0, 0
    for r in pool:
        ok, why = qualify(r)
        r["why"] = why
        if not ok:
            rejected += 1
            continue
        if r["full_name"].lower() in history.get("repos", {}):
            dup += 1
            continue
        picked.append(r)

    picked.sort(key=lambda r: (r["heat"], r["stars"]), reverse=True)

    # 配额制：7 条「这周在猛涨」+ 3 条「普通人能直接用」，
    # 否则纯按热度排，永远是 AI 工程圈的仓库，一封能装的一个都没有。
    n_hot = CFG.get("hot_n", 7)
    n_use = CFG.get("use_n", 3)
    hot = picked[:n_hot]
    hot_names = {r["full_name"].lower() for r in hot}
    rest = [r for r in picked[n_hot:] if r["full_name"].lower() not in hot_names]
    rest.sort(key=lambda r: (usability(r), r["stars"]), reverse=True)
    usable = [r for r in rest if usability(r) >= 4][:n_use]
    for r in hot:
        r["lane"] = "hot"
    for r in usable:
        r["lane"] = "usable"
    final = hot + usable

    vids = [v for v in videos if v["bvid"] not in history.get("videos", {})][: CFG["video_max"]]

    log(f"  合格 {len(picked)} | 剔除 {rejected} | 近期推过 {dup} | "
        f"今日入选 {len(final)}（猛涨 {len(hot)} + 能用 {len(usable)}）")

    if not args.no_history:
        for r in final:
            history.setdefault("repos", {})[r["full_name"].lower()] = today
        for v in vids:
            history.setdefault("videos", {})[v["bvid"]] = today
        save_history(history)

    print(f"\n# 🔭 GitHub 今日精选 · {datetime.now().strftime('%m 月 %d 日')}\n")
    print(f"候选 {len(pool)} → 合格 {len(picked) + rejected} → 今天推 {len(final)} 条"
          f"（猛涨 {len(hot)} 条 + 普通人能用的 {len(usable)} 条；"
          f"剔除 {rejected} 个不够热，{dup} 个近期推过）\n")
    if not final:
        print("> 今天没有够格的仓库。按约定：不拿小仓库凑数。\n")

    def _line(i, r):
        print(f"**{i}. {r['full_name']}**　⭐ {r['stars']:,}　{r['why']}　"
              f"`热度 {r['heat']:,.0f}/周·可用度 {usability(r)}`")
        print(f"   {r['description'] or '（无简介）'}")
        print(f"   {r['url']}\n")

    for i, r in enumerate(hot, 1):
        _line(i, r)
    if usable:
        print("## 🛠 这几条普通人可能真用得上\n")
        for i, r in enumerate(usable, len(hot) + 1):
            _line(i, r)
    if vids:
        print("\n## 📺 视频\n")
        for v in vids:
            print(f"- **{v['title']}**｜{v['author']}｜播放 {v['play']:,}｜{v['pubdate']}")
            print(f"  {v['url']}")

    if args.json:
        Path(args.json).write_text(json.dumps(
            {"date": today, "repos": final, "videos": vids,
             "stats": {"pool": len(pool), "rejected": rejected, "dup": dup,
                       "hot": len(hot), "usable": len(usable)}},
            indent=2, ensure_ascii=False), encoding="utf-8")
        log(f"JSON 已存：{args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
