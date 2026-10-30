# SmartChair 後端 API 回覆（給 Android／Flutter 前端）

> ⚠️ **已被 [api_frontend_guide.md](api_frontend_guide.md) 取代（2026-10-30）**，請改看那份。


> 以下回應都是 10/18 實際打 API 取得的真實內容（本機與正式環境同一版程式；不需登入的 API 已在正式網址確認一致）。

- 正式網址：`https://sandbar-badass-subfloor.ngrok-free.dev/api`（目前就是正式環境，沒有另一個網址）
- 一般 Header：`Content-Type: application/json`、`ngrok-skip-browser-warning: true`

---

## ⚠️ 先處理這 4 件事（不改的話功能會出錯）

1. **不要呼叫 `GET /api/notification/pending`。** 這支是給椅子硬體用的：每呼叫一次，就會把回傳的通知標記成「已送出」，第二次呼叫就拿不到了（實測：第一次回 1 筆，第二次回 0 筆）。App 如果每 5 秒呼叫一次，會把要給椅子震動的提醒搶走。**通知頁只用 `GET /api/notification/history` 就好**（它不會改任何資料，也有 `is_sent` 欄位可以參考）。
2. **認證格式只接受 `Authorization: Token <token>`。** 用 `Bearer` 會回 401。
3. **`/api/me` 直接回傳使用者物件**，不是包在 `user` 裡面。之前遇到「回傳 null」，最可能是程式去讀 `response.user`，或是 Header 沒帶好（沒帶或格式錯會回 401，內容是 `{"detail": "..."}`，不會有使用者資料）。
4. **後端沒有 `score` 欄位**，坐姿紀錄、通知、座椅狀態都沒有分數。時間欄位一律叫 `timestamp`，沒有 `created_at`。

---

## 回覆「請後端優先確認的問題」

| # | 問題 | 回覆 |
|---|---|---|
| 1 | /api/me 能否用 Token 取得使用者 | 可以，見下方實際回應。回應是使用者物件本身 |
| 2 | 是否接受 `Token <token>` | 是，**只**接受這個格式，`Bearer` 會 401 |
| 3 | posture/history 是否直接回傳陣列 | 是，直接回傳陣列，最新的在最前面 |
| 4 | 時間欄位名稱 | `timestamp`（ISO 8601 格式） |
| 5 | chair/status 欄位 | `active`、`username`、`since`、`calibrated`。**沒有** posture／score／occupied，「有沒有人坐」請讀 `active`；目前坐姿請用 `posture/history?limit=1` 取最新一筆 |
| 6 | avatar 格式 | `{"avatar_url": "https://..."}`，必填、最多 500 字，回 200 + 使用者物件 |
| 7 | 忘記密碼是否已部署 | 已部署，Gmail 寄 6 碼驗證碼，10 分鐘內有效，1 分鐘內不能重複寄 |
| 8 | calibrate/auto 是否需要感測資料 | 需要兩個條件：① 自己先 `chair/checkin`；② 最近 15 秒內有椅子傳來的資料（要真的坐在椅子上）。不符合分別回 400、404 |
| 9 | 是否需要實作 notification/ack | **App 不需要**。這支也是給椅子硬體用的，格式是 `{"ids": [1, 2]}` |
| 10 | ESP32 怎麼送資料 | **用 MQTT，不是 HTTP**：ESP32 發布到 MQTT topic `chair/pressure/01`，後端訂閱後自動預測坐姿、寫入資料庫。App 不需要呼叫 `POST /api/posture` |
| 11 | 資料怎麼對應到使用者 | 目前只有一張椅子，沒有 chair_id。資料會寫進「目前 check-in 的使用者」名下：誰呼叫 `POST /api/chair/checkin`，之後的坐姿紀錄就算誰的，直到 checkout 或別人 check-in |
| 12 | 是否都用同一套 Token | 是，所有需要登入的 API 都用同一個 Token（登入或註冊時拿到的），Token 不會過期 |

---

## 每支 API 規格

