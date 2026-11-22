# 智慧感測椅 韌體與 MQTT 資料說明（v2）

本文件說明 ESP32 韌體（`esp32/esp32_mqtt_ads1115/esp32_mqtt_ads1115.ino`，版本 `2.0.0`）的硬體配置、椅子端行為，以及透過 MQTT 傳送／接收的所有資料。
給後端的精簡版見 `ESP32資料格式_給後端.md`。

---

## 1. 整體架構

```text
 11 顆壓力感測器 ──► 3 顆 ADS1115 ──┐
 電池（2S 8.4V）──► 分壓 ──► VP 腳 ──┼──► ESP32 ──(WiFi / MQTT over TLS)──► EMQX ──► 後端
 4 顆震動馬達（扶手、靠背）◄──────────┤        ▲                                   │
 2 條 LED 燈條（左右扶手）◄───────────┘        └──── 指令 / 中立點 / 校正 ◄─────────┘
```

ESP32 自己完成所有前處理：壓力平滑與標準化、重心、姿勢判定、久坐計時、震動提醒、LED 顯示、電量換算。
**椅子不需要網路也能完整運作**，網路只用來回報資料與接收設定。

### 雙核心分工

| 核心 | 工作 | 斷網時 |
|---|---|---|
| Core 1（Arduino `loop()`） | 感測器取樣 25 Hz、姿勢判斷、震動、久坐計時、LED | **照常運作** |
| Core 0（`netTask`） | WiFi／MQTT 連線、送資料、收指令、NTP、OTA | 每 5 秒重試 MQTT、每 20 秒重試 WiFi，卡住只影響這個核心 |

兩邊用 FreeRTOS queue 交換資料：

| Queue | 內容 | 滿了怎麼辦 | 斷網期間 |
|---|---|---|---|
| telemetry（4 筆） | pressure、馬達 state | 丟最舊的 | 只留最新幾筆，連線後送出 |
| event（24 筆） | status 事件、ack | 丟最新的 | **保留，連線後補送**（提醒紀錄不遺失） |
| in（8 筆） | 收到的指令 | 丟最新的 | — |

所有馬達、姿勢、計時狀態只由 Core 1 修改，MQTT 收到的指令都排進 queue 交給 Core 1 執行。

---

## 2. 硬體配置

### 2.1 腳位一覽

| 用途 | 腳位 |
|---|---|
| I²C（3 顆 ADS1115） | SDA 21、SCL 22 |
| 馬達 M1～M4 | 14、27、26、25 |
| LED 燈條 右扶手／左扶手 | 18、19 |
| 電池電壓 | VP（GPIO 36） |
| 狀態指示燈 | 2 |

### 2.2 壓力感測器安裝方式

- **坐墊 S1～S8**：直接貼在椅面上，上面再蓋一塊坐墊，避免感測器被衣物勾到或刮傷。
- **椅背 S9～S11**：椅背後方沒有硬的支撐，受力小，所以每顆感測器上面加一個**凸墊**集中壓力，韌體中 `adcMax` 也設得比坐墊低（見第 13 節）。

> 更換安裝方式或坐墊後，空椅與坐滿時的讀值會改變，`adcMin`／`adcMax` 需重新量測（見第 13 節）。

### 2.3 感測器座標（俯視椅墊）

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

椅背 S9～S11 沿椅背中線由下而上排列（S9 最下、S11 最上）。實體照片見 README。

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
| S9 | 椅背中線 下 | (0.50, 0.10) | ADS3 A0 |
| S10 | 椅背中線 中 | (0.50, 0.06) | ADS3 A1 |
| S11 | 椅背中線 上 | (0.50, 0.02) | ADS3 A2 |

ADS1115 位址：#1 `0x48`、#2 `0x49`、#3 `0x4A`；增益 `GAIN_ONE`，取樣率 860 SPS。
左右重心只用坐墊 S1–S8；前後重心另加入椅背 S9–S11（見 6.2）。

### 2.4 震動馬達

