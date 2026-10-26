# 智慧感測椅 MQTT 資料說明

本文件說明 ESP32（`esp32_mqtt_ads1115.ino`）會透過 MQTT 傳送與接收哪些資料，以及每個欄位代表的意義。
後端、前端、demo 程式都以這份為準。

---

## 1. 整體架構

```text
 11 顆壓力感測器 ──► 3 顆 ADS1115 ──┐
 電池（2S 8.4V）──► 分壓 ──► VP 腳 ──┼──► ESP32 ──(WiFi / MQTT over TLS)──► MQTT Broker ──► 後端 / demo
 4 顆震動馬達 ◄──────────────────────┘        ▲                                     │
                                              └──────── 震動指令（cmd）◄────────────┘
```

ESP32 自己完成所有前處理：壓力標準化、重心計算、姿勢判定、電量換算、壞姿勢震動提醒。
**後端只需要讀結果，不需要再自己算。**

### 連線資訊

| 項目 | 值 |
|---|---|
| Broker | EMQX Cloud（位址見專案根目錄 `.env` 的 `MQTT_BROKER`） |
| Port | `8883`（TLS 加密） |
| 帳號密碼 | `.env` 的 `MQTT_USER` / `MQTT_PASS` |
| ESP32 Client ID | `esp32-chair-01` |
| 裝置 ID（payload 內） | `chair_01` |

---

## 2. Topic 一覽

| Topic | 方向 | 頻率 | 內容 |
|---|---|---|---|
| `chair/pressure/01` | ESP32 → 後端 | 每 0.5 秒 | **主要資料**：壓力、姿勢、重心、電量 |
| `chair/vibration/01/state` | ESP32 → 後端 | 每 1 秒＋狀態變化時 | 4 顆馬達目前狀態 |
| `chair/vibration/01/status` | ESP32 → 後端 | 事件發生時 | 系統事件（開機、硬體偵測、姿勢提醒、安全停機） |
| `chair/vibration/01/ack` | ESP32 → 後端 | 收到指令時 | 震動指令執行結果 |
| `chair/vibration/01/cmd` | 後端 → ESP32 | 後端需要時 | 手動控制震動馬達 |

> **只做資料顯示 / 分析的話，訂閱 `chair/pressure/01` 就夠了。**

### 共通欄位

每個 ESP32 發出的訊息都有：

| 欄位 | 型別 | 說明 |
|---|---|---|
| `device_id` | string | 固定 `"chair_01"` |
| `ts` | int | **ESP32 開機後經過的秒數**，不是真實時間（Unix time）。需要真實時間請以後端收到訊息的時間為準。ESP32 重開機會歸零。 |

---

## 3. 感測器與馬達位置

### 座標系統（俯視椅墊）

```text
              後（椅背）  y = 0
          ┌─────────────────────┐
          │ S8      S4      S1  │  y = 0.18
   左     │                     │     右
 x = 0    │ S7              S2  │  y = 0.42   x = 1
          │                     │
          │ S6      S5      S3  │  y = 0.72
          └─────────────────────┘
               前（膝蓋） y = 1
```

- **x**：0 = 左、1 = 右
- **y**：0 = 後（靠椅背）、1 = 前

### 壓力感測器

| 編號 | 位置 | 座標 (x, y) | 接線 |
|---|---|---|---|
| S1 | 坐墊 右後 | (0.82, 0.18) | ADS1 A0 |
| S2 | 坐墊 右中 | (0.82, 0.42) | ADS1 A1 |
| S3 | 坐墊 右前 | (0.82, 0.72) | ADS1 A2 |
| S4 | 坐墊 中後 | (0.50, 0.18) | ADS1 A3 |
| S5 | 坐墊 中前 | (0.50, 0.72) | ADS2 A0 |
| S6 | 坐墊 左前 | (0.18, 0.72) | ADS2 A1 |
| S7 | 坐墊 左中 | (0.18, 0.42) | ADS2 A2 |
| S8 | 坐墊 左後 | (0.18, 0.18) | ADS2 A3 |
| S9 | 椅背 左下 | (0.35, 0.10) | ADS3 A0 |
| S10 | 椅背 中 | (0.50, 0.05) | ADS3 A1 |
| S11 | 椅背 右下 | (0.65, 0.10) | ADS3 A2 |

