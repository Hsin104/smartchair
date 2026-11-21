# 智慧座椅（Smart Chair）

ESP32 讀取座椅壓力感測器，判斷坐姿與久坐時間，用震動馬達與 LED 燈條提醒使用者，並透過 MQTT 把資料送給後端。

## 檔案

| 路徑 | 內容 |
|---|---|
| `esp32/esp32_mqtt_ads1115/esp32_mqtt_ads1115.ino` | ESP32 韌體（v2） |
| `esp32/esp32_mqtt_ads1115/secrets.example.h` | WiFi／MQTT／OTA 設定範本 |
| `receiver/pose_demo.py` | 即時視覺化 demo（坐姿、壓力、久坐計時、燈條、馬達） |
| `receiver/mqtt_repro_test_runner.py` | 馬達震動測試工具 |
| `receiver/REPRO_TEST_PROTOCOL.txt` | 測試流程規範 |
| `MQTT資料說明.md` | 完整說明：硬體、接線、判定邏輯、MQTT 格式、可調參數 |
| `ESP32資料格式_給後端.md` | 給後端的精簡資料格式 |

## 硬體

- ESP32 ＋ 3 顆 ADS1115，11 顆壓力感測器（坐墊 S1～S8、椅背 S9～S11）
- 震動馬達 4 顆：M1 右扶手（GPIO 14）、M2 右靠背（27）、M3 左靠背（26）、M4 左扶手（25）
- WS2812B 燈條 2 條、各 35 顆：右扶手 D18、左扶手 D19，外接 5 V（建議 ≥ 2 A）

## 燒錄韌體

1. 複製 `secrets.example.h` 為 `secrets.h`，填入 WiFi、MQTT 帳密與 OTA 密碼（`secrets.h` 不會上傳 GitHub）。
2. Arduino IDE 安裝函式庫：Adafruit ADS1X15、Adafruit NeoPixel、PubSubClient、ArduinoJson。
3. 開發板選 ESP32 Dev Module，用 USB 燒錄。之後可透過 WiFi（OTA）燒錄，連接埠選 `chair-xxxxxx`。
4. 開機後序列埠會印出 `device_id`（例如 `chair_A1B2C3`）。

## 執行 demo

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r receiver\requirements.txt
Copy-Item receiver\.env.example receiver\.env   # 填入 MQTT 帳密，可選填 CHAIR_DEVICE_ID
.\.venv\Scripts\python.exe receiver\pose_demo.py
```

## MQTT Topic

| Topic | 方向 | 內容 |
|---|---|---|
| `chair/{device_id}/pressure` | 椅子 → 後端 | 壓力、坐姿、久坐、電量 |
| `chair/{device_id}/online` | 椅子 → 後端 | 在線狀態（LWT） |
| `chair/{device_id}/vibration/status` | 椅子 → 後端 | 提醒、校正等事件 |
| `chair/{device_id}/vibration/cmd` | 後端 → 椅子 | 手動控制馬達 |
| `chair/{device_id}/config` | 後端 → 椅子 | 個人中立點 |

格式細節見 `ESP32資料格式_給後端.md`。
