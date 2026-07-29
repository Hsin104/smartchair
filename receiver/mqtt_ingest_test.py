import json
import os
import ssl
import sys
from collections import deque
from datetime import datetime

import paho.mqtt.client as mqtt

MQTT_BROKER = "d8806e09.ala.eu-central-1.emqxsl.com"  # EMQX Cloud
MQTT_PORT = 8883  # TLS
MQTT_TOPIC_SENSOR = "chair/pressure/01"
MQTT_TOPIC_VIB_CMD = "chair/vibration/01/cmd"
MQTT_TOPIC_VIB_ACK = "chair/vibration/01/ack"
MQTT_TOPIC_VIB_STATE = "chair/vibration/01/state"
MQTT_TOPIC_VIB_STATUS = "chair/vibration/01/status"
MQTT_USER = "xiao"
MQTT_PASS = "zxzcindy1"

SENSOR_LABELS = [
    "S1",
    "S2",
    "S3",
    "S4",
    "S5",
    "S6",
    "S7",
    "S8",
    "S9",
    "S10",
    "S11",
]
SENSOR_INPUTS = [
    "ADS1 A0",
    "ADS1 A1",
    "ADS1 A2",
    "ADS1 A3",
    "ADS2 A0",
    "ADS2 A1",
    "ADS2 A2",
    "ADS2 A3",
    "ADS3 A0",
    "ADS3 A1",
    "ADS3 A2",
]

MOTOR_PINS = [14, 27, 26, 25]
MOTOR_COUNT = 4

runtime = {
    "mqtt_connected": False,
    "last_event": "尚未收到事件",
    "last_topic": "-",
    "sensor": {
        "device_id": "unknown",
        "ts": 0,
        "raw": [0] * len(SENSOR_LABELS),
        "norm": [0] * len(SENSOR_LABELS),
        "detected": [None] * len(SENSOR_LABELS),
        "state": ["unknown"] * len(SENSOR_LABELS),
    },
    "motors": [
        {
            "id": i + 1,
            "pin": MOTOR_PINS[i],
            "running": False,
            "intensity": 0,
            "remaining_ms": 0,
            "detected": None,
        }
        for i in range(MOTOR_COUNT)
    ],
    "motor_detection_supported": False,
    "events": deque(maxlen=12),
}

reconfigure_stdout = getattr(sys.stdout, "reconfigure", None)
if callable(reconfigure_stdout):
    reconfigure_stdout(encoding="utf-8", errors="replace")


def clear():
    os.system("cls" if os.name == "nt" else "clear")


def push_event(message):
    ts_text = datetime.now().strftime("%H:%M:%S")
    runtime["events"].appendleft(f"[{ts_text}] {message}")
    runtime["last_event"] = message


def normalize_int_list(values, length):
    if not isinstance(values, list):
        values = [values] if values is not None else []
    cleaned = []
    for i in range(length):
        item = values[i] if i < len(values) else 0
        try:
            cleaned.append(int(item))
        except Exception:
            cleaned.append(0)
    return cleaned


def normalize_detect_list(values, length):
    if not isinstance(values, list):
        return [None] * length
    cleaned = []
    for i in range(length):
        item = values[i] if i < len(values) else None
        if isinstance(item, bool):
            cleaned.append(item)
        elif isinstance(item, str) and item.lower() in ("true", "false"):
            cleaned.append(item.lower() == "true")
        else:
            cleaned.append(None)
    return cleaned


def normalize_state_list(values, length):
    if not isinstance(values, list):
        return ["unknown"] * length
    cleaned = []
    for i in range(length):
        item = values[i] if i < len(values) else "unknown"
        if isinstance(item, str) and item:
            cleaned.append(item)
        else:
            cleaned.append("unknown")
    return cleaned


def sensor_state_to_text(state_value, detected):
    if state_value == "installed":
        return "正常"
    if state_value == "not_installed":
        return "未安裝"
    if state_value == "not_detected":
        return "未偵測"
    if state_value == "detecting":
        return "偵測中"
    if detected is False:
        return "未偵測"
    return "未知"