> 姿勢與重心**只用坐墊 S1–S8 計算**；椅背 S9–S11 目前只有回傳數值，不參與判定。

### 震動馬達

| 編號 | 位置 | GPIO |
|---|---|---|
| M1 | 右前 | 14 |
| M2 | 右後 | 27 |
| M3 | 左後 | 26 |
| M4 | 左前 | 25 |

---

## 4. `chair/pressure/01`（主要資料）

### 範例

```json
{
  "device_id": "chair_01",
  "ts": 3625,
  "raw":  [9800, 12000, 15000, 8000, 14000, 13000, 11000, 9000, 2500, 2400, 2600],
  "norm": [41, 53, 70, 31, 64, 59, 48, 36, 1, 0, 1],
  "pose": {
    "label": "normal",
    "left_right_balance": 0.068,
    "front_back_balance": -0.282,
    "center_x": 0.517,
    "center_y": 0.500,
    "neutral_x": 0.500,
    "neutral_y": 0.443,
    "normal_radius": 0.070,
    "stability": 0.717,
    "confidence": 0.717,
    "total_pressure": 402.0,
    "left_total": 143.0,
    "right_total": 164.0,
    "front_total": 193.0,
    "back_total": 108.0
  },
  "sensor_detected": [true, true, true, true, true, true, true, true, true, true, true],
  "sensor_state": ["installed", "installed", "installed", "installed", "installed", "installed",
                   "installed", "installed", "installed", "installed", "installed"],
  "power": {
    "pin": "VP(GPIO36)",
    "raw": 3150,
    "vp_v": 2.640,
    "voltage_v": 7.920,
    "battery_pct": 80,
    "battery_present": true
  }
}
```

### 4.1 壓力值 `raw` / `norm`

兩個都是長度 11 的陣列，**索引 0 = S1、索引 10 = S11**。

| 欄位 | 範圍 | 說明 |
|---|---|---|
| `raw` | 0 ~ 32767 | ADS1115 原始讀值，除錯用 |
| `norm` | 0 ~ 100 | 標準化壓力：`(raw − 2400) / (20500 − 2400) × 100`，超出範圍會被夾在 0 或 100。**畫圖、分析請用這個** |

### 4.2 姿勢 `pose`

#### 判定方式

1. 用 S1–S8 的 `norm` 加權算出**重心** `(center_x, center_y)`。
2. 算出重心離**中立點** `(neutral_x, neutral_y)` 多遠。中立點 = 8 顆感測器平均受力時的重心。
3. 距離 < `normal_radius` → `normal`（demo 的綠環內）。
4. 超出時，比較左右偏移和前後偏移，**偏比較多的那個方向**就是結果。
5. S1–S8 的 `norm` 總和 < 8 → `no_occupancy`（沒人坐）。

#### 欄位

| 欄位 | 範圍 | 說明 |
|---|---|---|
| `label` | 見下表 | **目前姿勢，前端直接顯示這個** |
| `center_x` / `center_y` | 0 ~ 1 | 重心位置，座標見第 3 節 |
| `neutral_x` / `neutral_y` | 0 ~ 1 | 中立點（坐正時重心該在的位置），畫重心圖時當作圓心 |
| `normal_radius` | | 綠環半徑；重心與中立點距離小於此值即為 `normal` |
| `stability` | 0 ~ 1 | 穩定度。1 = 重心正好在中立點，0 = 偏移達綠環半徑 3 倍以上 |
| `confidence` | 0 ~ 1 | 目前與 `stability` 相同 |
| `left_right_balance` | −1 ~ 1 | 左右壓力比：`(右 − 左) / (左 + 右)`。**< 0 偏左、> 0 偏右** |
| `front_back_balance` | −1 ~ 1 | 前後壓力比：`(後 − 前) / (前 + 後)`。**< 0 偏前、> 0 偏後** |
| `total_pressure` | 0 ~ 800 | S1–S8 `norm` 總和 |
| `left_total` | 0 ~ 300 | S6 + S7 + S8 |
| `right_total` | 0 ~ 300 | S1 + S2 + S3 |
| `front_total` | 0 ~ 300 | S3 + S5 + S6 |
| `back_total` | 0 ~ 300 | S1 + S4 + S8 |

> `left_right_balance` / `front_back_balance` 是壓力比例，**只當參考**；姿勢判定以重心為準，所以偶爾會出現 balance 數值偏大但 `label` 仍是 `normal` 的情況，這是正常的。

