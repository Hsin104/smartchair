"""
Physio Agent 故障測試（回應教授 11/16 第 12 點）：模擬外部服務出錯，確認使用者會收到明確結果，而不是卡住或空白。

全部情境都不會真的讓 OpenAI 產生回答，也就不會計費：
    A 系列：OpenAI 位址改成本機沒有服務的埠 → 連線被拒（模擬 OpenAI 服務中斷）
    B 系列：OpenAI 位址改成本機一個「接受連線但永遠不回應」的假伺服器 → 模擬逾時
    C 系列：MCP Server 位址改成沒有服務的埠 → 模擬 MCP 掛掉（ReAct 第一步就連不上工具）
    D 系列：使用格式正確但無效的金鑰 → OpenAI 回 401（被拒絕的請求不計費）

每個情境都走 agent_worker._process（與正式環境的非同步任務同一段程式），
記錄任務最後狀態（done／failed）、App 會看到的文字，以及花了幾秒。

執行：venv/Scripts/python.exe fault_test.py [結果檔名]   （需要本機 Docker 的 mcp 在 localhost:8010）
     結果存到 demo/<結果檔名>.json（預設 fault_test_result）
"""

import asyncio
import json
import os
import socket
import sys
import threading
import time
from types import SimpleNamespace

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smartchair_backend.settings')
django.setup()

from django.conf import settings

import api.management.commands.agent_worker as worker
from api import physio_agent

UNREACHABLE = 'http://127.0.0.1:9/v1'          # 沒有服務的埠：連線立刻被拒
HANG_PORT = 18999                              # 假伺服器：接受連線但不回應


def _hang_server():
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('127.0.0.1', HANG_PORT))
    srv.listen(50)
    conns = []
    while True:
        c, _ = srv.accept()
        conns.append(c)   # 留著連線不關、也不回任何資料


async def run_case(name, posture, message, base_url=None, api_key=None, mcp_port=None):
    captured = {}

    def fake_finish(job, advice='', steps=None, error=''):
        captured.update(status='failed' if error else 'done', text=error or advice, steps=steps or [])

    env_backup = {k: os.environ.get(k) for k in ('OPENAI_BASE_URL', 'OPENAI_API_BASE')}
    cfg_backup = (settings.OPENAI_API_KEY, settings.MCP_SERVER_PORT)
    if base_url:
        os.environ['OPENAI_BASE_URL'] = os.environ['OPENAI_API_BASE'] = base_url
    if api_key:
        settings.OPENAI_API_KEY = api_key
    if mcp_port:
        settings.MCP_SERVER_PORT = mcp_port
    worker._finish = fake_finish
    t0 = time.perf_counter()
    try:
        await worker._process(SimpleNamespace(id=name, posture=posture, user_id=1, user_message=message))
    finally:
        for k, v in env_backup.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        settings.OPENAI_API_KEY, settings.MCP_SERVER_PORT = cfg_backup
    sec = time.perf_counter() - t0
    scope = next((s['observation'] for s in captured.get('steps', []) if s['action'] == 'scope_check'), '')
    row = {'case': name, 'status': captured.get('status'), 'seconds': round(sec, 1),
           'text': captured.get('text', ''), 'scope_step': scope}
    print(json.dumps(row, ensure_ascii=False), flush=True)
    return row


async def main():
    threading.Thread(target=_hang_server, daemon=True).start()
    hang = f'http://127.0.0.1:{HANG_PORT}/v1'
    fake_key = 'sk-proj-' + 'x' * 40
    q = '久坐後下背很痠，要怎麼調整？'
    cases = [
        ('A1 OpenAI 中斷＋有自述', 'forward', q, dict(base_url=UNREACHABLE)),
        ('A2 OpenAI 中斷＋只有坐姿', 'forward', '', dict(base_url=UNREACHABLE)),
        ('B1 OpenAI 無回應＋有自述', 'forward', q, dict(base_url=hang)),
        ('B2 OpenAI 無回應＋只有坐姿', 'forward', '', dict(base_url=hang)),
        ('C1 MCP 中斷＋只有坐姿', 'forward', '', dict(mcp_port=18998)),
        ('D1 金鑰無效＋有自述', 'forward', q, dict(api_key=fake_key)),
        ('D2 金鑰無效＋只有坐姿', 'forward', '', dict(api_key=fake_key)),
    ]
    rows = [await run_case(n, p, m, **kw) for n, p, m, kw in cases]
    name = sys.argv[1] if len(sys.argv) > 1 else 'fault_test_result'
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'demo', f'{name}.json')
    if os.path.isdir(os.path.dirname(out)):
        with open(out, 'w', encoding='utf-8') as f:
            json.dump(rows, f, ensure_ascii=False, indent=2)
        print('結果已存到', out)


if __name__ == '__main__':
    asyncio.run(main())
