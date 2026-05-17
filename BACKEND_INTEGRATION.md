# 前後端對接總結

## 已實現功能

### 1. 後端 API 對接

後端基礎 URL（可通過 `--dart-define=API_BASE_URL=https://sandbar-badass-subfloor.ngrok-free.dev/api` 設置）

#### 認證相關
- **POST /api/register** — 註冊新使用者（支援 username, password, email, height, weight）
- **POST /api/login** — 登入取得 Token
- **GET /api/me** — 獲取當前使用者資料
- **PATCH /api/me/update** — 更新身高、體重、Email

#### 坐姿數據
- **POST /api/posture** — 儲存坐姿感測數據（seat_pressure_data, back_pressure_data 或直接帶 posture）
- **GET /api/posture/history?limit=50** — 查詢坐姿歷史紀錄

#### AI 建議
- **POST /api/agent** — 查詢 Physio Agent 建議（posture, user_message）

#### 通知（馬達提醒）
- **GET /api/notification/pending** — 取得待處理的振動提醒通知
- **POST /api/notification/ack** — 確認通知已收到

### 2. 前端代碼變更

#### lib/services/api_service.dart
- ✅ `register()` 新增 `height` / `weight` 可選參數
- ✅ `updateMe()` — 新增方法調用 `PATCH /api/me/update`
- ✅ `saveUserSettings()` — 改由 `updateMe()` 處理

#### lib/screens/auth_page.dart
- ✅ 註冊頁面新增「身高 (cm)」輸入框（驗證範圍：50~250）
- ✅ 註冊頁面新增「體重 (kg)」輸入框（驗證範圍：20~300）
- ✅ 密碼確認欄位（確保密碼相符）
- ✅ 密碼顯示/隱藏切換（眼睛圖標）

#### lib/screens/setting.dart
- ✅ 本地儲存設定（SharedPreferences，含所有警告設置）
- ✅ 登入時同步身高、體重到後端 (`PATCH /api/me/update`)
- ✅ 本地警告設置（postureAlert, sedentaryAlert, vibrationAlert）保留在 SharedPreferences，不發送到後端
- ✅ 切換帳號時自動重新載入該帳號的設定

### 3. 資料同步流程

```
使用者註冊
  ↓ [身高、體重、Email、密碼]
  ↓
POST /api/register
  ↓ [response: token, user]
  ↓
儲存 token + email 至 SharedPreferences

使用者編輯設定 → 按「儲存設定」
  ↓
本地儲存 (SharedPreferences)：
  - height, weight（用於表單回填）
  - postureAlert, sedentaryAlert, vibrationAlert（本地偏好）
  ↓
若已登入：
  → PATCH /api/me/update { height, weight }
  ↓ [response: user 資料]
  ↓
顯示成功/失敗提示
```

### 4. 設定持久化

- **本地偏好**（不同帳號獨立儲存）：
  - 身高、體重（用於 UI 回填 + 後端同步）
  - 三種警告開關（本地使用，不同步後端）
  
- **帳號切換**：
  - 登出 A、登入 B → 自動載入 B 的設定
  - 多個帳號各自獨立

### 5. 身高/體重註冊驗證

- **身高**：50 ~ 250 cm（符合後端 REGISTER_SCHEMA）
- **體重**：20 ~ 300 kg（符合後端 REGISTER_SCHEMA）

---

## 待實現功能

### 1. 坐姿感測器數據接收
- ESP32 → 後端 (MQTT 或 HTTP)
- 後端 → 前端（Web 輪詢或 WebSocket）

### 2. AI 建議完整流程
- `ChairSyncController` 定期拉取最新坐姿
- 若非 normal，自動調用 `POST /api/agent` 取得建議
- UI 上顯示建議內容

### 3. 振動馬達通知
- `ChairSyncController` 定期拉取 `GET /api/notification/pending`
- 收到通知後在 UI 上顯示
- ESP32 需實現 `POST /api/notification/ack` 的對應邏輯

### 4. 報告頁面資料同步
- `report.dart` 目前使用模擬資料
- 需改為調用 `getPostureHistory()` 並繪製真實圖表

---

## 啟動方式

```powershell
# 從 VS Code 終端或 PowerShell 執行
.\scripts\start_web.ps1 -FixedPort 7357 -ApiBaseUrl "https://sandbar-badass-subfloor.ngrok-free.dev/api"
```

或不固定埠（自動分配）：
```powershell
.\scripts\start_web.ps1 -ApiBaseUrl "https://sandbar-badass-subfloor.ngrok-free.dev/api"
```

---

## 測試建議

1. **註冊流程**
   - 開啟應用 → 前往註冊
   - 填入帳號、Email、密碼（確認）、身高、體重
   - 按「註冊」應顯示成功並跳轉回首頁

2. **設定同步**
   - 登入後進入設定頁
   - 修改身高、體重、警告開關
   - 按「儲存設定」應同步到後端
   - 刷新頁面或重啟應用，設定應仍存在（本地 + 後端）

3. **切換帳號**
   - 登出 A、登入 B
   - B 的設定應自動載入（若之前已保存）

---

## 後端期望的請求格式

### 註冊
```json
POST /api/register
{
  "username": "testuser",
  "password": "password123",
  "email": "test@example.com",
  "height": 170,
  "weight": 65
}
```

### 更新用戶資料
```json
PATCH /api/me/update
{
  "height": 172,
  "weight": 68,
  "email": "newemail@example.com"  // 可選
}
```

---

## 後續改進方向

1. **實時通知**：改用 WebSocket 推送而非輪詢
2. **離線支持**：設定離線時快取，上線後同步
3. **多語言**：UI 文本國際化
4. **深色模式**：跟隨系統設置
