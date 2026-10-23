# ESP32 ↔ 後端傳送規格 v1

> 制定：陳翊昕（後端）　實作：蕭芷萱（硬體）
> 依據 10/19 教授建議：ESP32 端做 debouncing 與前處理、有變動才傳＋固定週期同步、傳有意義的資訊、斷網時椅子仍能提示、以量產多張椅子為前提。
> 規格中的數字是用遠端正式資料庫 9/1～10/23 真實椅子傳來的 21,353 筆資料算出來的（見第六節）。
> 感測器以**椅墊為主、椅背為輔**：椅背本身較軟、不易量測，坐姿判斷主要依靠椅墊 8 點。

---

## 一、為什麼要改：現況的數字

| 項目 | 現況 |
|---|---|
| 傳送頻率 | 每 0.5 秒一筆，不管有沒有變化 |
| 內容 | `raw`、`norm` 各 11 個原始數值 |
| 後端負擔 | 每一筆都跑一次坐姿模型＋寫一筆資料庫 → 一張椅子一天約 17 萬筆 |
| 防手震 | 在後端做（連續 10 筆一樣才算數，約 5 秒） |
| 量產上限 | 後端坐姿推論實測上限約每秒 90 筆 → 照現在的頻率只撐得住約 45 張椅子 |
| 多椅子 | topic 寫死 `chair/pressure/01`，第二張椅子接上會混在一起 |

---

## 二、分工：哪些事在椅子端做、哪些在後端做

| 時間等級 | 工作 | 在哪裡做 |
|---|---|---|
| 20 ms | 讀取 11 個感測器 | **ESP32** |
| 100 ms | 移動平均濾波（最近 5 次取平均）＝ debouncing | **ESP32** |
| 1 秒 | 判斷有沒有人坐、簡易坐姿判斷（狀態維持 1 秒才算數） | **ESP32** |
| 即時 | LED 燈條顯示坐姿狀態；**斷網時**由椅子自己震動提醒 | **ESP32** |
| 有變動時／每 5 秒 | 上傳一筆濾波後的資料 | ESP32 → 後端 |
| 秒級 | AI 模型精確判斷、確認坐姿維持一段時間才算數、寫資料庫、通知 App、**連網時**發馬達指令 | **後端** |
| 分鐘級 | 久坐判定 | 後端 |
| 使用者主動／每週 | AI 物理治療師建議 | 後端 |

---

## 三、MQTT 格式

### Topic（每張椅子各自一組）

| 用途 | Topic | 方向 |
|---|---|---|
| 感測資料 | `chair/{device_id}/pressure` | ESP32 → 後端 |
| 馬達指令 | `chair/{device_id}/vibration/cmd` | 後端 → ESP32 |
| 馬達回覆 | `chair/{device_id}/vibration/ack` | ESP32 → 後端 |

馬達指令與回覆的 JSON 內容**維持現在的格式不變**，只有 topic 改成帶 device_id。

### 感測資料 payload

```json
{
  "device_id": "chair_A1B2C3",
  "seq": 1532,
  "ts": 1761200000,
  "type": "change",
  "occupied": true,
  "values": [48, 69, 52, 57, 0, 41, 60, 55, 0, 12, 30],
  "local_posture": "left",
  "fw": "1.3.0"
}
```

| 欄位 | 型別 | 規格 |
|---|---|---|
| `device_id` | 字串 | `chair_` ＋ WiFi MAC 位址後 6 碼（大寫十六進位），見第五節第 6 點 |
| `seq` | 整數 | 開機從 0 開始，每送一筆加 1（後端用來發現漏封包） |
| `ts` | 整數 | Unix 時間（秒），NTP 對時；還沒對時成功就送 `0`，後端改用收到的時間 |
| `type` | 字串 | `change`（有變動）或 `sync`（定期同步） |
| `occupied` | 布林 | 有沒有人坐（規則見第五節第 4 點） |
| `values` | 11 個整數 | **濾波後的 norm 值，範圍 0～100**；順序跟現在的 `norm` 完全相同（0～7 椅墊、8～10 椅背由下往上） |
| `local_posture` | 字串 | `normal`／`left`／`right`／`forward`／`unknown`（規則見第五節第 4 點）；沒人坐時送 `unknown` |
| `fw` | 字串 | 韌體版本 |

