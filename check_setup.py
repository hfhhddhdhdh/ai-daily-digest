"""
AI Daily Digest — 配置自检脚本
在 GitHub Actions 中运行：Actions → ✅ 配置自检 → Run workflow
检查项：
  1. GitHub Secrets 是否齐全
  2. config.yml 能否正常解析
  3. GitHub API（高星项目抓取）是否可用
  4. LLM API（按 config 的 provider）连接是否成功
  5. SMTP 登录 + 发送一封测试邮件
"""
import os
import smtplib
import ssl
import sys
import yaml
from pathlib import Path
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

OK = "✅"
FAIL = "❌"


def section(title: str) -> None:
    print(f"\n── {title} " + "─" * max(1, 40 - len(title)))


def check_secrets() -> bool:
    section("GitHub Secrets")
    ok = True
    provider = _provider_from_config()

    required = {
        "SMTP_USER": "发件邮箱（SMTP_USER，如 xxx@outlook.com）",
        "SMTP_PASSWORD": "发件邮箱应用密码（SMTP_PASSWORD，16 位）",
    }
    if provider == "gemini":
        required["GEMINI_API_KEY"] = "Gemini API Key（https://aistudio.google.com/apikey）"
    elif provider == "anthropic":
        required["ANTHROPIC_API_KEY"] = "Anthropic API Key"
    elif provider == "deepseek":
        required["DEEPSEEK_API_KEY"] = "DeepSeek API Key（https://platform.deepseek.com）"

    for name, hint in required.items():
        if os.environ.get(name):
            print(f"  {OK} {name:20s} (已设置)")
        else:
            print(f"  {FAIL} {name:20s} (未设置 — 需要 {hint})")
            ok = False

    recipient = os.environ.get("RECIPIENT_EMAIL")
    print(f"  {'✅' if recipient else 'ℹ️'} {'RECIPIENT_EMAIL':20s} "
          f"({recipient or '未设置 — 默认发给发件邮箱自己'})")
    return ok


def _provider_from_config() -> str:
    try:
        cfg = _load_config()
        return cfg.get("provider", "gemini")
    except Exception:
        return "gemini"


def _load_config() -> dict:
    path = Path(__file__).parent / "config.yml"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def check_config() -> bool:
    section("config.yml")
    ok = True
    try:
        cfg = _load_config()
        print(f"  {OK} config.yml 解析成功")
        print(f"  {OK} provider = {cfg.get('provider', '?')}")
        print(f"  {OK} topics = {len(cfg.get('topics') or [])} 个")
        print(f"  {OK} news_feeds = {len(cfg.get('news_feeds') or {})} 个新闻源")
        print(f"  {OK} blog_feeds = {len(cfg.get('blog_feeds') or {})} 个博客")
        gh = cfg.get("github") or {}
        print(f"  {OK} github 板块 = {'开' if gh.get('enabled', True) else '关'} "
              f"(每天最多 {gh.get('count', 8)} 条)")
        smtp = cfg.get("smtp") or {}
        print(f"  {OK} smtp = {smtp.get('host')}:{smtp.get('port')} "
              f"({'SSL' if smtp.get('ssl') else 'STARTTLS'})")
        print(f"  {OK} send_hour_utc = {cfg.get('send_hour_utc')} "
              f"(北京时间 {int(cfg.get('send_hour_utc', 0)) + 8}:00 送达)")
    except Exception as e:
        print(f"  {FAIL} 解析失败: {e}")
        return False
    return ok


def check_github_api() -> bool:
    section("GitHub API（高星项目抓取）")
    try:
        import requests
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "ai-daily-digest-check"}
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        resp = requests.get(
            "https://api.github.com/search/repositories",
            params={"q": "stars:>100 created:>2020-01-01", "sort": "stars",
                    "order": "desc", "per_page": 1},
            headers=headers, timeout=20,
        )
        resp.raise_for_status()
        total = resp.json().get("total_count", 0)
        print(f"  {OK} GitHub 搜索 API 可用（命中仓库约 {total:,} 个）")
        return True
    except Exception as e:
        print(f"  {FAIL} GitHub API 调用失败: {e}")
        return False