| 編號 | 位置 | GPIO |
|---|---|---|
| M1 | 右扶手 | 14 |
| M2 | 右靠背（腰部） | 27 |
| M3 | 左靠背（腰部） | 26 |
| M4 | 左扶手 | 25 |

### 2.5 LED 燈條

| 項目 | 規格 |
|---|---|
| 燈條 | WS2812B，左右扶手各一條，包覆扶手；每條 35 顆（`LEDS_PER_STRIP`） |
| 資料線 | 右扶手 GPIO 18、左扶手 GPIO 19，直接接燈條 DIN |
| 電源 | 吃電源模組輸出的 **5 V**，不由 ESP32 供電 |
| 共地 | 外接 5 V 的 GND、燈條 GND、ESP32 GND **必須接在一起**，否則資料訊號無法辨識 |
| 耗電 | 每條 35 顆、共 70 顆。加了 gamma 修正後，平常（基準 50%＝實際輸出 25%）約 **0.4 A**，最壞（全部 80%＝實際 64%）約 **1.0 A**；5 V 電源或降壓模組仍建議 **≥ 2 A**（留餘裕）。若 5 V 由 2S 電池降壓而來，燈條平常約吃掉電池 0.3 A，2500 mAh 電池可讓燈條單獨亮約 8 小時 |
| 電位 | ESP32 輸出 3.3 V，WS2812B 在 5 V 供電時要求高電位 ≥ 3.5 V，處在邊緣；若出現亂色或閃爍，資料線加一顆 74AHCT125 轉成 5 V |
| 燈條方向 | 燈條兩端 = 扶手後端，中段 = 扶手前端 |

### 2.6 電池

2 顆 18650 串聯（滿電 8.4 V），經 10k + 10k / 10k 分壓（比值 3.0）接 VP。6.0 V = 0%、8.4 V = 100%。

---

## 3. 連線資訊

| 項目 | 值 |
|---|---|
| Broker | EMQX Cloud（`secrets.h` 的 `MQTT_BROKER`） |
| Port | `8883`（TLS） |
| `device_id` | `chair_` ＋ WiFi MAC 後 6 碼，例如 `chair_A1B2C3`；**開機時印在序列埠，請貼在椅子上** |
| MQTT Client ID | `esp32-` ＋ 同 6 碼 |
| OTA 主機名 | `chair-` ＋ 同 6 碼（小寫） |
| Keep-alive | 15 秒 |
| 遺囑（LWT） | 斷線時 broker 自動在 `chair/{device_id}/online` 發 retained `{"device_id":"…","online":false}` |

量產燒同一份韌體即可，每張椅子的 ID 自動不同。

### 時間 `ts`

- 連上網路後會用 NTP 對時（UTC+8），之後 `ts` 為 **Unix 秒數**；對時後就算斷網也繼續有效。
- 開機後還沒對時成功（例如一開機就沒網路）時，`ts` 為**開機秒數**，並多一個 `"time_synced": false`。

---

## 4. Topic 一覽

| Topic | 方向 | 頻率 | 內容 |
|---|---|---|---|
| `chair/{id}/pressure` | ESP32 → 後端 | 有變動立即送，否則 5 秒（無人 30 秒） | **主要資料**：壓力、姿勢、重心、久坐、電量 |
| `chair/{id}/online` | ESP32 → 後端 | 上線／斷線時（retained） | 是否在線 |
| `chair/{id}/vibration/status` | ESP32 → 後端 | 事件發生時 | 系統事件、提醒、校正結果 |
| `chair/{id}/vibration/state` | ESP32 → 後端 | 馬達變化時＋每 30 秒 | 4 顆馬達狀態 |
| `chair/{id}/vibration/ack` | ESP32 → 後端 | 收到震動指令時 | 指令執行結果 |
| `chair/{id}/vibration/cmd` | 後端 → ESP32 | 需要時 | 手動控制馬達（測試用） |
| `chair/{id}/config` | 後端 → ESP32 | retained | 中立點設定 |
| `chair/{id}/calibration/cmd` | 後端 → ESP32 | 需要時 | 開始個人校正 |

