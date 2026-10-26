# ESP32 韌體修改清單 v2（對照 MQTT資料說明.md）

> 給：蕭芷萱　from：陳翊昕　2026-10-26
> 你的 `MQTT資料說明.md` 已經做到很多教授要的「椅子端前處理」，這份**只列還需要改的地方**，其他維持你現在的設計。
> **你只需要看這份**：以你現在的韌體（`MQTT資料說明.md`）為基礎，加上這份清單的修改即可。先前給你的 `esp32_protocol_proposal.md`（v1）已被這份取代，裡面的問題不用回答。

---

## 一、你已經完成、維持不變的

- 椅子端用重心判斷坐姿（`pose.label`）、斷網也能自動震動提醒（強度隨時間加強、每 30 秒最多一次）
- `norm` 0～100、感測器順序 S1～S11（跟後端一致）
- 感測器安裝狀態、電量、硬體報告、馬達狀態與 ack、震動指令格式 A／B／C、15 秒安全停機

## 二、後端已經配合你改好的（不用你動）

| 項目 | 改法 |
|---|---|
| 震動 | **後端不再自動發任何震動指令**，所有震動（壞坐姿＋久坐）都由椅子負責，不會重複震、斷網也能用 |
| 馬達位置 | 後端手動觸發（測試用）的對應**暫時**改成跟你現在的一致：左傾 M3+M4、右傾 M1+M2、前傾 M1+M4、後仰 M2+M3（等你回覆第五節再定案） |
| `pose.label` | 後端會存起來（轉成 `left`／`right`／`forward`／`recline`／`empty`），跟雲端 AI 模型的判斷做對照 |

---

## 三、還需要改的（依優先順序）

### 1. 有變動才傳＋固定週期同步（教授 10/19 指定）

`chair/pressure/01` 目前每 0.5 秒固定送一次，改成：

| 什麼時候送 | 條件 |
|---|---|
| **有變動，立即送** | `pose.label` 改變（含坐下／離開）、或任一 `norm` 跟上次送出的值相差 **≥ 10** |
| **定期同步** | 距離上次送出滿 **5 秒**（`no_occupancy` 時放寬為 **30 秒**） |
| **限速** | 兩筆之間至少 **0.5 秒** |

- 門檻 10 的依據：遠端資料庫 21,353 筆真實資料，同一坐姿相鄰兩筆的變化 95% 在 7 以內、99% 在 20 以內
- 同步 5 秒的依據：後端坐姿模型實測上限每秒約 90 筆，5 秒一筆約可支撐 450 張椅子；每 0.5 秒一筆只能撐約 45 張
- 請在 payload 加 `"type": "change"` 或 `"type": "sync"`，以及每送一筆加 1 的 `"seq"`（後端用來發現漏封包）
- 你文件第 9 節的「超過 2～3 秒沒收到就算離線」要改成「**超過 15 秒**（3 個同步週期）沒收到才算離線」

### 2. 久坐提醒（新增，斷網也要能用）

目前韌體只有「壞坐姿」提醒，**沒有久坐提醒**。後端已不再發震動，所以久坐提醒必須在椅子上做，斷網時才能照常運作。

| 規則 | 規格 |
|---|---|
| 開始計時 | `pose.label` 從 `no_occupancy` 變成有人坐 |
| 觸發 | 連續坐滿 **`SITTING_LIMIT_MIN` 分鐘**，設定為 **5**（與後端久坐判定一致；請做成一個常數，之後要調整只改一處） |
| 震動 | 4 顆馬達全部震（格式 A，`stagger_ms` 80），強度 60%、每顆 300 ms |
| 重複 | 還沒起身的話，之後每 **5 分鐘**再提醒一次 |
| 歸零 | 連續 **60 秒**都是 `no_occupancy` 才算真的起身離開（挪一下屁股、短暫離座不算） |
| 回報 | 震動時送 `status`：`{"event": "sedentary_reminder", "sitting_min": 30}` |
| 優先順序 | 久坐提醒跟壞坐姿提醒同時成立時，先震久坐，壞坐姿提醒延後到下一次 |

