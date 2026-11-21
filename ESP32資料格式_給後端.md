# 椅子端資料格式 v2（回覆 esp32_spec_v2）

> 給：陳翊昕　from：蕭芷萱　韌體版本 `2.0.0`
> v2 清單第 1～7、9 項都已做進韌體；第 8 項 LED 改成我們自己的設計（只在椅子上顯示，不影響資料）。下面只列你需要知道的資料格式與跟你規格不一樣的地方。

---

## 一、跟你規格不同、需要你配合的地方

| 項目 | 你的規格 | 椅子實際做法 | 請你 |
|---|---|---|---|
| 久坐上限 | 5 分鐘 | **30 分鐘**（WHO 建議，正式值）；展示時可能暫改 5 | 從 `hardware_report.sitting_limit_min` 或 pressure 的 `sitting.limit_min` 讀，不要寫死 |
| 離線判斷 | 15 秒沒收到 pressure | 改用 **MQTT 遺囑（LWT）**，見第三節 | 訂閱 `chair/+/online` |
| 「有變動」的定義 | label 變或 norm 差 ≥ 10 | 另加：**重心移動 ≥ 0.035** | 不用改，知道就好 |
| 取樣頻率 | 50 Hz | **25 Hz**（校正 5 秒約 125 筆） | 不用改 |
| 馬達狀態心跳 | 每 1 秒 | **每 30 秒**＋有變化時 | 不要拿 state 判斷在線 |
| 中立點 | 椅子收到就一直用 | 個人值在**連續 30 秒沒人坐後自動退回預設值** | 見第五節，使用者再坐下時請重送 `set_neutral` |
| 舊 topic | 新舊都收 | 韌體**只用新 topic** `chair/{device_id}/…` | 舊 topic 可以等不再需要時移除 |

### 馬達位置（回覆第四節）

馬達實際裝在**扶手和靠背**，跟 7 月的規劃一樣，不會改裝；之前文件寫成「椅墊四角」是我標錯了。編號跟你原本的規劃不同，但你現在暫用的對應表剛好正確，**請直接定案**：

| 馬達 | 位置 |
|---|---|
| M1 | 右扶手 |
| M2 | 右靠背（腰部） |
| M3 | 左靠背（腰部） |
| M4 | 左扶手 |

| 坐姿 | 震動 |
|---|---|
| 前傾 | M1＋M4（兩側扶手） |
| 後仰 | M2＋M3（兩側腰部） |
| 左傾 | M4＋M3（左扶手＋左腰） |
| 右傾 | M1＋M2（右扶手＋右腰） |
| 久坐 | M1～M4 全部 |

---

## 二、Topic

`{device_id}` = `chair_` ＋ WiFi MAC 後 6 碼，例如 `chair_A1B2C3`（每張椅子自動不同）。

| Topic | 方向 | 內容 |
|---|---|---|
| `chair/{id}/pressure` | 椅子 → 後端 | 主要資料 |
| `chair/{id}/online` | 椅子 → 後端 | 在線狀態（retained） |
| `chair/{id}/vibration/status` | 椅子 → 後端 | 事件（提醒、校正結果、硬體報告…） |
| `chair/{id}/vibration/state` | 椅子 → 後端 | 馬達狀態 |
| `chair/{id}/vibration/ack` | 椅子 → 後端 | 手動指令回應 |
| `chair/{id}/vibration/cmd` | 後端 → 椅子 | 手動震動（格式 A／B／C 不變） |
| `chair/{id}/config` | 後端 → 椅子 | 中立點（retained） |
| `chair/{id}/calibration/cmd` | 後端 → 椅子 | 開始校正 |

所有椅子送出的訊息都有 `device_id` 與 `ts`。`ts` 在 NTP 對時成功後是 **Unix 秒數**；如果開機後一直沒對時成功，會是開機秒數並多一個 `"time_synced": false`，這時請用收到的時間。

---

## 三、在線判斷（LWT）