所有 ESP32 發出的訊息都有 `device_id` 與 `ts`。

---

## 5. `chair/{id}/pressure`（主要資料）

### 5.1 範例

```json
{
  "device_id": "chair_A1B2C3",
  "ts": 1794556800,
  "seq": 812,
  "type": "change",
  "norm": [41, 53, 70, 31, 64, 59, 48, 36, 1, 0, 1],
  "pose": {
    "label": "normal",
    "left_right_balance": 0.068,
    "front_back_balance": -0.282,
    "center_x": 0.517, "center_y": 0.500,
    "neutral_x": 0.500, "neutral_y": 0.443,
    "normal_radius": 0.055,
    "stability": 0.717, "confidence": 0.717,
    "total_pressure": 402.0,
    "left_total": 143.0, "right_total": 164.0, "front_total": 193.0, "back_total": 108.0
  },
  "sitting": {"active": true, "seconds": 754, "limit_min": 30, "alert": false},
  "power": {"voltage_v": 7.920, "battery_pct": 80, "battery_present": true}
}
```

### 5.2 什麼時候送

| 類型 | 條件 |
|---|---|
| `change`（立即送） | 符合下列任一項 |
| | ① `pose.label` 改變（含坐下、離開） |
| | ② 任一感測器 `norm` 與上次送出相差 **≥ 10** |
| | ③ 有人坐時，重心與上次送出相差 **≥ 0.035**（綠環半徑的一半） |
| `sync`（定期送） | 距離上次送出滿 **5 秒**；沒人坐時 **30 秒** |
| 限速 | 兩筆之間至少 **0.5 秒** |

- ② 的門檻 10 來自後端分析的 21,353 筆真實資料：同一坐姿相鄰兩筆變化 95% 在 7 以內。
- ③ 是我們加的：重心慢慢移動時，壓力會分攤到好幾顆感測器，每顆變化都不到 10，但重心已經明顯移動（例如往左靠時 S6–S8 各 +6、S1–S3 各 −6）。③ 實際觸發的次數可能不多，**待實測決定是否保留**；`CHANGE_CENTER_DELTA` 設 0 即關閉。
- 測試方法：`DEBUG_RAW` 設 1，序列埠每筆會印出 `reason=label / norm / center / sync`，坐著做幾種動作後統計 `center` 出現的次數。
- 坐著不動時約 5 秒一筆；動來動去時最快每秒 2 筆。

### 5.3 欄位

| 欄位 | 說明 |
|---|---|
| `seq` | 每送一筆加 1。**重開機從 1 開始**；斷網期間沒送出的筆數會變成跳號 |
| `type` | `change` 或 `sync` |
| `norm` | 長度 11，索引 0 = S1。0～100，`(raw − adcMin) / (adcMax − adcMin) × 100`，已做 5 筆平均 |
| `pose` | 見第 6 節 |
| `sitting.active` | 是否在一段「坐著」期間（短暫離座 30 秒內仍為 `true`） |
| `sitting.seconds` | 這段坐了幾秒（包含短暫離座的時間） |
| `sitting.limit_min` | 久坐上限（分鐘） |
| `sitting.alert` | 是否已觸發久坐提醒、尚未起身 |
| `power` | **只在 `sync` 筆出現**；若一直有變動沒有 sync，最多 30 秒也會帶一次 |
| `power.battery_present` | `false` 時應顯示「未偵測到電池」，不是「沒電」 |

`DEBUG_RAW` 設為 1 時，另外附 `raw`（ADS1115 原始值 0～32767）與 `power.raw`、`power.vp_v`，並在序列埠印出。

---

## 6. 姿勢判定

### 6.1 取樣與防抖（debouncing）

