# 智慧辦公椅專題 — 背景資料（陳翊昕）

## 專題基本資料
- **題目：** 具備坐姿分析與個人化伸展指引之「智慧辦公椅與物理治療師 Agent」
- **組別：** A02｜文化大學資工系 3A
- **成員：** 蕭芷萱（硬體）、戴珮珍（前端）、陳翊昕（後端／AI）
- **指導教授：** 洪敏雄 教授

## 我的負責範圍（陳翊昕）
- Django 後端建置
- PostgreSQL 資料庫設計
- Mosquitto MQTT Broker 架設
- REST API 開發
- 坐姿數據採集與標記
- AI 模型訓練（深度學習 MLP，TensorFlow/Keras）
- Physio Agent 開發（LLM + RAG + Function Calling）
- 壓力測試

## 系統架構
硬體（ESP32 + FSR + ToF + IMU）
  → MQTT →
後端（Django + PostgreSQL）
  → REST API →
前端 Flutter App ＋ Physio Agent（LLM + RAG）

## 技術堆疊
- 後端：Django + Django REST Framework
- 資料庫：PostgreSQL
- 通訊：MQTT（paho-mqtt）
- AI 模型：TensorFlow / Keras（MLP 深度學習）
- LLM：GPT-4o 或 Gemini 1.5 Pro
- RAG：LangChain + ChromaDB
- 環境：Python 3.11、Docker、VSCode、PowerShell

## 辨識的坐姿類別（6種）
1. 標準坐姿
2. 左傾
3. 右傾
4. 前傾（烏龜頸）
5. 過度後仰
6. 久坐未動

## 資料庫資料表
- users：使用者帳號、身高體重
- posture_records：時間戳、坐姿類別、感測器數值
- notifications：推播紀錄
- agent_logs：Physio Agent 對話紀錄

## MQTT Topic
- smartchair/sensor/fsr
- smartchair/sensor/tof
- smartchair/sensor/imu
- smartchair/result/posture
- smartchair/alert/vibrate