**不再傳 `raw`**：後端只用 norm，拿掉可以讓封包小一半。

---

## 四、什麼時候送

1. **有變動就送（`type: "change"`）**，以下任一成立：
   - `occupied` 改變（坐下／離開）
   - `local_posture` 改變
   - 任一感測值跟「上次送出的值」相差 **≥ 10**（0～100 的尺度）
2. **定期同步（`type: "sync"`）**：距離上次送出已經 **5 秒**，就送一筆（不管有沒有變化）
3. **限速**：兩筆之間至少間隔 **0.5 秒**（避免短時間連續觸發）
4. **沒人坐時**：同步週期放寬為 **30 秒**（只是讓後端知道椅子還在線）

數字依據：
- 同一個坐姿下，相鄰兩筆的變化量中位數 0、95% 在 7 以內、99% 在 20 以內 → 門檻 10 可以過濾雜訊，又抓得到換姿勢
- 同步週期 5 秒：後端實測上限每秒約 90 筆，5 秒一筆約可支撐 450 張椅子；1 秒只能撐約 90 張

---

## 五、規格定案

### 1. 取樣與 debouncing
- 每 **20 ms** 讀一次全部 11 個感測器
- 每個感測器保留**最近 5 次**讀值取平均（環狀緩衝區），送出和判斷都用平均後的值。這就是 debouncing：按下瞬間的暫態會被平均掉
- 狀態類的判斷（有沒有人坐、坐姿）要**持續 1 秒**都一樣才更新，避免來回跳動

### 2. 傳 norm，範圍 0～100
- 後端模型用的是 norm；資料庫裡的真實資料確認 norm 範圍是 0～100
- 傳整數即可

### 3. NTP 對時
- 連上 WiFi 後呼叫：`configTime(8 * 3600, 0, "pool.ntp.org", "time.google.com");`
- 用 `time(nullptr)` 取得 Unix 秒數；小於 `1700000000` 代表還沒對時成功，`ts` 送 `0`

### 4. 有沒有人坐、簡易坐姿判斷、LED 燈條

**有沒有人坐**（S＝椅墊 8 個值的總和，正常坐著約 290～360）：
- S ≥ **40** 持續 1 秒 → 坐下
- S < **20** 持續 2 秒 → 離開
- 兩個門檻不同是為了避免在邊界來回切換

**簡易坐姿判斷**：用「跟自己剛坐下時比」，不用固定門檻，所以每個人體型不同也適用
- 定義（索引照 `values` 順序）：
  - 左側 L = [5]+[6]+[7]、右側 R = [0]+[1]+[2]
  - 前側 F = [2]+[4]+[5]、後側 B = [0]+[3]+[7]
  - 左右比 LR = (L − R) / (L + R)、前後比 FB = (F − B) / (F + B)
- **基準**：坐下後第 3～5 秒的 LR、FB 平均值，記為 LR0、FB0（請使用者剛坐下時坐正）
- 判斷（每次都跟基準比，結果要維持 1 秒）：
  - LR − LR0 ≥ **+0.30** → `left`
  - LR − LR0 ≤ **−0.30** → `right`
  - FB − FB0 ≥ **+0.15** → `forward`
  - 其他 → `normal`
- 依據（中位數）：正常坐姿 LR −0.03、FB −0.22；左傾 LR +0.66；右傾 LR −0.59；前傾 FB +0.12。左右傾跟正常坐姿差約 0.6～0.7、前傾差約 0.34，門檻取差距的一半，誤判比較少
- 跟「自己剛坐下時」比，而不是跟固定數字比：資料顯示整體略偏右（正常坐姿 LR 也是負的），這種個人坐姿或感測器的偏差會被基準自動扣掉
- 後仰（recline）只能靠椅背判斷，但椅背較軟、讀值大多是 0（見第六節），椅子端先不判斷，交給後端模型