| 步驟 | 做法 | 目的 |
|---|---|---|
| 取樣 | 每 40 ms（25 Hz）讀 11 顆感測器 | |
| 平滑 | 每顆感測器取**最近 5 次**讀值平均（約 0.2 秒） | 消除按下瞬間的暫態與雜訊 |
| 判定 | 用平滑後的 norm 算重心與即時姿勢 | |
| 確認 | 即時姿勢要**連續 1 秒都一樣**才更新 `pose.label` | 避免重心在綠環邊界時 label 來回跳 |

所以 `pose.label` 最多比實際動作晚約 1.2 秒；`center_x`／`center_y` 是即時值。在這 1 秒內，紅點可能已經出綠環但 label 還是 `normal`，屬正常現象。

### 6.2 判定方式

1. S1–S8 的 `norm` 總和 < 8 → `no_occupancy`
2. 算重心：`center_x` 用 S1–S8 加權；`center_y` 用 S1–S8 **加上椅背 S9–S11** 加權（往後靠時重量壓在椅背上，只看坐墊的話重心幾乎不會往後移）
3. 重心與中立點距離 < `normal_radius` → `normal`。各方向範圍不同：後仰 0.65 倍（最容易判定）、左右傾 0.8 倍、前傾 1.1 倍（最嚴格）
4. 否則比較左右與前後偏移，偏比較多的方向就是結果

可調參數：`BACKREST_Y_WEIGHT`（椅背在前後重心的權重，預設 1.5，0 = 只看坐墊）、`BACKWARD_RADIUS_SCALE`（後仰，預設 0.65）、`LATERAL_RADIUS_SCALE`（左右傾，預設 0.8）、`FORWARD_RADIUS_SCALE`（前傾，預設 1.1），倍率越小越容易判定。椅背 S9–S11 背後沒有支撐、受力小，`adcMax`：S9（下）、S11（上）為 14000，S10（中間）較難受力為 5000（坐墊為 20500）。

| `label` | 意義 |
|---|---|
| `normal` | 坐姿正常 |
| `left_lean` / `right_lean` | 重心偏左／偏右 |
| `forward_lean` | 重心偏前（前傾、駝背） |
| `backward_lean` | 重心偏後（後仰、癱坐） |
| `no_occupancy` | 沒人坐 |

### 6.3 其他 pose 欄位

| 欄位 | 說明 |
|---|---|
| `neutral_x` / `neutral_y` | 目前使用的中立點（預設為幾何中心 0.5、0.4425，可由後端設定，見第 10 節） |
| `normal_radius` | 綠環半徑，預設 0.055 |
| `stability` / `confidence` | 1 = 重心在中立點，0 = 偏移達綠環半徑 3 倍 |
| `left_right_balance` | `(右 − 左) / (左 + 右)`，< 0 偏左 |
| `front_back_balance` | `(後 − 前) / (前 + 後)`，< 0 偏前 |
| `total_pressure` | S1–S8 norm 總和 |
| `left_total` / `right_total` / `front_total` / `back_total` | S6+S7+S8 / S1+S2+S3 / S3+S5+S6 / S1+S4+S8 |

---

## 7. 久坐計時

| 規則 | 規格 |
|---|---|
| 開始計時 | `pose.label` 從 `no_occupancy` 變成有人坐 |
| 不中斷 | 換姿勢、挪動、**短暫起身（30 秒內回來）**都不中斷，離座時間也算在內 |
| 歸零 | 連續 **30 秒** `no_occupancy` 才算真的離開，送 `left_seat` 事件 |
| 觸發 | 坐滿 `SITTING_LIMIT_MIN` = **30 分鐘**（依 WHO 建議每 30～60 分鐘起身活動） |
| 震動 | 4 顆馬達依序（間隔 80 ms）各震 1.5 秒，強度 100% |
| 重複 | 還沒起身的話，每 **5 分鐘**再提醒一次 |
| 優先 | 與壞坐姿提醒同時成立時，先震久坐，壞坐姿延後 30 秒 |

