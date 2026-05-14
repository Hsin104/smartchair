# ESP32 + ADS1115 壓力感測系統

## 快速開始

### 1️⃣ 上傳 ESP32 韌體
- 打開 Arduino IDE
- 開啟 `esp32/esp32_mqtt_ads1115/esp32_mqtt_ads1115.ino`
- 選擇 Board: **ESP32 Dev Module**
- 選擇 Port: **COM7**（或你的 ESP32 連接的 COM 口）
- 點擊 **Upload** ⬆️

### 2️⃣ 執行 Python 訂閱者 
(用於從 MQTT 抓取數據並呈現 for 測試使用)
```powershell
cd receiver
pip install -r requirements.txt
python python_subscriber.py
```

## 系統架構
- **ESP32**：讀取 ADS1115 感測器數據，透過 Wi-Fi 發送 JSON 到 MQTT
- **MQTT Broker**：EMQX Cloud（d8806e09.ala.eu-central-1.emqxsl.com:8883）
- **Python Subscriber**：即時接收和顯示壓力數據

## 配置
編輯 `esp32_mqtt_ads1115.ino` 修改：
- Wi-Fi SSID / 密碼
- MQTT 帳號 / 密碼
- 感測器最小/最大 ADC 值（校正）

## 硬體配置
- 分為偵測部件與回饋部件，偵測部件由 11 個壓力感測器組成，回饋部件由四個鈕扣型微型馬達組成
- **I2C**：GPIO21 (SDA)、GPIO22 (SCL)
- **偵測部件** **ADS1115 地址**：
  - 0x48（ADDR→GND）S1-S4
  - 0x49（ADDR→3V3）S5-S8
  - 0x4A（ADDR→SDA）S9-S11(下學期開發)
-**回饋部件** **esp32接腳**(下學期開發)
  - GPIO25 P1
  - GPIO26 P2
  - GPIO27 P3
  - GPIO14 P4

系統會自動偵測連接的 ADS1115，未找到的通道用亂數替代。