- 椅子連線時：`chair/{id}/online` ← `{"device_id":"chair_A1B2C3","online":true,"fw":"2.0.0"}`（retained）
- 椅子斷線（含斷電、斷網）：broker 在約 **20～25 秒內**（keep-alive 15 秒 × 1.5）自動發 `{"device_id":"chair_A1B2C3","online":false}`（retained）

因為是 retained，後端一訂閱就知道每張椅子目前在不在線。

---

## 四、`chair/{id}/pressure`

```json
{
  "device_id": "chair_A1B2C3",
  "ts": 1794556800,
  "seq": 812,
  "type": "change",
  "norm": [41, 53, 70, 31, 64, 59, 48, 36, 1, 0, 1],
  "pose": {
    "label": "normal",
    "left_right_balance": 0.068, "front_back_balance": -0.282,
    "center_x": 0.517, "center_y": 0.500,
    "neutral_x": 0.500, "neutral_y": 0.443, "normal_radius": 0.055,
    "stability": 0.717, "confidence": 0.717,
    "total_pressure": 402.0,
    "left_total": 143.0, "right_total": 164.0, "front_total": 193.0, "back_total": 108.0
  },
  "sitting": {"active": true, "seconds": 754, "limit_min": 30, "alert": false},
  "power": {"voltage_v": 7.920, "battery_pct": 80, "battery_present": true}
}
```

### 4.1 傳送頻率

| 類型 | 條件 |
|---|---|
| `change` | `pose.label` 改變（含坐下／離開）、任一 `norm` 與上次送出差 ≥ 10、或有人坐時重心移動 ≥ 0.035 |
| `sync` | 距離上次送出滿 **5 秒**（沒人坐 **30 秒**） |
| 限速 | 兩筆至少間隔 **0.5 秒**（最快每秒 2 筆） |

實際大約：坐著不動 5 秒一筆、動來動去每秒 1～2 筆、沒人坐 30 秒一筆。

### 4.2 欄位解讀

| 欄位 | 說明 |
|---|---|
| `seq` | 每筆加 1。**跳號** = 漏封包或斷網期間沒送；**變小** = 椅子重開機（從 1 開始） |
| `norm` | 長度 11，索引 0 = S1 … 10 = S11，0～100，已做平滑。順序與座標跟之前一樣 |
| `pose.label` | `normal`／`left_lean`／`right_lean`／`forward_lean`／`backward_lean`／`no_occupancy`。需連續 1 秒相同才會改變，所以比動作晚約 1 秒 |
| `pose.center_*` | 即時重心（0～1，x 小 = 左，y 小 = 後）。`center_x` 只算坐墊；`center_y` 連椅背 S9～S11 一起算（往後靠才判得出後仰）。判定範圍是綠環半徑乘上各方向倍率：後仰 0.6、左右傾 0.8、前傾 1.1。label 有 1 秒確認期，這段時間紅點出了綠環、label 仍是 `normal` 屬正常 |
| `pose.neutral_*`、`normal_radius` | 椅子目前使用的中立點，可以拿來確認你送的 `set_neutral` 有沒有生效 |
| 其他 `pose` 欄位 | 意義與之前相同 |
| `sitting.active` | 是否在一段坐著的期間（短暫離座 30 秒內仍算） |
| `sitting.seconds` | 這段坐了幾秒（含短暫離座時間），App 可以直接顯示 |
| `sitting.limit_min` | 椅子的久坐上限 |
| `sitting.alert` | 已觸發久坐提醒、還沒起身 |
| `power` | **只在 `sync` 筆出現**（一直有變動時最多 30 秒也會帶一次）。請保留最後一次的值。`battery_present: false` 要顯示「未偵測到電池」而不是「沒電」 |

已移除：`raw`、`sensor_detected`、`sensor_state`（移到 status 事件）、`power.pin`／`power.raw`／`power.vp_v`。

---

## 五、中立點與校正

格式照你的規格，補充以下幾點：