> 久坐上限只要改 `SITTING_LIMIT_MIN` 一處；展示時可暫時改成 5。後端的久坐判定要用同一個值，椅子會在 `hardware_report` 和每筆 pressure 的 `sitting.limit_min` 回報目前設定。

---

## 8. 壞坐姿震動提醒

| 姿勢 | 震動馬達 | 用意 |
|---|---|---|
| `forward_lean` | M1、M4（兩側扶手） | 提醒抬頭 |
| `backward_lean` | M2、M3（兩側靠背） | 提醒坐直 |
| `left_lean` | M4、M3（左扶手＋左靠背） | 同側提醒 |
| `right_lean` | M1、M2（右扶手＋右靠背） | 同側提醒 |

| 壞姿勢持續時間 | 等級 | 強度 | 每次震動長度 |
|---|---|---|---|
| 10 ~ 25 秒 | 1 | 100% | 0.4 秒 |
| 25 ~ 45 秒 | 2 | 100% | 0.7 秒 |
| 45 秒以上 | 3 | 100% | 1 秒 |

- 持續 10 秒後第一次提醒，之後**最快每 30 秒**一次；坐回 `normal`、離座或換成另一種壞姿勢，重新計時。
- **只有真的震動時**才送 `posture_reminder` 事件。

### 安全停機

任一馬達連續開啟超過 6 秒（正常最長 5 秒），視為異常，立即停掉全部馬達並送 `safety_timeout`。

---

## 9. LED 燈條顯示

| 狀況 | 顏色 |
|---|---|
| 沒人坐（含短暫離座） | 全暗（省電） |
| 坐著，久坐進度 0% → 50% → 100% | 綠 → 琥珀 → 紅，漸變（紅＋綠總量固定，比經過亮黃色省一半電） |
| 久坐提醒觸發（30 分鐘，之後每 5 分鐘） | 與馬達震動同時**紅色閃爍 10 秒**（亮 0.5 秒、暗 0.5 秒），之後**紅色常亮**；直到起身離開 30 秒 |

**亮度跟著重心走**：基準 50%，最亮 80%、最暗 20%（避免耗電與元件過熱）。重心偏到綠環邊緣（剛好判定為傾斜）時就到最亮／最暗。

| 姿勢 | 左扶手 | 右扶手 |
|---|---|---|
| 左傾 | 整條變亮 | 整條變暗 |
| 右傾 | 整條變暗 | 整條變亮 |
| 前傾 | 中段（扶手前端）變亮、兩端變暗 | 同左 |
| 後傾 | 兩端（扶手後端）變亮、中段變暗 | 同左 |

左右與前後**可疊加**。以左前傾為例：左扶手中段 80%、右扶手中段與左扶手兩端約 50%、右扶手兩端 20%。

計算方式（每顆燈）：

```text
leanLeft  = −(center_x − neutral_x) / normal_radius，限制在 −1 ~ 1
leanFront =  (center_y − neutral_y) / normal_radius，限制在 −1 ~ 1
位置 p    = 燈在燈條上的位置：中段 +1、兩端 −1（線性）
s         = (左扶手 +leanLeft／右扶手 −leanLeft) + leanFront × p，限制在 −1 ~ 1
亮度      = 50% + s × 30%   → 20% ~ 80%（人眼感覺的亮度）
實際輸出  = 亮度²            → 4% ~ 64%（gamma 修正，基準 25%）
```

人眼對亮度是非線性的：PWM 直接從 50% 調到 80%，看起來只亮一點點。所以韌體先算「感覺亮度」，再平方成實際輸出，最亮和最暗差 16 倍，左右傾斜才看得出來。實際最大輸出 64%，也比原本更省電。坐正時（重心偏移在綠環半徑的一半以內）兩邊維持 50%，超過才開始漸變。調整參數：`LED_DEADZONE_RADII`（不反應區，預設 0.5 倍綠環半徑）、`LED_LEAN_FULL_RADII`（多偏才到極限，預設 1.0 倍綠環半徑）、`LED_GAMMA`（預設 2.0，越大對比越強）。