#### `label` 可能的值

| 值 | 意義 |
|---|---|
| `normal` | 坐姿正常 |
| `left_lean` | 重心偏左 |
| `right_lean` | 重心偏右 |
| `forward_lean` | 重心偏前（往前坐、駝背前傾） |
| `backward_lean` | 重心偏後（往後靠、癱坐） |
| `no_occupancy` | 沒人坐 |

### 4.3 感測器狀態

| 欄位 | 說明 |
|---|---|
| `sensor_detected` | 長度 11 的 bool 陣列：該感測器所在的 ADS1115 晶片是否有偵測到 |
| `sensor_state` | 長度 11 的字串陣列，值如下 |

| `sensor_state` 值 | 意義 |
|---|---|
| `installed` | 正常，曾經讀到有效壓力 |
| `detecting` | 開機後 15 秒內，還在判斷有沒有接 |
| `not_installed` | 15 秒內都沒讀到壓力且數值幾乎不動，判定沒接感測器 |
| `not_detected` | 對應的 ADS1115 晶片沒偵測到（I²C 接線問題） |

### 4.4 電量 `power`

電池為 2 顆 18650 串聯（滿電 8.4 V），經 10k + 10k / 10k 分壓（比值 3.0）接到 ESP32 VP 腳。
**電壓還原與百分比計算都在 ESP32 完成，後端直接用 `battery_pct` 即可。**

| 欄位 | 說明 |
|---|---|
| `pin` | 固定 `"VP(GPIO36)"` |
| `raw` | VP 腳 ADC 原始值（16 次平均），除錯用 |
| `vp_v` | VP 腳實際電壓（分壓後，約 2.0 ~ 2.8 V） |
| `voltage_v` | 換算回的**電池實際電壓**（`vp_v × 3.0`，已平滑） |
| `battery_pct` | 電量 %：6.0 V = 0%、8.4 V = 100%，線性換算 |
| `battery_present` | 是否偵測到電池。`false` 時 `battery_pct` 會是 0，**應顯示「未偵測到電池」而不是「沒電」** |

---

## 5. `chair/vibration/01/state`（馬達狀態）

```json
{
  "device_id": "chair_01",
  "ts": 3625,
  "event": "heartbeat",
  "cmd_id": "none",
  "motors": [
    {"id": 1, "pin": 14, "running": false, "intensity": 0,  "remaining_ms": 0},
    {"id": 2, "pin": 27, "running": true,  "intensity": 42, "remaining_ms": 120},
    {"id": 3, "pin": 26, "running": true,  "intensity": 42, "remaining_ms": 120},
    {"id": 4, "pin": 25, "running": false, "intensity": 0,  "remaining_ms": 0}
  ]
}
```

| 欄位 | 說明 |
|---|---|
| `event` | 這筆狀態為什麼被送出，見下表 |
| `cmd_id` | 觸發的指令 ID；不是指令觸發時為 `"none"` |
| `motors[].running` | 是否正在震動 |
| `motors[].intensity` | 震動強度 0 ~ 100（%） |
| `motors[].remaining_ms` | 還剩幾毫秒停止 |

| `event` 值 | 時機 |
|---|---|
| `boot` | 連上 MQTT 時 |
| `heartbeat` | 每 1 秒定時回報 |
| `motor_changed` | 任一馬達開始或停止 |
| `cmd_accepted` | 收到並排程了震動指令 |
| `stop_all` | 收到全部停止指令 |
| `safety_timeout` | 安全停機（見第 6 節） |

---

## 6. `chair/vibration/01/status`（系統事件）

### 一般事件

```json
{"device_id": "chair_01", "ts": 3625, "event": "posture_reminder", "message": "forward_lean"}
```

| `event` | `message` | 說明 |
|---|---|---|
| `mqtt_connected` | `subscribed_vibration_command_topic` | ESP32 連上 MQTT |
| `posture_reminder` | 姿勢 label，例如 `forward_lean` | 壞姿勢已持續 10 秒以上。**注意：此狀態期間每 0.5 秒都會送一次，不代表每次都有震動** |
| `safety_timeout` | `stop_all_motors` | 超過 15 秒沒收到有效的震動指令，ESP32 自動停掉所有馬達（防止馬達卡在開啟狀態） |

### 硬體報告（連上 MQTT 時送一次）

