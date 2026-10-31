# SmartChair 後端 API 串接說明（給 Android／Flutter 前端）

> 2026-10-31 版（新增頭像上傳），**取代先前的 `api_reply_frontend_1018.md` 與 `api_update_frontend_1023.md`，只看這份即可**。
> 內容都是實際打 API 驗證過的。全部端點一覽見 [api_endpoints.md](api_endpoints.md)。
> **網頁版（`zhen` 分支）與 iOS（iOS-smart-chair）是兩份程式，以下修改兩邊都要做。**

- 網址：`https://sandbar-badass-subfloor.ngrok-free.dev/api`
- Header：`Content-Type: application/json`、`ngrok-skip-browser-warning: true`
- 需要登入的 API：`Authorization: Token <token>`（**只接受 `Token`，用 `Bearer` 會 401**）

---

## ⚠️ 先改這 4 件事（不改功能會出錯）

1. **不要呼叫 `GET /notification/pending`**：那是給椅子硬體用的，每呼叫一次就會把通知標成「已送出」（第二次就拿不到）。通知頁只用 `GET /notification/history`。兩份程式的 `api_service.dart` 目前都在 history 沒資料時改呼叫 pending，請拿掉。
2. **`GET /me` 直接回傳使用者物件**，不是包在 `user` 裡。之前「回傳 null」多半是去讀了 `response.user`。
3. **後端沒有 `score` 欄位**；時間欄位一律叫 `timestamp`（ISO 8601），沒有 `created_at`。
4. **AI 建議改用非同步流程**（見第三節），舊的 `POST /agent` 之後會移除。

---

## 一、帳號

| API | 必填 | 成功 | 備註 |
|---|---|---|---|
| `GET /users/exists?username=` | — | 200 `{"exists": bool}` | |
| `POST /register` | username、password（≥6） | **201** | email、height（50–250）、weight（20–300）選填；**不能帶其他欄位**（會 400） |
| `POST /login` | username、password | 200 | 帳號不存在 404、密碼錯 401 |
| `GET /me` | — | 200 使用者物件 | |
| `PATCH /me/update` | 皆選填 | 200 使用者物件 | height、weight、email、display_name、avatar_url |
| `POST /me/avatar` | avatar_url | 200 使用者物件 | 存網址，不是上傳圖片 |
| `POST /me/avatar/upload` | file（multipart） | 200 | **上傳頭像圖片**，見下方 |
| `POST /auth/change-password` | current_password、new_password（≥6） | 200 | 目前密碼錯 401 |
| `POST /auth/forgot-password/request` | username、email | 200 | 寄 6 碼驗證碼，10 分鐘有效 |
| `POST /auth/forgot-password/verify` | username、code（6 碼字串）、new_password | 200 | 驗證碼錯誤或過期 400 |

登入／註冊成功的回應：`{"success": true, "token": "...", "user": {"id", "username", "email", "display_name", "avatar_url", "height", "weight"}}`

### 上傳頭像 `POST /me/avatar/upload`（10/31 新增）

- `Content-Type: multipart/form-data`（不要自己設定，讓套件自動帶 boundary），欄位名稱 **`file`**
- 不要轉成 base64；`/me/avatar` 也不接受 `data:image/...`
- 只收 PNG、JPG、JPEG，**以圖片實際內容判斷**（改副檔名沒用），最大 5 MB
- 後端會縮成最長邊 512 px 並重新存檔（去掉照片的 EXIF／GPS），回傳的網址每次都不同，舊圖會刪除

成功 200：
```json
{ "success": true,
  "avatar_url": "https://sandbar-badass-subfloor.ngrok-free.dev/media/avatars/3f9c...e1.png",
  "user": { "id": 1, "username": "dpz", "email": "...", "display_name": "...",
            "avatar_url": "https://.../media/avatars/3f9c...e1.png", "height": 170, "weight": 60 } }
```
失敗 400：`{"success": false, "message": "只支援 PNG、JPG、JPEG 圖片"}`、`"圖片大小不能超過 5MB"`、`"請以 multipart/form-data 上傳，欄位名稱為 file"`；沒登入 401。之後 `GET /me` 會回傳新的 `avatar_url`。