**LED 燈條**（建議 WS2812B，8 顆，只要 1 條資料線）：
- 資料線接一個沒被感測器、馬達用到的 GPIO（例如 GPIO 13）
- 顏色：
  - 沒人坐：全暗
  - `normal`：綠色
  - 壞坐姿持續 10 秒內：黃色
  - 壞坐姿超過 10 秒：紅色
  - 斷網中：最右邊 1 顆藍色閃爍（其他照常顯示）
- 「血條」：亮起的顆數＝這次坐下後連續坐的時間，每 5 分鐘熄 1 顆（8 顆共 40 分鐘），全熄時整條紅色慢閃，提醒起來動一動

**斷網時的震動提醒**：
- MQTT 連線中：馬達一律由後端指令控制，ESP32 不自己震（避免重複）
- MQTT 斷線中：壞坐姿持續 **30 秒**，ESP32 自己用對應馬達震一次（對應關係與後端 `api/motor_constants.py` 相同：left→M1+M3、right→M2+M4、forward→M1+M2、久坐→M1～M4 全部），之後同一個壞坐姿 5 分鐘內不重複震

### 5. 變動門檻與同步週期
見第四節：門檻 **10**、同步 **5 秒**（沒人坐 30 秒）、最短間隔 **0.5 秒**

### 6. device_id
- 用 WiFi MAC 位址後 6 碼：`chair_` ＋ 例如 `A1B2C3`
- 每張椅子自動不同，不用手動設定，量產燒同一份韌體就好
- 後端第一次收到新的 device_id 會自動登記這張椅子
- 請開機時在序列埠印出 device_id，方便貼標籤

---

## 六、感測器資料現況：椅墊為主、椅背為輔

21,353 筆真實資料中：
- 椅墊 8 個值：中位數 43、95% 在 74 以下，讀值穩定，是坐姿判斷的主要依據
- 椅背 3 個值：95% 都是 0。椅背本身較軟，感測器不容易受力，屬於已知限制

因此：
- 椅子端的坐姿判斷（left／right／forward）只用椅墊，不用椅背
- `values` 仍然照常送出全部 11 個值（椅背 3 個也送），有讀到時後端模型可以當輔助
- 之後如果想讓椅背量得到，可以在感測器後面墊一塊薄硬板，讓壓力集中在感測器上；這是加分項目，不影響這次的規格

---

## 七、參考程式（Arduino，可直接拆進現有韌體）

假設現有程式已經有：讀第 i 個感測器 norm 值的函式 `readNorm(i)`、MQTT client `mqtt`（PubSubClient）。需要的函式庫：ArduinoJson、Adafruit NeoPixel。

