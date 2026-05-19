診斷報告 — 前端（smart_chair_app）

摘要

- 時間: 請以收到此檔案時為準。
- 問題: 前端顯示已登入且存在 token，但呼叫 `GET /api/me` 回傳為 null（`me == null`），同時 posture history 與 pending notification 都為空。
- 前端檢測字串（UI 顯示）:
  backend: history=0, pending=0, advice=no; auth: loggedIn=true, me=no, token=yes

要請後端執行的檢查

1) 使用前端提供的 token 測試 API（請把 `<YOUR_TOKEN>` 換成前端 token）：

```bash
curl -i -H "Authorization: Token <YOUR_TOKEN>" "https://sandbar-badass-subfloor.ngrok-free.dev/api/me"
curl -i -H "Authorization: Token <YOUR_TOKEN>" "https://sandbar-badass-subfloor.ngrok-free.dev/api/posture/history?limit=1"
curl -i -H "Authorization: Token <YOUR_TOKEN>" "https://sandbar-badass-subfloor.ngrok-free.dev/api/notification/pending"
```

期望結果：
- `/api/me` 應回傳使用者資料（200 + JSON），而不是空值或 null。
- `/api/posture/history?limit=1` 應回傳最新的一筆 posture（若帳戶有資料）。
- 若上述回傳 401/403 或空值，請檢查 token 驗證流程。

2) 檢查伺服器端驗證與日誌

- 確認伺服器收到的 `Authorization` 標頭內容（完整字串）。
- 若使用 Django REST framework 或類似 middleware，檢查 token 驗證 middleware 是否正確解析並對應到使用者。
- 檢查 token 是否已被標記為失效、或與使用者帳號不匹配。
- 檢查 `/api/me` endpoint 的實作：是否在 token 驗證通過後仍可能回傳 null（例如 user profile 未建立或被刪除）。

3) 若 token 可以通過驗證，但 `/api/me` 回傳 null：

- 請列出 `/api/me` 的回傳 body（raw JSON）與 HTTP status code。
- 檢查資料庫內是否存在對應 user profile（由 token 對應的 user id）。
- 檢查是否有 migration 或 model 欄位變動導致查詢失敗。

建議臨時測試指令（可模擬一筆 posture）

- 若想確認前端在有 posture 時會顯示資料，可先用 admin token 或其他受信任 token 建立一筆 posture（以你的 API 格式為準）：

```bash
curl -i -X POST -H "Authorization: Token <ADMIN_OR_TEST_TOKEN>" \
  -H "Content-Type: application/json" \
  --data '{"chair_id": "test-chair", "timestamp": "2026-05-19T00:00:00Z", "posture": {"lean": 0.1}}' \
  "https://sandbar-badass-subfloor.ngrok-free.dev/api/posture/"
```

- 再用使用者 token 測試 `GET /api/posture/history?limit=1`。

如何從前端取 token（若後端需要確切 token）

- 前端 SharedPreferences 有儲存 `auth_token`（key: `auth_token`）。
- 或在開發機上，開啟瀏覽器 devtools 的 Console，執行 `localStorage.getItem('auth_token')`（若前端直接存到 localStorage）。

附註與優先檢查項目

- 優先檢查 token 驗證中間件與對應到 user 的邏輯。
- 若後端期望 `Bearer <token>` 而前端送 `Token <token>`，也會導致 `me==null`（請確認接受的格式）。
- 若有多個 token 系統（例如 JWT 與 DRF Token），請確認前端與後端使用同一種 token。

前端目前可提供的資訊

- 前端已顯示診斷對話框，內容為：
  - 已登入: true
  - token 存在: yes
  - 前端建議執行的 curl 指令（如上）

請後端回覆：
- `/api/me` 的實際 HTTP status code 與 response body（貼 raw JSON）。
- token 是否被伺服器認可，或伺服器端看到的 Authorization header 為何。

---

若你希望我把這份檔案直接傳到某個後端 issue 或 email（如有 API 或 repo 權限），請提供相關連結或授權，我可以替你建立 issue 並貼上內容。
