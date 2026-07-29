//用來測試馬達震動
import json
import ssl
import sys
import threading
import time
from datetime import datetime

import paho.mqtt.client as mqtt

MQTT_BROKER = "d8806e09.ala.eu-central-1.emqxsl.com"
MQTT_PORT = 8883
MQTT_TOPIC_CMD = "chair/vibration/01/cmd"
MQTT_TOPIC_ACK = "chair/vibration/01/ack"
MQTT_TOPIC_STATUS = "chair/vibration/01/status"
MQTT_USER = "xiao"
MQTT_PASS = "zxzcindy1"

MOTOR_COUNT = 4
INTENSITY_MIN = 0
INTENSITY_MAX = 100
DURATION_MIN_MS = 50
DURATION_MAX_MS = 5000
STAGGER_MIN_MS = 0
STAGGER_MAX_MS = 500

state = {
    "connected": False,
    "last_ack": None,
    "last_status": None,
}
ack_event = threading.Event()


def clamp_int(value, min_value, max_value):
    if value < min_value:
        return min_value
    if value > max_value:
        return max_value
    return value


def now_cmd_id(prefix):
    return f"{prefix}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"


def parse_int(prompt, min_value, max_value):
    while True:
        text = input(prompt).strip()
        try:
            value = int(text)
        except ValueError:
            print("請輸入整數")
            continue

        clamped = clamp_int(value, min_value, max_value)
        if clamped != value:
            print(f"已自動夾限為 {clamped}")
        return clamped


def on_connect(client, userdata, flags, reason_code, properties=None):
    state["connected"] = True
    client.subscribe(MQTT_TOPIC_ACK)
    client.subscribe(MQTT_TOPIC_STATUS)
    print(f"MQTT 已連線 (code={reason_code})")


def on_disconnect(client, userdata, disconnect_flags, reason_code, properties=None):
    state["connected"] = False
    print(f"MQTT 已斷線 (code={reason_code})")


def on_message(client, userdata, msg):
    payload_text = msg.payload.decode("utf-8", errors="ignore")
    try:
        data = json.loads(payload_text)
    except Exception:
        data = None

    if msg.topic == MQTT_TOPIC_ACK:
        state["last_ack"] = data if isinstance(data, dict) else {"raw": payload_text}
        ack_event.set()
    elif msg.topic == MQTT_TOPIC_STATUS:
        state["last_status"] = data if isinstance(data, dict) else {"raw": payload_text}


def build_client():
    callback_api = getattr(mqtt, "CallbackAPIVersion", None)
    if callback_api and hasattr(callback_api, "VERSION2"):
        client = mqtt.Client(callback_api_version=callback_api.VERSION2)
    else:
        client = mqtt.Client()
    client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.tls_set(tls_version=ssl.PROTOCOL_TLS_CLIENT)
    client.tls_insecure_set(True)
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    return client


def publish_and_wait_ack(client, payload, timeout_sec=3.0):
    ack_event.clear()
    state["last_ack"] = None

    payload_text = json.dumps(payload, ensure_ascii=False)
    client.publish(MQTT_TOPIC_CMD, payload_text)
    print(f"已送出 CMD -> {payload_text}")

    if ack_event.wait(timeout=timeout_sec):
        print("收到 ACK:")
        print(json.dumps(state["last_ack"], ensure_ascii=False))
    else:
        print("等待 ACK 超時（可能網路延遲或裝置離線）")


def build_single_payload():
    motor_id = parse_int(f"馬達編號 (1-{MOTOR_COUNT}): ", 1, MOTOR_COUNT)
    intensity = parse_int("強度 (0-100): ", INTENSITY_MIN, INTENSITY_MAX)
    duration_ms = parse_int("持續時間 ms (50-5000): ", DURATION_MIN_MS, DURATION_MAX_MS)
    stagger_ms = parse_int("錯峰延遲 ms (0-500): ", STAGGER_MIN_MS, STAGGER_MAX_MS)

    return {
        "cmd_id": now_cmd_id("single"),
        "motor_id": motor_id,
        "intensity": intensity,
        "duration_ms": duration_ms,
        "stagger_ms": stagger_ms,
    }


def build_multi_payload():
    print("輸入格式: id:intensity:duration_ms，用分號分隔")
    print("例如: 1:60:900;3:70:1200")
    raw = input("請輸入多馬達命令: ").strip()
    stagger_ms = parse_int("錯峰延遲 ms (0-500): ", STAGGER_MIN_MS, STAGGER_MAX_MS)

    motors = []
    for part in raw.split(";"):
        part = part.strip()
        if not part:
            continue

        fields = [x.strip() for x in part.split(":")]
        if len(fields) != 3:
            print(f"略過無效片段: {part}")
            continue

        try:
            motor_id = clamp_int(int(fields[0]), 1, MOTOR_COUNT)
            intensity = clamp_int(int(fields[1]), INTENSITY_MIN, INTENSITY_MAX)
            duration_ms = clamp_int(int(fields[2]), DURATION_MIN_MS, DURATION_MAX_MS)
        except ValueError:
            print(f"略過無效片段: {part}")
            continue

        motors.append(
            {
                "id": motor_id,
                "intensity": intensity,
                "duration_ms": duration_ms,
            }
        )

    if not motors:
        print("沒有有效馬達資料，改送 stop_all")
        return {"cmd_id": now_cmd_id("fallback"), "stop_all": True}

    return {
        "cmd_id": now_cmd_id("multi"),
        "stagger_ms": stagger_ms,
        "motors": motors,
    }


def build_stop_payload():
    return {
        "cmd_id": now_cmd_id("stop"),
        "stop_all": True,
    }


def print_menu():
    print("\n====== 馬達控制選單 ======")
    print("1) 單馬達")
    print("2) 多馬達錯峰")
    print("3) 全部停止")
    print("4) 查看最近 STATUS")
    print("q) 離開")


def main():
    reconfigure_stdout = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure_stdout):
        reconfigure_stdout(encoding="utf-8", errors="replace")

    client = build_client()
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
        client.loop_start()

        print(f"Broker: {MQTT_BROKER}:{MQTT_PORT}")
        print(f"CMD Topic: {MQTT_TOPIC_CMD}")
        print(f"ACK Topic: {MQTT_TOPIC_ACK}")

        while True:
            print_menu()
            cmd = input("請選擇: ").strip().lower()

            if cmd == "1":
                payload = build_single_payload()
                publish_and_wait_ack(client, payload)
            elif cmd == "2":
                payload = build_multi_payload()
                publish_and_wait_ack(client, payload)
            elif cmd == "3":
                payload = build_stop_payload()
                publish_and_wait_ack(client, payload)
            elif cmd == "4":
                if state["last_status"] is None:
                    print("尚未收到 STATUS")
                else:
                    print(json.dumps(state["last_status"], ensure_ascii=False))
            elif cmd == "q":
                print("結束控制程式")
                break
            else:
                print("無效選項")

            time.sleep(0.05)

    except KeyboardInterrupt:
        print("\n已中止")
    except Exception as exc:
        print(f"連線或執行失敗: {exc}")
    finally:
        try:
            client.loop_stop()
            client.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    main()