- `config` 收到 `set_neutral`／`reset_neutral` 都直接套用，回 `config_applied`；數值超出範圍（中立點 0.05～0.95、半徑 0.02～0.3）或格式錯誤時回 `config_rejected` 並附 `reason`。
- 不寫入快閃記憶體；斷網開機用幾何中心 (0.5, 0.4425, 0.055)。`set_neutral` 的 `normal_radius` 建議也用 0.055（原本 0.07 實測範圍太大）。
- **個人值的有效期**：連續 30 秒沒人坐，椅子會自動退回最後一次收到的 `reset_neutral` 值（沒收過就用幾何中心），並送 `neutral_reset` 事件。

  **請你配合**：
  1. 收到 `left_seat` 或 `neutral_reset` 後，把 `chair/{id}/config` 的 retained 換成 `reset_neutral`，不然椅子重開機會拿到上一個人的值。
  2. 同一個使用者再坐下時（pressure 的 label 從 `no_occupancy` 變成有人坐），重送一次 `set_neutral`。

- 校正：取樣 `duration_s` 秒（2～10）。超過 20% 的取樣沒人坐回 `no_occupancy`；重心離平均位置 > 0.035 的取樣超過 5% 回 `unstable`（不會因為單一雜訊點失敗）。開始時會先送 `calibration_started`。

```json
{"event": "calibration_started", "request_id": "01a253e2-...", "duration_s": 5}
{"event": "calibrated", "request_id": "01a253e2-...", "neutral_x": 0.5012, "neutral_y": 0.4266,
 "norm_avg": [52, 50, 44, 48, 42, 44, 50, 52, 25, 27, 27], "samples": 125, "stable_pct": 98}
{"event": "calibration_failed", "request_id": "01a253e2-...", "reason": "unstable", "stable_pct": 81}
```

---

## 六、事件 `chair/{id}/vibration/status`

斷網期間發生的事件會暫存（最多 24 筆），連線後補送，所以**同一時間可能一次收到好幾筆舊事件**，請以 `ts` 為準。

| `event` | 時機 | 主要欄位 |
|---|---|---|
| `posture_reminder` | 壞坐姿**真的震動時**（最快每 30 秒） | `message`（姿勢）、`motors`、`intensity`、`vibration_ms`、`level`（1～3）、`duration_s`（壞坐姿已持續秒數） |
| `sedentary_reminder` | 久坐震動時（之後每 5 分鐘） | `sitting_min`、`limit_min`、`motors`、`intensity` |
| `left_seat` | 離座滿 30 秒（久坐計時歸零） | `sitting_min`、`sitting_s`（這次坐了多久） |
| `hardware_report` | 每次連上 MQTT | `fw`、`ads`、`sensor_detected`、`sensor_state`、`motor_layout`、`sitting_limit_min`、`sample_hz` |
| `sensor_state_changed` | 感測器狀態改變 | `sensor_detected`、`sensor_state` |
| `mqtt_connected` | 連上 MQTT | — |
| `config_applied` / `config_rejected` / `neutral_reset` | 中立點 | 見第五節 |
| `calibration_started` / `calibrated` / `calibration_failed` | 校正 | 見第五節 |
| `safety_timeout` | 馬達異常開太久被強制停機 | — |

範例：

```json
{"device_id": "chair_A1B2C3", "ts": 1794556800, "event": "posture_reminder",
 "message": "forward_lean", "motors": [1, 4], "intensity": 100, "vibration_ms": 700, "level": 2, "duration_s": 25}
{"device_id": "chair_A1B2C3", "ts": 1794558600, "event": "sedentary_reminder",
 "sitting_min": 30, "limit_min": 30, "motors": [1, 2, 3, 4], "intensity": 100, "vibration_ms": 1500}
```

`posture_reminder` 的 `duration_s` 依你的範例，指的是**壞坐姿已持續的秒數**；馬達震動長度另外放在 `vibration_ms`。

---

## 七、馬達 state／cmd／ack

格式不變，只有兩點：
- `state` 心跳改成每 30 秒（馬達變化時仍立即送）
- `cmd` 改用正式 JSON 解析，數字可以是小數；格式錯誤會回 `{"status":"error","message":"invalid_json"}`