說明：知識庫（WHO 指引）建議每靜態久坐 30～60 分鐘中斷一次；本專題目前設 5 分鐘，方便展示與測試時看得到效果，後端與椅子端兩邊必須用同一個值。

### 3. 支援多張椅子（量產需求）

目前 `device_id`、Topic、Client ID 都寫死 01，第二張椅子接上會混在一起；而且 **EMQX 不允許兩台用同一個 Client ID**，兩張椅子會互相把對方踢下線。

| 項目 | 改成 |
|---|---|
| `device_id` | `chair_` ＋ WiFi MAC 後 6 碼，例如 `chair_A1B2C3`（每張自動不同，量產燒同一份韌體） |
| Client ID | `esp32-` ＋ 同樣的 MAC 後 6 碼 |
| Topic | 把 `01` 換成 device_id：`chair/{device_id}/pressure`、`chair/{device_id}/vibration/state`、`…/status`、`…/ack`、`…/cmd` |

開機時在序列埠印出 device_id，方便貼標籤。後端下週會支援新 topic，**過渡期新舊 topic 都收**，你可以先改、不用等後端。

### 4. 精簡每筆資料

| 欄位 | 改成 |
|---|---|
| `raw` | 拿掉（只除錯用，可以用編譯開關保留） |
| `sensor_detected`、`sensor_state` | 只放在開機的 `hardware_report`，以及狀態改變時送一次 |
| `power` | 只放在 `sync` 那筆就好（電量不會幾秒內改變） |
| `pose` | 保留 |

### 5. `posture_reminder` 不要每 0.5 秒送

目前壞坐姿期間每 0.5 秒都送一次。改成**真的震動那一次才送**（也就是最快每 30 秒一次），並帶上震了哪幾顆馬達與強度，例如：

```json
{"device_id": "chair_A1B2C3", "ts": 3625, "event": "posture_reminder",
 "message": "forward_lean", "motors": [1, 4], "intensity": 42, "duration_s": 25}
```

後端會記錄成「這次提醒」，App 也能顯示「椅子剛剛提醒過你」。

### 6. 在文件補上 debouncing 做法

教授特別提到感測器按下瞬間的暫態。請在文件寫明你怎麼處理，建議做法：
- 每顆感測器保留最近 5 次讀值取平均再算重心
- `pose.label` 要連續 **1 秒**都一樣才更新（避免在綠環邊界來回跳）

### 7.（加分）LED 燈條

教授 10/19 建議：斷網或後端掛掉時，椅子本身仍要有看得到的提示。震動是「提醒」，LED 是「隨時看得到的狀態」，兩者互補。

#### 7-1 硬體

| 項目 | 規格 |
|---|---|
| 燈條 | WS2812B（NeoPixel）8 顆，只需 1 條資料線就能個別控制每顆顏色 |
| 資料腳位 | 建議 **GPIO 13**：避開你文件中的馬達 14／27／26／25、電量 VP=36，以及 ESP32 預設 I²C 的 21／22（如果你的 ADS1115 不是接 21／22，請以實際接線為準），也避開開機用腳位 0／2／12／15。請再確認 GPIO 13 沒有被其他東西用到 |
| 電源 | WS2812B 要 **5 V**：2S 電池（6～8.4 V）先經一顆 5 V 降壓模組再接燈條，**不可直接接電池，也不可接 ESP32 的 3.3 V** |
| 保護 | 資料線串一顆 330 Ω 電阻；燈條 5 V 與 GND 之間並一顆 1000 µF 電容；燈條、降壓模組、ESP32 **共地** |
| 安裝位置 | 扶手前緣或椅墊前緣，坐著時眼角餘光看得到 |
| 耗電 | 亮度設 25% 時 8 顆約 120 mA；沒人坐時只留 1 顆狀態燈，避免耗電 |

#### 7-2 燈號配置

```text
 [1][2][3][4][5][6][7]   [8]
 └──── 坐姿＋血條 ────┘   狀態燈
```

- **第 1～7 顆：坐姿顏色＋久坐「血條」**
- **第 8 顆：連線與電量狀態燈**

#### 7-3 第 1～7 顆：顏色代表坐姿，亮幾顆代表還能坐多久