> ⚠️ **網頁版請幫忙實測圖片能不能顯示**：網址是 ngrok 免費網域，呼叫 API 時靠 `ngrok-skip-browser-warning` 標頭跳過警告頁，但 `<img>`／`Image.network` 抓圖片時帶不了這個標頭，圖片**可能被 ngrok 警告頁擋住**（顯示破圖）。如果擋住，請改成用 HTTP 請求（帶這個標頭）抓圖片 bytes 再用 `Image.memory` 顯示，並告訴我結果。iOS 不受影響的話也請說一聲。

---

## 二、椅子：入座、校正、目前坐姿

### 1. 入座 `POST /chair/checkin`

```json
{ "device_id": "chair_A1B2C3" }
```
- `device_id` 選填，印在椅子標籤上（`chair_` ＋ 6 碼）；**不帶就是原本那張 `chair_01`，現在的 App 不改也能用**
- 同一張椅子原本坐的人、以及自己原本坐的其他椅子，都會自動結束（一張椅子一人、一人一張椅子）
- 回應：`{"status": "checked_in", "username": "...", "device_id": "...", "calibrated": true}`
- **`calibrated` 為 `false` 時，每次入座都要跳出校正提示**（例如「花 5 秒校正坐姿？」，可以選「稍後」），直到使用者完成校正為止；為 `true` 就不用再提示

### 2. 校正（只要做一次，換椅子也通用）

校正結果記在使用者身上，之後坐任何一張椅子都會自動套用，椅子的震動判斷也會變成個人化。

**流程**（由椅子取樣 5 秒計算；椅子沒回應時後端會自動改用自己的資料計算）：

1. 畫面顯示「請坐正、保持不動」，使用者按「開始校正」
2. `POST /chair/calibration`（無 body）→ 立即回 **202**：
   ```json
   { "request_id": "...", "status": "running", "duration_s": 5, "timeout_s": 10 }
   ```
3. 顯示 5 秒倒數，期間**每秒** `GET /chair/calibration` 一次：

| `status` | App 要做什麼 |
|---|---|
| `running` | 繼續倒數／等待（最多約 10 秒） |
| `done` | 顯示「校正完成」，停止查詢；`calibration` 內有 `neutral_x`、`neutral_y`、`method` |
| `failed` | 顯示 `message`（中文原因），讓使用者重試，停止查詢 |

失敗原因 `reason`：`no_occupancy`（沒坐在椅子上）、`unstable`（校正時有移動）、`no_data`（椅子沒連線）。沒入座就呼叫會回 400 `{"error": "請先入座（check-in）再進行校正"}`。

> 舊的 `POST /chair/calibrate/auto` 仍可用（後端立即計算、同步回傳），但比較不準，改版時請換成上面的新流程。

### 3. 離座 `POST /chair/checkout`（無 body）

### 4. 目前坐姿：`GET /posture/history?limit=1`

流程跟之前一樣：椅子送資料 → 後端 AI 模型分析坐姿 → App 讀最新一筆顯示。建議每 5 秒查一次。

```json
[{ "id": 114484, "timestamp": "2026-10-18T16:42:33+08:00",
   "posture": "left", "posture_display": "身體左傾", "confidence": 0.94,
   "seat_pressure_data": {...}, "back_pressure_data": {...}, "physio_advice": null }]
```
- 直接顯示 `posture_display`（中文）
- 坐姿代碼：`normal`、`left`、`right`、`forward`、`recline`、`sedentary`（久坐）、`empty`（沒人坐）
- `confidence` 為 AI 判斷的信心（0～1），有時是 null（由規則判斷，例如久坐）

### 5. 椅子狀態