| API | 需要登入 | 必填欄位 | 成功 | 備註 |
|---|---|---|---|---|
| `GET /users/exists?username=` | 否 | username | 200 `{"exists": bool}` | |
| `POST /register` | 否 | username、password（≥ 6 字） | **201** | email、height（50–250）、weight（20–300）選填。**不能帶其他欄位**，多帶會 400 |
| `POST /login` | 否 | username、password | 200 | 帳號不存在 404、密碼錯 401 |
| `GET /me` | 是 | — | 200 使用者物件 | |
| `PATCH /me/update` | 是 | 全部選填 | 200 使用者物件 | 可改 height、weight、email、display_name、avatar_url，沒傳的欄位不會被清掉 |
| `POST /me/avatar` | 是 | avatar_url | 200 使用者物件 | 存的是網址，不是上傳圖片檔 |
| `POST /auth/change-password` | 是 | current_password、new_password（≥ 6 字） | 200 | 目前密碼錯 401 |
| `POST /auth/forgot-password/request` | 否 | username、email | 200 | 帳號不存在 404、Email 不符 400、寄信失敗 503 |
| `POST /auth/forgot-password/verify` | 否 | username、code（6 碼字串）、new_password（≥ 6 字） | 200 | 驗證碼錯誤或過期 400 |
| `GET /posture/history?limit=` | 是 | — | 200 陣列 | limit 預設 50，必須是整數 |
| `POST /agent` | 是 | posture | 200 | 見下方 |
| `GET /notification/history?limit=` | 是 | — | 200 | 回傳格式見下方，包在 `notifications` 裡 |
| `GET /notification/pending` | — | — | — | **App 請勿呼叫**（見最上方） |
| `POST /chair/checkin` | 是 | 無 body | 200 | 會把原本坐著的人自動 checkout |
| `POST /chair/checkout` | 是 | 無 body | 200 | |
| `GET /chair/status` | 否 | — | 200 | |
| `POST /chair/calibrate/auto` | 是 | 無 body | 200 | 條件見上方第 8 題 |

### AI 建議 `POST /api/agent`

- `posture` 必填，只能是 `normal`、`left`、`right`、`forward`、`recline`、`sedentary`（**`empty` 不行**，會 400）
- `user_message` 選填，最多 500 字。沒填時送空字串、`null`，或不帶這個欄位都可以
- 回應欄位：`posture`、`posture_display`、`advice`、`recommended_exercises`（格式跟你們列的一樣），另外多一個 `steps`（AI 的決策過程，App 不需要顯示）
- 實測回應時間約 6～25 秒，App 設 90 秒 timeout 足夠
- AI 服務暫時無法使用時回 **503**，內容是 `{"error": "Agent 暫時無法使用：..."}`

### 坐姿代碼

`normal`、`forward`、`left`、`right`、`recline`、`sedentary`、`empty`。`empty` 是椅子偵測到沒人坐時寫入的，會出現在 posture/history 裡。

---

## 錯誤回應格式

後端的錯誤格式有四種，建議 App 依序檢查這幾個欄位：

| 情況 | 格式 | 例子 |
|---|---|---|
| 欄位格式錯誤（缺欄位、多欄位、型別錯） | `{"schema_error": "..."}` | 400 |
| 帳號／密碼相關 | `{"success": false, "error_code": "...", "message": "中文說明"}` | `USER_NOT_FOUND`、`INVALID_PASSWORD`、`ACCOUNT_EXISTS`、`EMAIL_MISMATCH`、`INVALID_CODE`、`EMAIL_SEND_FAILED` |
| 椅子、AI 相關 | `{"error": "中文說明"}` | 校準條件不符、AI 暫時無法使用 |
| 沒登入或 Token 錯 | `{"detail": "..."}` | 401 |

可以直接顯示給使用者看的是 `message` 或 `error` 欄位，兩者都是中文。

---

## 指定的 3 支 API 實際回應

### `GET /api/me`
```
HTTP 200
{
  "id": 56,
  "username": "fe_contract_check",
  "email": "fe@example.com",
  "display_name": null,
  "avatar_url": null,
  "height": 170.0,
  "weight": 65.0
}
```
沒帶 Token、或用 `Bearer`：
```
HTTP 401
{ "detail": "Authentication credentials were not provided." }
```

### `GET /api/posture/history?limit=1`
```
HTTP 200
[
  {
    "id": 114484,
    "timestamp": "2026-10-18T16:42:33.396955+08:00",
    "posture": "left",
    "posture_display": "身體左傾",
    "seat_pressure_data": { "left_back": 600, "left_mid": 600, ... },
    "back_pressure_data": null,
    "physio_advice": null,
    "confidence": null
  }
]
```
- `posture_display` 是中文名稱，可以直接顯示
- `confidence` 是 AI 判斷的信心分數（0～1），有些紀錄是 null（由規則判斷，不是 AI 推論）

### `GET /api/notification/pending?limit=1`
```
第一次呼叫：HTTP 200
{
  "count": 1,
  "notifications": [
    { "id": 16650, "message": "坐姿提醒：身體左傾", "timestamp": "2026-10-18T08:42:33.404051Z" }
  ]
}

第二次呼叫：HTTP 200
{ "count": 0, "notifications": [] }
```
這就是為什麼 App 不能呼叫它：呼叫一次，通知就被標成已送出。也不支援 `limit` 參數（會被忽略）。

改用 `GET /api/notification/history?limit=1`：
```
HTTP 200
{
  "count": 1,
  "notifications": [
    { "id": 16650, "message": "坐姿提醒：身體左傾", "timestamp": "2026-10-18T08:42:33.404051Z", "is_sent": false }
  ]
}
```
- 通知沒有 `posture` 欄位，坐姿名稱寫在 `message` 裡
- 兩種時間格式（`+08:00` 和 `Z`）都是標準 ISO 8601，一般的解析函式都能處理
