"""只测发信通道：不抓新闻、不调 LLM，30 秒内验证 SMTP 是否可用。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fetch_news as fn

cfg = fn.load_config()
senders = fn._build_senders(cfg)
if not senders:
    print('=== 没有可用通道（缺少 SMTP_USER/SMTP_PASSWORD）===')
    sys.exit(1)

print('可用通道:')
for s in senders:
    print(f"  - {s['name']}: {s['host']}:{s['port']} (ssl={s['ssl']}, user={s['user']})")

body = (
    '<h2>📡 发信通道测试</h2>'
    '<p>收到这封邮件说明当前发信通道可用，每日简报会正常送达。</p>'
    '<p style="color:#888">这是一封测试邮件，不会覆盖仓库里的最新简报。</p>'
)
try:
    fn.send_email(body, cfg, archive=False)
    print('=== 测试成功：邮件已发出 ===')
except Exception as e:
    print(f'=== 测试失败：{e} ===')
    sys.exit(1)
