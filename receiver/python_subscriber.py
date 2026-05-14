import json
import os
import ssl
from datetime import datetime

import paho.mqtt.client as mqtt

MQTT_BROKER = "d8806e09.ala.eu-central-1.emqxsl.com"  # EMQX Cloud
MQTT_PORT = 8883  # TLS
MQTT_TOPIC = "chair/pressure/01"
MQTT_USER = "xiao"
MQTT_PASS = "zxzcindy1"

SENSOR_LABELS = ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8"]
SENSOR_GPIOS  = [32,   33,   34,   35,   36,   39,   25,   26]


def clear():
    os.system("cls" if os.name == "nt" else "clear")


def print_table(device, ts, raw, norm):
    clear()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"裝置: {device}    時間: {now}    ESP32 ts: {ts}s")
    print("=" * 62)
    print(f"{'感測器':<6} {'GPIO':<8} {'RAW (0-4095)':<16} {'壓力 (0-100)':<12} {'狀態'}")
    print("-" * 62)
    for i in range(len(SENSOR_LABELS)):
        r = raw[i] if i < len(raw) else 0
        n = norm[i] if i < len(norm) else 0
        bar = "█" * (n // 10) + "░" * (10 - n // 10)
        status = "●" if r > 0 else "○"
        gpio = f"GPIO{SENSOR_GPIOS[i]}"
        print(f"{SENSOR_LABELS[i]:<6} {gpio:<8} {r:<16} {n:<12} {status} {bar}")
    print("=" * 62)


def on_connect(client, userdata, flags, reason_code, properties=None):
    print(f"已連線 (code={reason_code})，等待資料...")
    client.subscribe(MQTT_TOPIC)


def on_message(client, userdata, msg):
    payload_text = msg.payload.decode("utf-8", errors="ignore")
    try:
        data = json.loads(payload_text)
        device = data.get("device_id", "unknown")
        ts = data.get("ts", 0)
        raw = data.get("raw", [])
        norm = data.get("norm", [])
        print_table(device, ts, raw, norm)
    except Exception:
        print(f"無法解析: {payload_text}")


client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.username_pw_set(MQTT_USER, MQTT_PASS)
client.tls_set(tls_version=ssl.PROTOCOL_TLS_CLIENT)
client.tls_insecure_set(True)  # 跳過憑證驗證（測試用）
client.on_connect = on_connect
client.on_message = on_message

client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
client.loop_forever()
