"""在 GitHub Actions(美国网络) 上探测哪些 Gemini 模型当前真的可用，用于维护降级池。"""
import os
from google import genai
from google.genai import types

client = genai.Client(api_key=os.environ['GEMINI_API_KEY'])

try:
    models = [m.name.split('/')[-1] for m in client.models.list()]
except Exception as e:
    print('列出模型失败:', e)
    raise SystemExit(1)

skip = ('tts', 'image', 'embedding', 'aqa', 'veo')
cands = [m for m in models if ('flash' in m or 'pro' in m) and not any(s in m for s in skip)]
print(f'共 {len(models)} 个模型，候选 {len(cands)} 个\n')

ok, fail = [], []
for m in cands:
    try:
        r = client.models.generate_content(
            model=m, contents='回复两个字：正常',
            config=types.GenerateContentConfig(max_output_tokens=20),
        )
        t = (r.text or '').strip()
        print(f'[OK]   {m} -> {t[:12]}')
        ok.append(m)
    except Exception as e:
        msg = str(e).split('\n')[0][:110]
        print(f'[FAIL] {m} -> {msg}')
        fail.append(m)

print('\n=== 可用模型 ===')
print(', '.join(ok) if ok else '（无）')