省電／省計算的做法：
- 每 100 ms 更新一次，重心變化先平滑，避免燈閃動
- 亮度由程式直接縮放顏色值，不使用 `setBrightness()`
- **畫面沒變化就不送資料給燈條**
- 開機自我測試：兩條燈條依序亮紅、綠、藍各 0.2 秒

### 狀態指示燈（GPIO 2）

| 狀態 | 顯示 |
|---|---|
| 開機 | 閃燈次數 = 偵測到的 ADS1115 數量 |
| MQTT 已連線 | 常亮 |
| 斷線中 | 每秒閃一次（椅子功能照常運作） |

---

## 10. 中立點設定與個人校正

### 10.1 `chair/{id}/config`（retained）

```json
{"cmd": "set_neutral",   "neutral_x": 0.5,    "neutral_y": 0.4266, "normal_radius": 0.055, "source": "user"}
{"cmd": "reset_neutral", "neutral_x": 0.5137, "neutral_y": 0.4043, "normal_radius": 0.055, "source": "fleet"}
```

- 兩種都直接套用，之後的姿勢、震動、LED 都用新值。
- `reset_neutral` 的值會記成「預設值」；`set_neutral` 是個人值。
- 範圍檢查：`neutral_x`／`neutral_y` 0.05～0.95、`normal_radius` 0.02～0.3，超出就拒絕（`config_rejected`）。
- **只存在 RAM**，不寫快閃記憶體；斷網開機用幾何中心（0.5、0.4425、0.055）。
- 使用個人值時，**連續 30 秒沒人坐會自動退回預設值**，並送 `neutral_reset`，避免下一個人用到前一個人的值。

### 10.2 `chair/{id}/calibration/cmd`

```json
{"cmd": "calibrate", "duration_s": 5, "request_id": "01a253e2-..."}
```

1. 收到後送 `calibration_started`，取樣 `duration_s` 秒（2～10 秒，25 Hz）
2. 超過 20% 的取樣沒人坐 → `calibration_failed`，`reason: "no_occupancy"`
3. 重心離平均位置超過 0.035 的取樣多於 5% → `calibration_failed`，`reason: "unstable"`
4. 成功 → `calibrated`，回報平均重心與 11 顆平均 norm；**椅子不自己改中立點**，等後端回送 `set_neutral`

---

## 11. `chair/{id}/vibration/status`（事件）

| `event` | 時機 | 其他欄位 |
|---|---|---|
| `mqtt_connected` | 連上 MQTT | `message` |
| `hardware_report` | 連上 MQTT | `fw`、`ads`、`sensor_detected`、`sensor_state`、`motor_layout`、`sitting_limit_min`、`sample_hz` |
| `sensor_state_changed` | 任一感測器狀態改變 | `sensor_detected`、`sensor_state` |
| `posture_reminder` | 壞坐姿震動時 | `message`（姿勢）、`motors`、`intensity`、`vibration_ms`、`level`、`duration_s`（壞坐姿已持續秒數） |
| `sedentary_reminder` | 久坐震動時 | `sitting_min`、`limit_min`、`motors`、`intensity` |
| `left_seat` | 離座滿 30 秒 | `sitting_min`、`sitting_s` |
| `config_applied` / `config_rejected` | 收到 config | `cmd`、中立點數值或 `reason` |
| `neutral_reset` | 離座後退回預設中立點 | `reason`、中立點數值 |
| `calibration_started` / `calibrated` / `calibration_failed` | 校正 | `request_id` 等 |
| `safety_timeout` | 馬達異常強制停機 | `message` |

`sensor_state` 的值：`installed`（正常）、`detecting`（開機 15 秒內判斷中）、`not_installed`（判定沒接）、`not_detected`（ADS1115 沒偵測到）。

---

## 12. 馬達狀態、手動指令、回應

### `chair/{id}/vibration/state`