def check_llm() -> bool:
    section("LLM API")
    try:
        cfg = _load_config()
        provider = cfg.get("provider", "gemini")
        model = (cfg.get("digest") or {}).get(f"{provider}_model", "?")

        if provider == "gemini":
            from google import genai as google_genai
            from google.genai import types as genai_types
            client = google_genai.Client(api_key=os.environ["GEMINI_API_KEY"])
            resp = client.models.generate_content(
                model=model,
                contents="只回复两个字：正常",
                config=genai_types.GenerateContentConfig(max_output_tokens=20),
            )
            text = (resp.text or "").strip()
            print(f"  {OK} Gemini 连接成功 (model={model})，回复: {text or '(空)'}")
            return True

        if provider == "anthropic":
            import anthropic
            client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
            msg = client.messages.create(
                model=model, max_tokens=20,
                messages=[{"role": "user", "content": "只回复两个字：正常"}],
            )
            text = (msg.content[0].text or "").strip()
            print(f"  {OK} Anthropic 连接成功 (model={model})，回复: {text[:20]}")
            return True

        if provider == "deepseek":
            import requests
            resp = requests.post(
                "https://api.deepseek.com/chat/completions",
                headers={"Authorization": f"Bearer {os.environ['DEEPSEEK_API_KEY']}",
                         "Content-Type": "application/json"},
                json={"model": model, "messages": [{"role": "user", "content": "只回复两个字：正常"}],
                      "max_tokens": 20},
                timeout=60,
            )
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"].strip()
            print(f"  {OK} DeepSeek 连接成功 (model={model})，回复: {text[:20]}")
            return True

        print(f"  {FAIL} 未知 provider: {provider}")
        return False
    except KeyError as e:
        print(f"  {FAIL} 缺少密钥/环境变量: {e}")
        return False
    except Exception as e:
        print(f"  {FAIL} LLM API 调用失败: {e}")
        return False


def check_smtp_and_test() -> bool:
    section("SMTP + 测试邮件")
    try:
        cfg = _load_config()
        smtp = cfg.get("smtp") or {}
        host = smtp.get("host", "smtp-mail.outlook.com")
        port = int(smtp.get("port", 587))
        use_ssl = bool(smtp.get("ssl", False))

        user = os.environ.get("SMTP_USER", "")
        password = os.environ.get("SMTP_PASSWORD", "")
        recipient = os.environ.get("RECIPIENT_EMAIL") or user

        if not user or not password:
            print(f"  {FAIL} 缺少 SMTP_USER 或 SMTP_PASSWORD")
            return False

        html = f"""<!DOCTYPE html><html><body style="font-family:sans-serif">
<h2>📡 测试邮件</h2>
<p>如果你收到这封邮件，说明 AI Daily Digest 配置成功！🎉</p>
<p>每天 <strong>北京时间 8:00</strong> 左右，你将收到当天的 AI 简报
（新闻 + 趋势 + 论文 + 博客 + GitHub 高星新项目）。</p>
<p style="color:#888">发送时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
</body></html>"""

        msg = MIMEMultipart("alternative")
        msg["Subject"] = "📡 AI Daily Digest · 测试邮件"
        msg["From"] = user
        msg["To"] = recipient
        msg.attach(MIMEText(html, "html", "utf-8"))

        if use_ssl:
            server = smtplib.SMTP_SSL(host, port, timeout=60)
        else:
            server = smtplib.SMTP(host, port, timeout=60)
            server.ehlo()
            server.starttls(context=ssl.create_default_context())
            server.ehlo()

        with server:
            server.login(user, password)
            server.sendmail(user, recipient, msg.as_string())

        print(f"  {OK} SMTP 登录成功 ({user})")
        print(f"  {OK} 测试邮件已发送 → {recipient}（请查收，含垃圾箱）")
        return True
    except Exception as e:
        print(f"  {FAIL} SMTP 失败: {e}")
        print("      常见原因：① 填了登录密码而不是 163/QQ 邮箱的「授权码」；")
        print("      ② 邮箱没在设置里开启 SMTP 服务；③ 账号或授权码有误")
        return False


def main() -> None:
    print("=" * 56)
    print("  📡 AI Daily Digest — 配置自检")
    print("=" * 56)

    checks = [
        ("GitHub Secrets", check_secrets),
        ("config.yml", check_config),
        ("GitHub API", check_github_api),
        ("LLM API", check_llm),
        ("SMTP + 测试邮件", check_smtp_and_test),
    ]
    results = {}
    for name, fn in checks:
        results[name] = fn()

    print("\n" + "═" * 56)
    failed = [k for k, v in results.items() if not v]
    if failed:
        print(f"  {'❌':4s} 未通过: {', '.join(failed)}")
        print("  💡 修复后重新运行本检查即可。")
    else:
        print("  🎉 所有检查通过！测试邮件已发送，明天早上开始自动送达。")
    print("═" * 56)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
