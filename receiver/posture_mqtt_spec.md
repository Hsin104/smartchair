# MQTT 後端資料說明（椅墊姿態版）

## 1. Topic
- `chair/pressure/01`
  - 每 0.5 秒發布一次，內容為目前座墊壓力與姿態摘要。
- `chair/vibration/01/cmd`
  - 由後端或測試端發送 vibration 指令，ESP32 解析並執行。
- `chair/vibration/01/ack`
  - ESP32 回應命令是否被接受、排程成功。
- `chair/vibration/01/state`
  - ESP32 發送最新馬達狀態。
- `chair/vibration/01/status`
  - ESP32 發送系統狀態、電源狀態與警示事件。

## 2. `chair/pressure/01` 封包格式

```json
{
  "device_id": "chair_01",
  "ts": 1729660000,
  "raw": [0, 12, 30, 20, 60, 50, 65, 70, 10, 8, 5],
  "norm": [0, 12, 30, 20, 60, 50, 65, 70, 10, 8, 5],
  "pose": {
    "label": "left_lean",
    "left_right_balance": -0.18,
    "front_back_balance": 0.04,
    "center_x": 0.46,
    "center_y": 0.62,
    "stability": 0.79,
    "confidence": 0.86,
    "total_pressure": 431.4,
    "left_total": 210.3,
    "right_total": 221.1,
    "front_total": 238.8,
    "back_total": 192.7
  },
  "sensor_detected": [true, true, true, true, true, true, true, true, true, true, true],
  "sensor_state": ["installed", "installed", "installed", "installed", "installed", "installed", "installed", "installed", "installed", "installed", "installed"],
  "power": {
    "pin": "VP(GPIO36)",
    "raw": 3150,
    "vp_v": 2.640,
    "voltage_v": 7.92,
    "battery_pct": 80,
    "battery_present": true
  }
}
```

## 3. 欄位說明

### raw / norm
- `raw`: 原始 ADC 值
- `norm`: 0~100 之間的標準化壓力值
- 共有 11 個數值，對應感測器 1~11

### pose
- `label`: 姿勢狀態
  - `normal`
  - `left_lean`
  - `right_lean`
  - `forward_lean`
  - `backward_lean`
  - `no_occupancy`
- `left_right_balance`: 左右偏移，範圍約 -1 ~ 1
  - 0: 左右平衡
  - < 0: 偏左
  - > 0: 偏右
- `front_back_balance`: 前後偏移，範圍約 -1 ~ 1
  - 0: 前後平衡
  - < 0: 偏前
  - > 0: 偏後
- `center_x` / `center_y`: 重心座標，0~1（x 小 = 左、y 小 = 後 / 靠椅背、y 大 = 前）
  - 可用於 UI 展示紅點位置
- `neutral_x` / `neutral_y`: 中立點（坐墊感測器平均受力時的重心），UI 圓環中心
- `normal_radius`: 重心距中立點小於此值判定 `normal`（UI 綠環半徑）；超出則依偏移較大的軸判定 `*_lean`
- `stability`: 穩定度，0~1（重心偏移達綠環半徑 3 倍時為 0）
  - 越接近 1 表示越穩定
- `confidence`: 判斷信心，0~1
- `total_pressure`: 總壓力
- `left_total` / `right_total` / `front_total` / `back_total`: 區域壓力總和

### power
- `raw`: VP(GPIO36) 平均 ADC 原始值（除錯用）
- `vp_v`: VP 腳實際電壓（分壓後）
- `voltage_v`: 由 ESP32 換算回分壓前的電池電壓（`vp_v` × 分壓比，已平滑）
- `battery_pct`: ESP32 依 `voltage_v` 在 6.0 V（0%）~ 8.4 V（100%）之間換算的電量百分比
- `battery_present`: 是否偵測到電池；`false` 時 `battery_pct` 為 0，不應視為沒電

## 4. 震動提醒事件

### `chair/vibration/01/ack`
- 當收到命令時，ESP32 會回應以下格式：

```json
{
  "device_id": "chair_01",
  "cmd_id": "single-20261023-160000",
  "status": "ok",
  "message": "scheduled"
}
```

### `chair/vibration/01/state`
- 回報目前馬達狀態：

```json
{
  "device_id": "chair_01",
  "event": "cmd_accepted",
  "cmd_id": "single-20261023-160000",
  "motors": [
    {"id":1,"pin":14,"running":true,"intensity":80,"remaining_ms":300},
    {"id":2,"pin":27,"running":false,"intensity":0,"remaining_ms":0}
  ]
}
```

## 5. 後端使用建議
- 不要直接使用 `raw` 做決策，應該使用 `pose` 和 `balance`。
- `pose.label` 可直接顯示在儀表板。
- `center_x` 與 `center_y` 可直接用於重心圖。
- `stability` 和 `confidence` 可用來判斷是否需要提示。
- `battery_pct` 可用於電量警告與保養提醒。

## 6. 震動提醒邏輯（已實作）
- `forward_lean` -> 馬達 1 和 4 震動
- `backward_lean` -> 馬達 2 和 3 震動
- `left_lean` -> 馬達 3 和 4 震動
- `right_lean` -> 馬達 1 和 2 震動
- 10 秒後第一次提醒，25 秒後第二次提醒，45 秒後第三次提醒
- 若姿勢恢復正常，提醒計時器會重置

## 7. 後端實作重點
- 先接 `chair/pressure/01`
- 只使用 `pose` 這層資料做 UI / 分析 / 提醒
- 非必要時不要處理 `raw` ADC
- 若有事件提報需求，可接 `chair/vibration/01/status`