def print_dashboard():
    clear()
    sensor = runtime["sensor"]
    raw = sensor["raw"]
    norm = sensor["norm"]

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    mqtt_status = "已連線" if runtime["mqtt_connected"] else "未連線"
    print(f"時間: {now}")
    print(f"MQTT: {mqtt_status}    Broker: {MQTT_BROKER}:{MQTT_PORT}")
    print(f"最後事件: {runtime['last_event']}")
    print(f"最後 Topic: {runtime['last_topic']}")
    print("=" * 96)
    print(f"裝置: {sensor['device_id']}    ESP32 ts: {sensor['ts']}s")
    print("-" * 96)
    print(f"{'感測器':<4} {'接腳(ADS通道)':<12} {'RAW (0-32767)':<16} {'壓力 (0-100)':<14} {'偵測'} {'狀態'}")
    print("-" * 96)
    for i in range(len(SENSOR_LABELS)):
        sensor_input = SENSOR_INPUTS[i] if i < len(SENSOR_INPUTS) else "N/A"
        r = raw[i] if i < len(raw) else 0
        n = norm[i] if i < len(norm) else 0
        detected = sensor.get("detected", [None] * len(SENSOR_LABELS))[i]
        state_value = sensor.get("state", ["unknown"] * len(SENSOR_LABELS))[i]
        n = max(0, min(100, n))
        bar = "█" * (n // 10) + "░" * (10 - n // 10)
        detect_text = sensor_state_to_text(state_value, detected)
        if detect_text in ("未安裝", "未偵測"):
            status = "-"
            bar = "-" * 10
            r = 0
            n = 0
        elif detect_text == "正常":
            status = "●" if r > 0 else "○"
        else:
            status = "?"
        print(f"{SENSOR_LABELS[i]:<6} {sensor_input:<16} {r:<16} {n:<12} {detect_text:<8} {status} {bar}")
    print("=" * 96)

    print("馬達狀態")
    print("-" * 96)
    print(f"{'馬達':<6} {'GPIO':<6} {'運轉':<6} {'強度':<6} {'剩餘(ms)':<10} {'偵測'}")
    print("-" * 96)
    for motor in runtime["motors"]:
        running = "ON" if motor.get("running") else "OFF"
        detected = motor.get("detected")
        if runtime.get("motor_detection_supported", False):
            detect_text = "正常" if detected is True else "偵測不到"
        else:
            detect_text = "無回授"
        print(
            f"M{motor.get('id', 0):<5} "
            f"{motor.get('pin', 0):<6} "
            f"{running:<6} "
            f"{int(motor.get('intensity', 0)):<6} "
            f"{int(motor.get('remaining_ms', 0)):<10} "
            f"{detect_text}"
        )
    print("=" * 96)

    print("近期事件")
    print("-" * 96)
    if runtime["events"]:
        for line in list(runtime["events"]):
            print(line)
    else:
        print("(尚無事件)")


def on_connect(client, userdata, flags, reason_code, properties=None):
    runtime["mqtt_connected"] = True
    subscribe_topics = [
        MQTT_TOPIC_SENSOR,
        MQTT_TOPIC_VIB_CMD,
        MQTT_TOPIC_VIB_ACK,
        MQTT_TOPIC_VIB_STATE,
        MQTT_TOPIC_VIB_STATUS,
    ]
    for topic in subscribe_topics:
        client.subscribe(topic)
    push_event(f"MQTT 已連線 (code={reason_code})，已訂閱 {len(subscribe_topics)} 個 Topic")
    print_dashboard()


def on_disconnect(client, userdata, disconnect_flags, reason_code, properties=None):
    runtime["mqtt_connected"] = False
    push_event(f"MQTT 已斷線 (code={reason_code})")
    print_dashboard()


def parse_json(payload_text):
    try:
        return json.loads(payload_text)
    except Exception:
        return None


def on_message(client, userdata, msg):
    payload_text = msg.payload.decode("utf-8", errors="ignore")
    runtime["last_topic"] = msg.topic
    data = parse_json(payload_text)

    if msg.topic == MQTT_TOPIC_SENSOR:
        if data is None:
            push_event("感測器資料解析失敗")
        else:
            runtime["sensor"]["device_id"] = data.get("device_id", "unknown")
            runtime["sensor"]["ts"] = int(data.get("ts", 0) or 0)
            runtime["sensor"]["raw"] = normalize_int_list(data.get("raw", []), len(SENSOR_LABELS))
            runtime["sensor"]["norm"] = normalize_int_list(data.get("norm", []), len(SENSOR_LABELS))
            runtime["sensor"]["state"] = normalize_state_list(data.get("sensor_state", []), len(SENSOR_LABELS))
            push_event("收到感測器資料更新")

    elif msg.topic == MQTT_TOPIC_VIB_STATE:
        if data is None:
            push_event("馬達狀態資料解析失敗")
        else:
            motors = data.get("motors", [])
            for motor_data in motors:
                motor_id = int(motor_data.get("id", 0) or 0)
                if 1 <= motor_id <= MOTOR_COUNT:
                    idx = motor_id - 1
                    runtime["motors"][idx]["running"] = bool(motor_data.get("running", False))
                    runtime["motors"][idx]["intensity"] = int(motor_data.get("intensity", 0) or 0)
                    runtime["motors"][idx]["remaining_ms"] = int(motor_data.get("remaining_ms", 0) or 0)
            push_event(f"馬達狀態更新: event={data.get('event', 'unknown')}")

    elif msg.topic == MQTT_TOPIC_VIB_ACK:
        if data is None:
            push_event(f"ACK 非 JSON: {payload_text}")
        else:
            push_event(
                "ACK "
                f"cmd_id={data.get('cmd_id', 'unknown')} "
                f"status={data.get('status', 'unknown')} "
                f"msg={data.get('message', '')}"
            )

    elif msg.topic == MQTT_TOPIC_VIB_STATUS:
        if data is None:
            push_event(f"STATUS 非 JSON: {payload_text}")
        else:
            if data.get("event") == "hardware_report":
                runtime["sensor"]["detected"] = normalize_detect_list(
                    data.get("sensor_detected", []), len(SENSOR_LABELS)
                )
                runtime["motor_detection_supported"] = bool(
                    data.get("motor_detection_supported", False)
                )
                motor_detected = data.get("motor_detected", [])
                for i in range(MOTOR_COUNT):
                    marker = motor_detected[i] if isinstance(motor_detected, list) and i < len(motor_detected) else None
                    if isinstance(marker, bool):
                        runtime["motors"][i]["detected"] = marker
                    else:
                        runtime["motors"][i]["detected"] = None
            push_event(
                "STATUS "
                f"event={data.get('event', 'unknown')} "
                f"msg={data.get('message', '')}"
            )

    elif msg.topic == MQTT_TOPIC_VIB_CMD:
        if data is None:
            push_event(f"CMD 非 JSON: {payload_text}")
        else:
            push_event(f"收到控制指令: cmd_id={data.get('cmd_id', 'unknown')}")

    else:
        push_event(f"收到未分類 Topic: {msg.topic}")

    print_dashboard()


def build_client():
    callback_api = getattr(mqtt, "CallbackAPIVersion", None)
    if callback_api and hasattr(callback_api, "VERSION2"):
        client = mqtt.Client(callback_api_version=callback_api.VERSION2)
    else:
        client = mqtt.Client()
    client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.tls_set(tls_version=ssl.PROTOCOL_TLS_CLIENT)
    client.tls_insecure_set(True)  # 跳過憑證驗證（測試用）
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    return client


def main():
    print("啟動 MQTT 測試接收器...")
    print(f"Broker: {MQTT_BROKER}:{MQTT_PORT}")
    print(f"Sensor Topic : {MQTT_TOPIC_SENSOR}")
    print(f"Vib CMD Topic: {MQTT_TOPIC_VIB_CMD}")
    print(f"Vib ACK Topic: {MQTT_TOPIC_VIB_ACK}")
    print(f"Vib ST  Topic: {MQTT_TOPIC_VIB_STATE}")
    print(f"Vib SYS Topic: {MQTT_TOPIC_VIB_STATUS}")

    client = build_client()
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
        push_event("等待 MQTT 訊息...")
        print_dashboard()
        client.loop_forever()
    except KeyboardInterrupt:
        print("\n已停止接收。")
    except Exception as exc:
        print(f"連線失敗: {exc}")
        print("請確認網路可用、MQTT 帳密正確，以及憑證設定是否可連線。")


if __name__ == "__main__":
    main()