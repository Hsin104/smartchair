# 10/19 Meeting — 正式 WSGI 部署＋壓力測試成果（陳翊昕）

## 1. 選型：Gunicorn(WSGI) vs Uvicorn(ASGI)

| 考量 | Gunicorn (WSGI, gthread) | Uvicorn (ASGI) |
| --- | --- | --- |
| 本專案 view 型態 | 全部是同步 DRF function view，直接執行 | 同步 view 經 `sync_to_async(thread_sensitive=True)`，同一 process 內排在同一條執行緒，失去併發 |
| Physio Agent `asyncio.run()` | worker thread 內沒有 event loop，可直接執行 | 已在 event loop 中，需另外處理巢狀 loop |
| DB 持久連線 `CONN_MAX_AGE` | 每條 thread 重用連線 | Django 文件註明 ASGI 下需關閉（實測開啟時 posture 錯誤率 76～95%） |
| 實測（下表） | 全部端點、全部併發等級勝出 | — |

**結論：採用 Gunicorn，gthread worker，3 process × 8 thread。**
- 多 process：坐姿預測是 TensorFlow 推論，受 GIL 限制，靠多 process 才能用到多核心。
- 多 thread：`/api/agent` 等 OpenAI 回應數秒到數十秒（I/O bound），用 thread 撐住等待中的請求。
- worker 數受記憶體限制：每個 worker 各自載入 TensorFlow 模型，3 worker 實測合計約 1 GB。

## 2. 壓力測試方法（`load_test.py`，可重複執行）

- 封閉迴圈：N 個併發使用者在 15 秒內持續送請求，一個回來才送下一個；N = 1／10／30／50。
- 三個端點：
  - `health` GET /api/health — 只驗證 DB 連線，量 server 本身的上限
  - `history` GET /api/posture/history — Token 驗證＋DB 查詢＋序列化
  - `posture` POST /api/posture — schema 驗證＋**TensorFlow 推論**＋DB 寫入（最重、最關鍵）
- 刻意不測 `/api/agent`：瓶頸在外部 OpenAI，且每次都花費用。
- 錯誤依類型統計（HTTP 狀態碼／連線例外），不是只看有沒有回應。
- 環境：本機 Docker（Windows 11，20 核心），原始數據在 `demo/loadtest/*.json`。

## 3. 結果：posture（坐姿預測，核心請求）

| 併發 | runserver（前） | Uvicorn ASGI | **Gunicorn（後）** |
| --- | --- | --- | --- |
| 1  | 8.1 QPS ／ p95 162 ms | 9.3 ／ 129 ms | **16.6 ／ 102 ms** |
| 10 | 34.5 ／ 465 ms | 54.2 ／ 279 ms | **76.8 ／ 202 ms** |
| 30 | 32.6 ／ 1368 ms | 57.0 ／ 802 ms | **74.0 ／ 580 ms** |
| 50 | 32.9 ／ 2450 ms | 56.3 ／ 1359 ms | **71.0 ／ 920 ms** |

→ 吞吐量約 **2.2 倍**，50 人同時送資料時 p95 延遲從 **2.45 秒降到 0.92 秒**，三者錯誤率皆 0%。

## 4. 結果：輕量請求（QPS）

| 端點 | 併發 | runserver | Uvicorn | **Gunicorn** |
| --- | --- | --- | --- | --- |
| health  | 10 | 195 | 185 | **1413** |
| health  | 50 | 592 | 399 | **1210** |
| history | 10 | 177 | 228 | **530** |
| history | 50 | 349 | 237 | **534** |

（此表的提升同時包含 Gunicorn 與 DB 持久連線兩項改動；posture 的提升在開啟持久連線前就已達成，可歸功於 Gunicorn 多 process。）

## 5. 壓測過程抓到並修正的問題

1. **DB 連線埠耗盡**：Django 預設每個請求新開一條 Postgres 連線，Gunicorn 變快後每秒開關數百條，TIME_WAIT 佔滿本機埠 → `Cannot assign requested address`，health 503 錯誤率最高 81%。
   修正：`CONN_MAX_AGE=60`＋`CONN_HEALTH_CHECKS`，修正後錯誤率 0%。
2. **worker 重生拖垮效能**：`max_requests=2000` 讓測試期間 worker 重生約 20 次，每次重載 TensorFlow。調整為 50000。
3. **模型冷啟動**：各 worker 第一個請求才載入模型，改為 worker 啟動時預載。

## 6. 順帶修正（端到端驗證時發現）

1. **MQTT 心跳誤判**：心跳只在收到訊息時更新，椅子沒人坐超過 120 秒就被判定不健康。改用 MQTT keepalive 的 PINGRESP 更新心跳，實測閒置 3.5 分鐘仍維持 healthy。
2. **降級錯誤訊息沒生效**：MCP client 把錯誤包進 ExceptionGroup，「MCP 連不上／OpenAI 額度超限」的中文訊息比對不到。改為攤平取出真正的子例外，實測停掉 MCP 時正確回覆「無法連線到 MCP Server（mcp:8010）…」。
3. **舊 FAISS 索引維度不符**：還留著 Gemini 時期索引（3072 維）的 volume，知識庫查詢會失敗且錯誤訊息是空的。改為載入時比對維度，不符就自動重建（1536 維），已驗證能查到 forward.txt。
4. **卡死不會自動重啟（修正 10/12 第 25 頁）**：一般 Docker（非 Swarm）只會把容器標成 unhealthy，`restart: unless-stopped` 只在主程式真正結束時才重啟，所以 10/12 只做到「偵測」。新增 `healthcheck.py`：連續 3 次檢查失敗就 SIGKILL 主程式，搭配 `init: true`（tini 當 PID 1，否則容器內砍不掉 PID 1），容器結束後由 restart policy 重啟。mcp 的檢查從 TCP 改成 HTTP（process 卡住時核心仍會完成 TCP 握手，偵測不到）；django 回 503（資料庫異常）只標 unhealthy、不重啟，因為重啟 django 修不好資料庫；啟動後 90 秒寬限，避免模型還在載入就被誤殺。
   **實測**：對三個容器內所有程式送 SIGSTOP 模擬卡死 → django、mcp 約 90 秒、mqtt-subscriber 約 3.5 分鐘（心跳逾時 120 秒＋3 次檢查）自動重啟，各重啟 1 次後恢復 healthy、API 正常回應。