| API | 說明 |
|---|---|
| `GET /chair/status?device_id=` | 某張椅子目前誰在用：`device_id`、`online`、`active`、`username`、`since`、`calibrated`（不帶參數＝chair_01） |
| `GET /chairs` | 所有椅子清單：`device_id`、`online`、`username`、`since`、`last_seen` |

`online`＝最近 15 秒內有收到椅子的資料。

---

## 三、AI 建議（非同步）

教授要求 AI 建議不能讓使用者卡著等，所以改成「先拿任務編號、再查結果」。

**1. 送出** `POST /agent/jobs`
```json
{ "posture": "left", "user_message": "" }
```
- `posture` 必填：`normal`／`left`／`right`／`forward`／`recline`／`sedentary`（`empty` 不行）
- `user_message` 選填，最多 500 字；沒填送空字串、`null` 或不帶都可以
- 立即回應 202：`{"job_id": "...", "status": "queued", "poll_url": "/api/agent/jobs/<job_id>"}`

**2. 每 2 秒查一次** `GET /agent/jobs/<job_id>`

| status | App 要做什麼 |
|---|---|
| `queued`、`running` | 繼續等，顯示「AI 分析中…」 |
| `done` | 讀 `posture_display`、`advice`、`recommended_exercises`（伸展動作＋影片），停止查詢 |
| `failed` | 顯示 `error`（中文），停止查詢 |

- 通常 6～25 秒完成，後端最多等 60 秒；**查詢 90 秒還沒結果就可以停止**
- 問到藥物、診斷、減重、懷孕等範圍外的問題，`advice` 會是「根據目前知識庫，我無法回答此問題，建議諮詢專業醫師或物理治療師。」，請照常顯示
- 只能查自己的任務，查別人的 404
- `steps` 是 AI 的決策過程，App 不需要顯示

`GET /agent/stretch-plan`：依近 7 天壞坐姿統計推薦伸展動作清單（含 YouTube 連結）。

---

## 四、通知

`GET /notification/history?limit=50`
```json
{ "count": 2, "notifications": [
    { "id": 16651, "kind": "auto_checkout", "message": "已自動離座：椅子 10 分鐘沒有偵測到人，回來後請重新入座", "timestamp": "...", "is_sent": false },
    { "id": 16650, "kind": "posture", "message": "坐姿提醒：身體左傾", "timestamp": "2026-10-18T08:42:33Z", "is_sent": false } ] }
```

| `kind` | 意思 | App 要做什麼 |
|---|---|---|
| `posture` | 坐姿提醒 | 照常顯示（椅子自己會震動，App 不用另外處理） |
| `auto_checkout` | 自動離座：椅子連續 10 分鐘沒人（或椅子離線） | ① 跳出系統通知（見下）② 使用者回到 App 時詢問「要重新入座嗎？」，按下去呼叫 `POST /chair/checkin` |
| `weekly` | 每週坐姿報告 | 照常顯示 |

**跳出系統通知**（App 開著時，輪詢讀到新的 `auto_checkout` 通知就跳出）：
- 網頁版：瀏覽器內建通知（Notification API，第一次需要使用者允許）
- iOS：本機通知（例如 flutter_local_notifications）
- App 關著時的推播（Web Push／APNs）之後再做

通知沒有 `posture` 欄位，坐姿名稱寫在 `message` 裡。

---

## 五、錯誤格式

| 情況 | 格式 | 可以直接顯示的欄位 |
|---|---|---|
| 欄位格式錯誤 | `{"schema_error": "..."}`（400） | — |
| 帳號／密碼相關 | `{"success": false, "error_code": "...", "message": "..."}` | `message` |
| 椅子、AI、校正相關 | `{"error": "..."}` | `error` |
| 沒登入或 Token 錯 | `{"detail": "..."}`（401） | — |

`error_code` 可能值：`USER_NOT_FOUND`、`INVALID_PASSWORD`、`ACCOUNT_EXISTS`、`EMAIL_MISMATCH`、`INVALID_CODE`、`EMAIL_SEND_FAILED`
