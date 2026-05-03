# 智慧辦公椅後端 AI 系統開發報告
## 報告人：陳翊昕｜後端 & AI 開發負責人
## 報告期間：2026 年 4 月 21 日 ～ 5 月 4 日

---

## 一、專題背景與目標

本專題名稱為「智慧辦公椅」，目標是打造一套能即時偵測使用者坐姿並給予改善建議的 AI 系統。系統結合嵌入式硬體感測器、雲端後端 API、深度學習模型與 AI 物理治療師助手，當使用者坐姿不良時，椅子的震動馬達會提醒使用者，同時 AI 提供專業的改善建議。

### 硬體配置（最終確認）
- 椅墊壓力感測器 FSR × 8（3-2-3 排列：左後/左中/左前、中後/中前、右後/右中/右前）
- 椅背壓力感測器 FSR × 3（脊椎線：上段/中段/下段）
- 震動馬達 × 2（坐姿不良時震動提醒使用者）
- 移除項目：ToF 距離感測器（成本高、效益低）、IMU 加速度計（功能可由 FSR 取代）

### 技術架構
- 後端框架：Django REST Framework（Python）
- 資料庫：PostgreSQL
- 深度學習框架：TensorFlow / Keras
- AI Agent：LangChain + Google Gemini 2.5 Flash + FAISS 向量資料庫
- 通訊協定：MQTT（EMQX Cloud，ESP32 與雲端後端串接）
- API 測試工具：Postman

---

## 二、坐姿辨識模型升級：隨機森林 → 深度學習 MLP

### 為什麼要升級？

原始版本使用隨機森林（Random Forest）作為坐姿分類器，但面臨以下問題：
1. 特徵數量太少：只使用 4 個原始 FSR 數值，無法捕捉複雜的感測器組合關係
2. 硬體感測器配置改變：從 FSR×4 + ToF + IMU 改為 FSR×8（椅墊）+ FSR×3（椅背），資料格式完全不同
3. 準確率不穩定：受假資料品質影響大
4. 缺乏衍生特徵：無法加入比例、總量等計算特徵

### 深度學習 MLP 架構

採用多層感知器（Multi-Layer Perceptron）：

```
輸入層（16 個特徵）
  ↓
全連接層（64 個神經元，ReLU 激活函數）
批次正規化（BatchNormalization）
Dropout（30%，防止過擬合）
  ↓
全連接層（128 個神經元，ReLU 激活函數）
批次正規化（BatchNormalization）
Dropout（30%，防止過擬合）
  ↓
全連接層（64 個神經元，ReLU 激活函數）
Dropout（20%）
  ↓
全連接層（32 個神經元，ReLU 激活函數）
  ↓
輸出層（5 種坐姿類別，Softmax 激活函數）
```

總參數量：約 20,677 個

### 16 個輸入特徵說明

**椅墊 FSR 原始數值（8 個）：**
- left_back（左後）、left_mid（左中）、left_front（左前）
- center_back（中後）、center_front（中前）
- right_back（右後）、right_mid（右中）、right_front（右前）

**椅背 FSR 原始數值（3 個）：**
- spine_upper（脊椎上段）、spine_mid（脊椎中段）、spine_lower（脊椎下段）

**衍生特徵（5 個，自動計算）：**
- seat_total：椅墊總壓力（8 個感測器加總）
- left_ratio：左側比例（左側三個感測器 / 椅墊總壓力）
- front_ratio：前排比例（前排三個感測器 / 椅墊總壓力）
- spine_total：椅背脊椎總壓力
- spine_ratio：椅背佔全身比例（spine_total / 全部壓力合計）

### 訓練設定與結果

- 訓練工具：TensorFlow / Keras + EarlyStopping（patience=15）+ ReduceLROnPlateau
- 訓練資料：2000 筆（10 位受測者假資料 × 5 種坐姿 × 40 筆，8+3 感測器格式）
- 測試資料：500 筆
- 訓練 Epoch：約 20 輪（EarlyStopping 提早停止）
- 測試準確率：**100%**（500 筆測試資料，5 種坐姿 F1-Score 均達 1.00）

### 久坐未動（sedentary）的特殊處理

久坐未動無法由感測器壓力值判斷（坐得好好的也可能久坐），因此採用時間邏輯：