```json
{"device_id": "chair_A1B2C3", "ts": 1794556800, "event": "motor_changed", "cmd_id": "none",
 "motors": [{"id": 1, "pin": 14, "running": true, "intensity": 42, "remaining_ms": 120}, ...]}
```

`event`：`boot`、`heartbeat`（每 30 秒）、`motor_changed`、`cmd_accepted`、`stop_all`、`safety_timeout`。

### `chair/{id}/vibration/cmd`（後端手動測試用；後端不會自動發震動）

```json
{"cmd_id": "test-001", "stagger_ms": 80, "motors": [{"id": 1, "intensity": 60, "duration_ms": 300}]}
{"cmd_id": "test-002", "motor_id": 2, "intensity": 50, "duration_ms": 500}
{"cmd_id": "test-003", "stop_all": true}
```

`intensity` 0～100、`duration_ms` 50～5000、`stagger_ms` 0～500。v2 改用 ArduinoJson 解析，數字可以是小數。

### `chair/{id}/vibration/ack`

```json
{"device_id": "chair_A1B2C3", "ts": 1794556800, "cmd_id": "test-001", "status": "ok", "message": "scheduled"}
```

`message`：`scheduled`、`all_motors_stopped`、`no_valid_motor_command`、`invalid_json`。

---

## 13. 可調參數與待辦

### 13.1 主要常數（都在 `.ino` 開頭）

| 常數 | 值 | 說明 |
|---|---|---|
| `SITTING_LIMIT_MIN` | 30 | 久坐上限（分鐘） |
| `SEDENTARY_REPEAT_MS` | 5 分鐘 | 久坐重複提醒間隔 |
| `LEAVE_RESET_MS` | 30 秒 | 離座多久算真的離開 |
| `SAMPLE_INTERVAL_MS` / `SMOOTH_N` | 40 ms / 5 | 取樣頻率 / 平均筆數 |
| `POSE_CONFIRM_MS` | 1000 | label 確認時間 |
| `OCCUPANCY_MIN_TOTAL` | 8 | 有人坐的壓力門檻 |
| `CHANGE_NORM_DELTA` / `CHANGE_CENTER_DELTA` | 10 / 0.035 | 「有變動」的定義 |
| `SYNC_INTERVAL_MS` / `SYNC_INTERVAL_EMPTY_MS` | 5 秒 / 30 秒 | 定期同步間隔 |
| `LEDS_PER_STRIP` | 35 | 每條燈珠數 |
| `LED_MIN_PCT` / `LED_BASE_PCT` / `LED_MAX_PCT` | 20 / 50 / 80 | 燈條亮度範圍 |
| `DEBUG_RAW` | 0 | 1 = 附帶 raw 並印在序列埠 |

### 13.2 改裝感測器後要做的事

1. `DEBUG_RAW` 設 1，從序列埠記下每顆感測器：**空椅時的 raw** → 填 `adcMin`；**用力坐滿時的 raw** → 填 `adcMax`
2. 確認空椅時 `total_pressure` 明顯低於 `OCCUPANCY_MIN_TOTAL`（8），坐下時明顯高於它；坐墊或凸墊預壓太大時要調高
3. 用真人測試門檻 10 / 0.035 是否合適，太敏感就調高
4. 若燈珠數不是 35，修改 `LEDS_PER_STRIP`

---

## 14. 給前端／後端的使用建議

- **顯示姿勢**：用 `pose.label`。
- **重心圖**：以 `(neutral_x, neutral_y)` 為圓心、`normal_radius` 為綠環半徑，紅點畫在 `(center_x, center_y)`。
- **電量**：保留最後一次收到的 `power`（不是每筆都有），先檢查 `battery_present`。
- **在線判斷**：用 `chair/{id}/online`（LWT），不要靠「多久沒收到 pressure」。坐著不動時 pressure 本來就 5 秒才一筆，沒人坐 30 秒一筆。
- **漏封包**：`seq` 跳號 = 漏了或斷網；`seq` 變小 = 椅子重開機。
- `raw` 只拿來除錯，不要拿來做判斷。