**顏色**（依優先順序，上面的狀況成立就不看下面）：

| 狀況 | 顯示 |
|---|---|
| 沒人坐（`no_occupancy`） | 全暗 |
| 久坐時間到（第 2 項的 `SITTING_LIMIT_MIN`） | 7 顆**紅色慢閃**（亮 0.5 秒、暗 0.5 秒），直到起身離開 60 秒 |
| 壞坐姿持續 ≥ 10 秒（跟震動提醒同步開始） | 紅色常亮 |
| 壞坐姿未滿 10 秒 | 黃色常亮 |
| `normal` | 綠色常亮 |

**血條（亮幾顆）**：剛坐下時 7 顆全亮，之後每過 `SITTING_LIMIT_MIN ÷ 7` 分鐘熄 1 顆（5 分鐘時約每 43 秒熄 1 顆），全部熄滅的那一刻就是久坐提醒觸發。起身離開滿 60 秒後重新從 7 顆開始。

→ 使用者一眼就能看到「坐姿對不對」（顏色）和「還能坐多久」（顆數），類似遊戲的血條。

#### 7-4 第 8 顆：狀態燈

| 狀況（依優先順序） | 顯示 |
|---|---|
| 電量 < 20%（且 `battery_present` 為 true） | 橘色閃爍（每 2 秒閃一下） |
| WiFi 或 MQTT 斷線 | **藍色閃爍**（每秒閃一下）——斷網時坐姿燈、震動、久坐提醒照常運作 |
| 連線正常 | 綠色微亮（亮度 10%） |

#### 7-5 其他規則

- **開機自我測試**：開機時 8 顆依序亮紅→綠→藍各一次（約 1 秒），確認每顆燈都正常
- **震動時**：馬達震動的那一刻，第 1～7 顆白色閃一下（0.1 秒），讓「震動」和「燈號」對得起來
- **亮度**：預設 25%，做成常數方便調整；太亮會干擾工作
- **更新頻率**：每 100 ms 更新一次即可，閃爍用 `millis()` 計算，不要用 `delay()`（會卡住感測器讀取）

#### 7-6 參考程式（Adafruit NeoPixel）

```cpp
#include <Adafruit_NeoPixel.h>

const int LED_PIN = 13, LED_N = 8, BAR_N = 7;
const uint8_t BRIGHTNESS = 64;                 // 約 25%
Adafruit_NeoPixel strip(LED_N, LED_PIN, NEO_GRB + NEO_KHZ800);

// 以下變數沿用你韌體中已經有的狀態（名稱請換成你實際使用的）
// String poseLabel;            // "normal" / "left_lean" / ... / "no_occupancy"
// uint32_t badSinceMs;         // 目前這個壞坐姿從何時開始（normal 時為 0）
// uint32_t sitStartMs;         // 這次坐下的時間
// bool sedentaryAlert;         // 久坐提醒已觸發、尚未起身
// int batteryPct; bool batteryPresent;
// const uint32_t SITTING_LIMIT_MIN = 5;      // 與後端久坐判定一致

void ledSetup() {
  strip.begin();
  strip.setBrightness(BRIGHTNESS);
  uint32_t test[3] = {strip.Color(255, 0, 0), strip.Color(0, 255, 0), strip.Color(0, 0, 255)};
  for (int c = 0; c < 3; c++)
    for (int i = 0; i < LED_N; i++) { strip.setPixelColor(i, test[c]); strip.show(); delay(40); }
  strip.clear(); strip.show();                  // 開機自我測試只在 setup() 用 delay
}

void ledUpdate(uint32_t now) {                   // 在 loop() 中每 100 ms 呼叫一次
  strip.clear();
  bool blinkFast = (now / 500) % 2 == 0;         // 0.5 秒亮、0.5 秒暗
  bool blinkSlow = (now % 2000) < 200;           // 每 2 秒閃 0.2 秒

  // ── 第 1~7 顆：坐姿顏色＋血條 ──
  if (poseLabel != "no_occupancy") {
    uint32_t color;
    if (sedentaryAlert)               color = blinkFast ? strip.Color(255, 0, 0) : 0;
    else if (poseLabel == "normal")   color = strip.Color(0, 255, 0);
    else if (now - badSinceMs >= 10000) color = strip.Color(255, 0, 0);
    else                              color = strip.Color(255, 180, 0);

    uint32_t limitMs = SITTING_LIMIT_MIN * 60000UL;
    uint32_t sat = now - sitStartMs;
    int lit = sedentaryAlert ? BAR_N
            : max(0, BAR_N - (int)((uint64_t)sat * BAR_N / limitMs));
    for (int i = 0; i < lit; i++) strip.setPixelColor(i, color);
  }

  // ── 第 8 顆：狀態燈 ──
  uint32_t status;
  if (batteryPresent && batteryPct < 20) status = blinkSlow ? strip.Color(255, 100, 0) : 0;
  else if (!WiFi.isConnected() || !mqtt.connected()) status = blinkFast ? strip.Color(0, 0, 255) : 0;
  else status = strip.Color(0, 25, 0);
  strip.setPixelColor(LED_N - 1, status);

  strip.show();
}
```