- 深度學習模型只負責分類 5 種坐姿（normal / forward / left / right / recline）
- 若模型預測為 normal，額外檢查：使用者 30 分鐘前是否已有坐姿紀錄
- 若有 → 判定為 sedentary（久坐未動），觸發提醒
- 此設計讓 DL 模型專注在壓力特徵，久坐由 API 層邏輯判斷

---

## 三、資料庫欄位修正

配合硬體規格確認，後端資料庫（PostgreSQL）欄位進行以下調整：

### 移除的欄位
- `fsr_data`：舊版 4 個 FSR 原始數值（已被 seat_pressure_data 取代）
- `head_distance_data`：ToF 距離感測數值（ToF 感測器已移除）
- `tilt_angle_data`：IMU 傾角數值（IMU 感測器已移除）

### 新增 / 更新的欄位
- `seat_pressure_data`：椅墊 8 個 FSR 數值（JSON 格式，3-2-3 排列）
- `back_pressure_data`：椅背 3 個脊椎 FSR 數值（JSON 格式）

### 資料格式範例

```json
{
  "seat_pressure_data": {
    "left_back": 50, "left_mid": 50, "left_front": 48,
    "center_back": 46, "center_front": 46,
    "right_back": 50, "right_mid": 50, "right_front": 48
  },
  "back_pressure_data": {
    "spine_upper": 30, "spine_mid": 35, "spine_lower": 28
  }
}
```

### Migration 記錄
- Migration 0002：移除 fsr_data（舊版欄位）
- Migration 0003：移除 head_distance_data、tilt_angle_data；新增 back_pressure_data

---

## 四、Physio Agent 開發（4/21 ～ 5/4）

### 什麼是 Physio Agent？

Physio Agent 是本專題開發的 AI 物理治療師助手，名叫「姿康（PhysioBot）」。當系統偵測到使用者坐姿不良時，自動從醫學文獻中檢索相關資訊，並利用大型語言模型生成繁體中文的個人化改善建議。

### 系統架構：RAG（檢索增強生成）

RAG 是一種讓 AI 在回答前先查閱特定知識庫的技術，避免 AI 憑空生成不準確的醫學建議。

完整流程：
1. 建立知識庫（7 份醫學文獻，手動撰寫）
2. 使用 RecursiveCharacterTextSplitter 切分文件（每段 400 字，重疊 50 字）
3. 透過 Google Gemini Embedding 模型（gemini-embedding-001）將文字向量化
4. 儲存至 FAISS 本地向量資料庫
5. 當使用者坐姿不良時，自動以坐姿類別作為查詢
6. FAISS 檢索最相關的 3 份文件片段
7. 將文件內容 + 問題送入 Gemini 2.5 Flash LLM
8. LLM 生成固定格式的繁體中文建議

### 知識庫內容（7 份文件）

知識庫參考 Mayo Clinic、Cleveland Clinic、Physiopedia、NHS、WHO、PubMed 等國際醫療機構資料：

1. **標準坐姿**（Mayo Clinic / Cleveland Clinic）：正確辦公坐姿五大要素，脊椎對齊、螢幕位置、動態坐姿原則
2. **左傾**（Physiopedia / NHS）：脊椎不對稱受力風險、腰方肌失衡、側向伸展改善動作
3. **右傾**（Physiopedia / Cleveland Clinic）：右側肩頸慢性疼痛、滑鼠位置調整建議
4. **前傾頭姿（烏龜頸）**（Physiopedia / Mayo Clinic / PubMed）：頭部每前移 2.5 公分頸椎負擔增加 4-5 公斤，頸部縮回訓練
5. **過度後仰**（Cleveland Clinic / NHS）：腰椎剪力、核心肌群弱化、腰枕使用建議
6. **久坐未動**（WHO / Mayo Clinic）：WHO 列為全球第四大致死風險因子，每 30 分鐘起身活動建議
7. **通用辦公室伸展操**（NHS / Cleveland Clinic）：頸部、肩膀、腰背、下肢，每小時一輪

### Agent 回應格式

每次生成的建議固定包含四個區塊：

```
⚠️ 問題分析
（用 2-3 句說明此坐姿的健康危害）

✅ 立即改善（3 個具體動作，附操作說明）
1. ...
2. ...
3. ...

💪 長期預防
（1-2 句預防此問題復發的訓練建議）

⏰ 提醒
（一句溫馨提醒語）
```