```cpp
#include <WiFi.h>
#include <time.h>
#include <ArduinoJson.h>
#include <Adafruit_NeoPixel.h>

const int N = 11, AVG = 5;
const char* FW = "1.3.0";
String deviceId, topicPressure;

int buf[N][AVG]; int bufIdx = 0;
int filt[N], lastSent[N];
uint32_t seq = 0, lastSentMs = 0, lastSampleMs = 0;

bool occupied = false;          String posture = "unknown";
uint32_t occCandSince = 0;      bool occCand = false;
String postCand = "unknown";    uint32_t postCandSince = 0;
uint32_t sitStartMs = 0;        float LR0 = 0, FB0 = 0; int baseN = 0;

Adafruit_NeoPixel strip(8, 13, NEO_GRB + NEO_KHZ800);

void setupIds() {
  uint8_t mac[6]; WiFi.macAddress(mac);
  char id[16]; sprintf(id, "chair_%02X%02X%02X", mac[3], mac[4], mac[5]);
  deviceId = id; topicPressure = "chair/" + deviceId + "/pressure";
  Serial.println("device_id = " + deviceId);
  configTime(8 * 3600, 0, "pool.ntp.org", "time.google.com");
  strip.begin(); strip.show();
}

void sample() {                       // 每 20 ms 呼叫
  for (int i = 0; i < N; i++) buf[i][bufIdx] = readNorm(i);
  bufIdx = (bufIdx + 1) % AVG;
  for (int i = 0; i < N; i++) {
    int s = 0; for (int k = 0; k < AVG; k++) s += buf[i][k];
    filt[i] = s / AVG;
  }
}

float ratio(int a, int b) { return (a + b) ? (float)(a - b) / (a + b) : 0; }

void updateState(uint32_t now) {
  int S = 0; for (int i = 0; i < 8; i++) S += filt[i];
  bool c = occupied ? (S >= 20) : (S >= 40);              // 遲滯
  if (c != occCand) { occCand = c; occCandSince = now; }
  uint32_t need = occupied ? 2000 : 1000;                  // 離開 2 秒、坐下 1 秒
  if (occCand != occupied && now - occCandSince >= need) {
    occupied = occCand;
    if (occupied) { sitStartMs = now; baseN = 0; LR0 = FB0 = 0; }
    else posture = "unknown";
  }
  if (!occupied) return;

  float LR = ratio(filt[5] + filt[6] + filt[7], filt[0] + filt[1] + filt[2]);
  float FB = ratio(filt[2] + filt[4] + filt[5], filt[0] + filt[3] + filt[7]);
  uint32_t sat = now - sitStartMs;
  if (sat >= 3000 && sat < 5000) {                         // 坐下第 3~5 秒建立基準
    LR0 = (LR0 * baseN + LR) / (baseN + 1); FB0 = (FB0 * baseN + FB) / (baseN + 1); baseN++;
    return;
  }
  if (baseN == 0) return;

  String p = "normal";
  if (LR - LR0 >= 0.30) p = "left";
  else if (LR - LR0 <= -0.30) p = "right";
  else if (FB - FB0 >= 0.15) p = "forward";
  if (p != postCand) { postCand = p; postCandSince = now; }
  if (postCand != posture && now - postCandSince >= 1000) posture = postCand;
}

bool changed() {
  for (int i = 0; i < N; i++) if (abs(filt[i] - lastSent[i]) >= 10) return true;
  return false;
}

void publish(const char* type, uint32_t now) {
  JsonDocument doc;
  time_t t = time(nullptr);
  doc["device_id"] = deviceId; doc["seq"] = seq++;
  doc["ts"] = (t > 1700000000) ? (long)t : 0;
  doc["type"] = type; doc["occupied"] = occupied;
  JsonArray v = doc["values"].to<JsonArray>();
  for (int i = 0; i < N; i++) { v.add(filt[i]); lastSent[i] = filt[i]; }
  doc["local_posture"] = posture; doc["fw"] = FW;
  char out[256]; serializeJson(doc, out);
  mqtt.publish(topicPressure.c_str(), out);
  lastSentMs = now;
}

bool prevOcc = false; String prevPosture = "unknown";

void loopTelemetry() {               // 放在 loop() 裡
  uint32_t now = millis();
  if (now - lastSampleMs < 20) return;
  lastSampleMs = now;
  sample(); updateState(now);

  bool stateChanged = (occupied != prevOcc) || (posture != prevPosture);
  uint32_t syncMs = occupied ? 5000 : 30000;
  if (now - lastSentMs >= 500 && (stateChanged || changed())) publish("change", now);
  else if (now - lastSentMs >= syncMs) publish("sync", now);
  prevOcc = occupied; prevPosture = posture;
  // LED 與斷網震動：依第五節第 4 點，用 occupied、posture、now - sitStartMs、mqtt.connected() 實作
}
```

---

## 八、後端配合事項（陳翊昕）

- 訂閱 `chair/+/pressure`，依 device_id 對應到該椅子目前的使用者（多椅子架構）
- 防手震改成「坐姿維持 N 秒才算數」，不依賴固定傳送頻率
- 只在坐姿確認改變時寫資料庫，`sync` 只更新椅子狀態
- 馬達指令改送 `chair/{device_id}/vibration/cmd`
- **過渡期同時支援舊 topic `chair/pressure/01`**：硬體和後端可以各自上線，不會互相卡住