> 震動時白閃一下：在你送出震動的地方，對第 1～7 顆 `setPixelColor(i, strip.Color(255,255,255))` 後 `show()`，下一次 `ledUpdate()` 就會自動恢復原本顏色。

### 8.（可選）NTP 對時

`ts` 目前是開機秒數，後端會用收到的時間代替，所以不改也可以。要改的話：連上 WiFi 後 `configTime(8 * 3600, 0, "pool.ntp.org");`，`ts` 改送 Unix 秒數。

---

## 四、請確認：馬達位置是刻意改的嗎？

後端原本是照 7 月的規劃設計震動（7/12～7/13「設計馬達觸發邏輯草稿：各坐姿對應馬達（手軸×2、腰部×2）規則表」），但你現在的韌體是裝在椅墊四個角，兩邊不一樣：

| 馬達 | 原本規劃（後端） | 你現在的韌體 |
|---|---|---|
| M1 | 左手軸（扶手） | 椅墊右前 |
| M2 | 右手軸（扶手） | 椅墊右後 |
| M3 | 左腰（椅背） | 椅墊左後 |
| M4 | 右腰（椅背） | 椅墊左前 |

| 坐姿 | 原本規劃的震法與理由 | 你現在的震法 |
|---|---|---|
| 前傾 | M1+M2：兩邊手軸，提醒抬頭 | M1+M4：前側 |
| 後仰 | M3+M4：兩邊腰部，提醒坐直 | M2+M3：後側 |
| 左傾 | M1+M3：左手軸＋左腰（同側提醒） | M3+M4：左側 |
| 右傾 | M2+M4：右手軸＋右腰（同側提醒） | M1+M2：右側 |
| 久坐 | M1～M4 全部，提醒起身 | （目前沒有） |

**請回覆是哪一種**：
- **A. 刻意改的**（例如扶手、椅背不好裝，或裝在椅墊比較有感）：後端就以你現在的位置定案，請在 `MQTT資料說明.md` 補一句改的原因，報告時才說得清楚
- **B. 沒注意到原本的規劃**：請評估能不能改裝到手軸、腰部；能改的話，後端和韌體的對應表都改回原本的設計

兩種都可以，**重點是兩邊要一致**。目前後端已暫時照你現在的位置。

---

## 五、改完之後的 `chair/{device_id}/pressure` 範例

```json
{
  "device_id": "chair_A1B2C3",
  "ts": 3625,
  "seq": 812,
  "type": "change",
  "norm": [41, 53, 70, 31, 64, 59, 48, 36, 1, 0, 1],
  "pose": {
    "label": "normal",
    "left_right_balance": 0.068,
    "front_back_balance": -0.282,
    "center_x": 0.517, "center_y": 0.500,
    "neutral_x": 0.500, "neutral_y": 0.443,
    "normal_radius": 0.070,
    "stability": 0.717, "confidence": 0.717,
    "total_pressure": 402.0,
    "left_total": 143.0, "right_total": 164.0, "front_total": 193.0, "back_total": 108.0
  }
}
```

`type` 為 `sync` 的那筆另外帶 `power`。