### 技術選型說明

| 元件 | 選擇 | 原因 |
|------|------|------|
| LLM | Google Gemini 2.5 Flash | 免費額度足夠，支援繁體中文 |
| Embedding | gemini-embedding-001 | 與 LLM 同一平台，整合方便 |
| 向量資料庫 | FAISS（本地） | 無需額外服務，避免 ChromaDB 版本衝突 |
| Chain | LangChain 1.x LCEL | 取代已棄用的 RetrievalQA，架構更清晰 |
| temperature | 0.7 | 建議有一定變化性，但不失專業性 |

---

## 五、API 設計

### POST /api/posture（主要流程）

ESP32 送出感測器數值後的完整處理流程：
1. 接收 seat_pressure_data（8 個 FSR）和 back_pressure_data（3 個 FSR）
2. 深度學習模型自動預測坐姿類別
3. 若預測為 normal，額外執行久坐時間判斷
4. 若坐姿不良（非 normal）→ 自動呼叫 Physio Agent 生成建議
5. 建立 Notification 記錄（震動馬達待取通知）
6. 回傳 posture + physio_advice

### POST /api/agent（手動查詢）

使用者主動查詢建議：
- 輸入：posture（坐姿類別）+ user_message（可選，如「我肩膀很痠」）
- 輸出：posture_display（中文名稱）+ advice（完整建議）
- 對話記錄存入 AgentLog

### GET /api/notification/pending（ESP32 輪詢）

ESP32 定時輪詢是否有待處理的震動提醒：
- 回傳尚未發送的通知清單
- 同時自動標記為已發送
- ESP32 收到後驅動馬達震動

### POST /api/notification/ack（馬達確認）

ESP32 確認馬達已震動完畢（可選），回傳確認筆數。

---

## 六、6 種坐姿 Postman 測試結果

| 坐姿 | 判斷方式 | 測試結果 | 是否觸發 Agent |
|------|----------|----------|----------------|
| normal（標準坐姿） | 深度學習模型 | ✅ 正確 | 否 |
| forward（頭部前傾） | 深度學習模型 | ✅ 正確 | 是，回傳 physio_advice |
| left（身體左傾） | 深度學習模型 | ✅ 正確 | 是，回傳 physio_advice |
| right（身體右傾） | 深度學習模型 | ✅ 正確 | 是，回傳 physio_advice |
| recline（過度後仰） | 深度學習模型 | ✅ 正確 | 是，回傳 physio_advice |
| sedentary（久坐未動） | 時間邏輯（30 分鐘） | ✅ 正確 | 是，回傳 physio_advice |

所有 6 種坐姿均正確辨識，Physio Agent 在坐姿不良時自動觸發並回傳繁體中文建議。

---

## 七、完成事項總覽

本報告期間（4/21 ～ 5/2，提前 2 天完成）共完成以下項目：

1. ✅ 隨機森林移除，改用深度學習 MLP（TensorFlow/Keras）
2. ✅ 16 個特徵輸入設計（椅墊 8 個 + 椅背 3 個 + 衍生特徵 5 個）
3. ✅ 假資料重新產生（2500 筆，新版 8+3 感測器格式）
4. ✅ 模型重訓，測試準確率達 100%
5. ✅ 資料庫欄位更新（移除 ToF/IMU 欄位，新增 back_pressure_data）
6. ✅ Django Migration 套用至 PostgreSQL
7. ✅ RAG 知識庫建立（7 份醫學文獻，FAISS 向量資料庫）
8. ✅ Gemini 2.5 Flash LLM 串接，繁體中文專業建議
9. ✅ 坐姿偵測自動觸發 Agent 建議（POST /api/posture）
10. ✅ 手動查詢建議介面（POST /api/agent）
11. ✅ 6 種坐姿 Postman 測試全數通過
12. ✅ 震動馬達通知 API 建置完成（GET /api/notification/pending、POST /api/notification/ack，待 ESP32 接入）
13. ✅ Django Admin 後台資料可視化

---

## 八、下一步計畫

- 等待組員 ESP32 送入真實感測器數據（目前使用假資料訓練）
- UI 介面（組員負責）串接後端 API
- 實際使用者坐姿數據採集與模型微調
- 震動馬達端到端測試（ESP32 ↔ /api/notification/pending）