```json
{
  "device_id": "chair_01",
  "ts": 5,
  "event": "hardware_report",
  "motor_detection_supported": false,
  "ads": {"ads1": true, "ads2": true, "ads3": true},
  "sensor_detected": [true, true, true, true, true, true, true, true, true, true, true],
  "motor_detected": ["unknown", "unknown", "unknown", "unknown"]
}
```

| 欄位 | 說明 |
|---|---|
| `ads.ads1` ~ `ads3` | 3 顆 ADS1115 是否有偵測到 |
| `sensor_detected` | 同第 4.3 節 |
| `motor_detection_supported` / `motor_detected` | 馬達沒有回授電路，無法偵測是否接上，固定為 `false` / `"unknown"` |

---

## 7. 自動姿勢提醒（ESP32 內建）

同一種壞姿勢持續一段時間，ESP32 會**自己**震動對應位置的馬達，不需要後端下指令。

| 姿勢 | 震動馬達 |
|---|---|
| `left_lean` | M3、M4（左側） |
| `right_lean` | M1、M2（右側） |
| `forward_lean` | M1、M4（前側） |
| `backward_lean` | M2、M3（後側） |

| 壞姿勢持續時間 | 強度 | 每次震動長度 |
|---|---|---|
| 10 ~ 25 秒 | 28% | 120 ms |
| 25 ~ 45 秒 | 42% | 170 ms |
| 45 秒以上 | 60% | 220 ms |

- 持續 10 秒後第一次提醒，之後**最快每 30 秒**再提醒一次。
- 坐回 `normal` 或離開座位，計時立即歸零。
- 換成另一種壞姿勢，也會重新計時。

---

## 8. `chair/vibration/01/cmd`（後端 → ESP32 震動指令）

### 格式 A：多顆馬達

```json
{
  "cmd_id": "test-001",
  "stagger_ms": 80,
  "motors": [
    {"id": 1, "intensity": 60, "duration_ms": 300},
    {"id": 4, "intensity": 60, "duration_ms": 300}
  ]
}
```

### 格式 B：單顆馬達

```json
{"cmd_id": "test-002", "motor_id": 2, "intensity": 50, "duration_ms": 500}
```

### 格式 C：全部停止

```json
{"cmd_id": "test-003", "stop_all": true}
```

| 欄位 | 範圍 | 說明 |
|---|---|---|
| `cmd_id` | 任意字串 | 自訂指令 ID，會原樣出現在 ack / state，方便對應。不給就是 `"no_cmd_id"` |
| `id` / `motor_id` | 1 ~ 4 | 馬達編號 |
| `intensity` | 0 ~ 100 | 強度 % |
| `duration_ms` | 50 ~ 5000 | 震動長度，超出會被夾到範圍內 |
| `stagger_ms` | 0 ~ 500，預設 80 | 多顆馬達時，依陣列順序每顆延遲這麼久才開始 |
| `stop_all` | `true` | 立即停止全部馬達 |

> ESP32 用簡易字串解析，**數字請給整數**（不要 `60.0`），也不要在 `motors` 裡放巢狀物件。

### 回應：`chair/vibration/01/ack`

```json
{"device_id": "chair_01", "ts": 3625, "cmd_id": "test-001", "status": "ok", "message": "scheduled"}
```

| `status` | `message` | 意義 |
|---|---|---|
| `ok` | `scheduled` | 指令已排程執行 |
| `ok` | `all_motors_stopped` | 已全部停止 |
| `error` | `no_valid_motor_command` | 指令格式錯誤或馬達編號不合法，沒有執行 |

---

## 9. 後端 / 前端使用建議

- **顯示姿勢**：直接用 `pose.label`。
- **重心圖**：以 `(neutral_x, neutral_y)` 為圓心、`normal_radius` 為綠環半徑，紅點畫在 `(center_x, center_y)`。紅點在綠環內 ⇔ `label == "normal"`，兩者保證一致。
- **壓力熱圖**：用 `norm` 搭配第 3 節座標。
- **電量**：用 `battery_pct`，並先檢查 `battery_present`。
- **時間**：`ts` 是開機秒數，記錄資料請用後端收到時的時間。
- **離線判斷**：超過 2 ~ 3 秒沒收到 `chair/pressure/01`，就視為裝置離線。
- `raw` 只拿來除錯，不要拿來做判斷。
