"""
Gunicorn 正式部署設定（取代 python manage.py runserver）。

為什麼選 Gunicorn(WSGI) 而不是 Uvicorn/Daphne(ASGI)：
- 所有 API 都是同步的 DRF function view，沒有 async view／WebSocket。ASGI 底下 Django 會用
  sync_to_async(thread_sensitive=True) 執行同步 view，同一個 process 內所有同步 view 都排在
  同一條執行緒上，反而失去併發能力（實測數字見 load_test.py 對照結果）。
- Physio Agent 內部用 asyncio.run() 跑 MCP＋ReAct 迴圈，在 WSGI 的 worker thread 裡沒有
  既存 event loop，可以直接執行；放在 ASGI 的 event loop 裡反而要另外處理巢狀 loop。

worker 模型：gthread（多 process × 多 thread）
- 多 process：坐姿預測是 TensorFlow 推論＋Python 前處理，受 GIL 限制，要靠多 process 才能
  真正平行用到多核心。
- 多 thread：/api/agent 會等 OpenAI 回應數秒到數十秒（I/O bound），用 thread 撐住等待中的請求，
  不會一個 Agent 請求就卡死整個 worker。

每個 worker 都會各自載入 TensorFlow 模型（約 600MB 記憶體），worker 數量依主機記憶體調整，
用環境變數 GUNICORN_WORKERS / GUNICORN_THREADS 覆寫，不需要改程式碼。
刻意不開 preload_app：TensorFlow 在 fork 之前初始化，fork 後的子 process 可能卡死。
"""

import os

bind = '0.0.0.0:8000'
worker_class = 'gthread'
workers = int(os.getenv('GUNICORN_WORKERS', 3))
threads = int(os.getenv('GUNICORN_THREADS', 8))

# Physio Agent 的 LLM 逾時是 60 秒（api/physio_agent.py _LLM_TIMEOUT_SECONDS），
# worker timeout 要比它長，否則 Agent 還沒回應完 worker 就被 Gunicorn 強制砍掉
timeout = 120
graceful_timeout = 30
keepalive = 5

# 每個 worker 處理一定數量請求後自動重生，避免長時間運行累積記憶體洩漏；jitter 讓各 worker 錯開重生。
# 門檻不能設太低：重生要重新載入 TensorFlow 模型（數秒），壓測時曾設 2000，
# 結果測試期間 worker 重生約 20 次，重生瞬間的連線失敗、吞吐量也被拖垮。
max_requests = 50000
max_requests_jitter = 5000


def post_worker_init(worker):
    # 坐姿模型在 api.views 匯入時載入；不預先匯入的話，每個 worker 收到第一個請求才載入，
    # 該請求會多等好幾秒。worker 啟動時就先匯入，把載入成本移到開機階段。
    import api.views  # noqa: F401


accesslog = '-'
errorlog = '-'
loglevel = 'info'
