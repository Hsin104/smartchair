//看mqtt的數據
import argparse
import json
import os
import ssl
import sys
import threading
import time
import uuid
from collections import deque
from datetime import datetime

import paho.mqtt.client as mqtt

MQTT_BROKER = "d8806e09.ala.eu-central-1.emqxsl.com"
MQTT_PORT = 8883
MQTT_USER = "xiao"
MQTT_PASS = "zxzcindy1"

TOPIC_SENSOR = "chair/pressure/01"
TOPIC_CMD = "chair/vibration/01/cmd"
TOPIC_ACK = "chair/vibration/01/ack"
TOPIC_STATE = "chair/vibration/01/state"
TOPIC_STATUS = "chair/vibration/01/status"

MOTOR_COUNT = 4
MOTOR_PINS = [14, 27, 26, 25]
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

class MinimalClient:
    def __init__(self, pretty_mode=False):
        self.connected = False
        self.last_ack = None
        self.pretty_mode = pretty_mode
        self._ack_event = threading.Event()
        self.runtime = {
            "last_topic": "-",
            "last_event": "尚未收到事件",
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

        callback_api = getattr(mqtt, "CallbackAPIVersion", None)
        if callback_api and hasattr(callback_api, "VERSION2"):
            self.client = mqtt.Client(callback_api_version=callback_api.VERSION2)
        else:
            self.client = mqtt.Client()

        self.client.username_pw_set(MQTT_USER, MQTT_PASS)
        self.client.tls_set(tls_version=ssl.PROTOCOL_TLS_CLIENT)
        self.client.tls_insecure_set(True)
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message

    def _clear(self):
        os.system("cls" if os.name == "nt" else "clear")

    def _push_event(self, message):
        ts_text = datetime.now().strftime("%H:%M:%S")
        self.runtime["events"].appendleft(f"[{ts_text}] {message}")
        self.runtime["last_event"] = message

    def _normalize_int_list(self, values, length):
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

    def _normalize_detect_list(self, values, length):
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

    def _normalize_state_list(self, values, length):
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

    def _sensor_state_to_text(self, state_value, detected):
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

    def render_dashboard(self):
        self._clear()
        sensor = self.runtime["sensor"]
        raw = sensor["raw"]
        norm = sensor["norm"]

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        mqtt_status = "已連線" if self.connected else "未連線"
        print(f"時間: {now}")
        print(f"MQTT: {mqtt_status}    Broker: {MQTT_BROKER}:{MQTT_PORT}")
        print(f"最後事件: {self.runtime['last_event']}")
        print(f"最後 Topic: {self.runtime['last_topic']}")
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
            detect_text = self._sensor_state_to_text(state_value, detected)
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
        for motor in self.runtime["motors"]:
            running = "ON" if motor.get("running") else "OFF"
            detected = motor.get("detected")
            if self.runtime.get("motor_detection_supported", False):
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
        if self.runtime["events"]:
            for line in list(self.runtime["events"]):
                print(line)
        else:
            print("(尚無事件)")

    def on_connect(self, client, userdata, flags, reason_code, properties=None):
        self.connected = True
        client.subscribe(TOPIC_SENSOR)
        client.subscribe(TOPIC_ACK)
        client.subscribe(TOPIC_STATE)
        client.subscribe(TOPIC_STATUS)
        if self.pretty_mode:
            self._push_event(f"MQTT 已連線 (code={reason_code})")
            self.render_dashboard()
        else:
            print(f"connected code={reason_code}")

    def on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties=None):
        self.connected = False
        if self.pretty_mode:
            self._push_event(f"MQTT 已斷線 (code={reason_code})")
            self.render_dashboard()
        else:
            print(f"disconnected code={reason_code}")

    def on_message(self, client, userdata, msg):
        text = msg.payload.decode("utf-8", errors="ignore")
        self.runtime["last_topic"] = msg.topic
        try:
            data = json.loads(text)
        except Exception:
            data = {"raw": text}

        if msg.topic == TOPIC_SENSOR and isinstance(data, dict):
            self.runtime["sensor"]["device_id"] = data.get("device_id", "unknown")
            self.runtime["sensor"]["ts"] = int(data.get("ts", 0) or 0)
            self.runtime["sensor"]["raw"] = self._normalize_int_list(data.get("raw", []), len(SENSOR_LABELS))
            self.runtime["sensor"]["norm"] = self._normalize_int_list(data.get("norm", []), len(SENSOR_LABELS))
            if "sensor_detected" in data:
                self.runtime["sensor"]["detected"] = self._normalize_detect_list(
                    data.get("sensor_detected", []), len(SENSOR_LABELS)
                )
            if "sensor_state" in data:
                self.runtime["sensor"]["state"] = self._normalize_state_list(
                    data.get("sensor_state", []), len(SENSOR_LABELS)
                )
            self._push_event("收到感測器資料更新")
            if not self.pretty_mode:
                print(
                    json.dumps(
                        {
                            "topic": msg.topic,
                            "device_id": data.get("device_id", "unknown"),
                            "raw": self.runtime["sensor"]["raw"],
                            "norm": self.runtime["sensor"]["norm"],
                        },
                        ensure_ascii=False,
                    )
                )
        elif msg.topic == TOPIC_ACK:
            self.last_ack = data
            self._ack_event.set()
            self._push_event(
                "ACK "
                f"cmd_id={data.get('cmd_id', 'unknown') if isinstance(data, dict) else 'unknown'} "
                f"status={data.get('status', 'unknown') if isinstance(data, dict) else 'unknown'}"
            )
            if not self.pretty_mode:
                print(json.dumps({"topic": msg.topic, "ack": data}, ensure_ascii=False))
        elif msg.topic == TOPIC_STATE and isinstance(data, dict):
            motors = data.get("motors", [])
            for motor_data in motors:
                motor_id = int(motor_data.get("id", 0) or 0)
                if 1 <= motor_id <= MOTOR_COUNT:
                    idx = motor_id - 1
                    self.runtime["motors"][idx]["running"] = bool(motor_data.get("running", False))
                    self.runtime["motors"][idx]["intensity"] = int(motor_data.get("intensity", 0) or 0)
                    self.runtime["motors"][idx]["remaining_ms"] = int(motor_data.get("remaining_ms", 0) or 0)
            self._push_event(f"馬達狀態更新: event={data.get('event', 'unknown')}")
            if not self.pretty_mode:
                print(json.dumps({"topic": msg.topic, "data": data}, ensure_ascii=False))
        elif msg.topic == TOPIC_STATUS and isinstance(data, dict):
            if data.get("event") == "hardware_report":
                self.runtime["sensor"]["detected"] = self._normalize_detect_list(
                    data.get("sensor_detected", []), len(SENSOR_LABELS)
                )
                self.runtime["motor_detection_supported"] = bool(
                    data.get("motor_detection_supported", False)
                )
                motor_detected = data.get("motor_detected", [])
                for i in range(MOTOR_COUNT):
                    marker = motor_detected[i] if isinstance(motor_detected, list) and i < len(motor_detected) else None
                    if isinstance(marker, bool):
                        self.runtime["motors"][i]["detected"] = marker
                    else:
                        self.runtime["motors"][i]["detected"] = None
            self._push_event(
                "STATUS "
                f"event={data.get('event', 'unknown')} "
                f"msg={data.get('message', '')}"
            )
            if not self.pretty_mode:
                print(json.dumps({"topic": msg.topic, "data": data}, ensure_ascii=False))
        else:
            if self.pretty_mode:
                self._push_event(f"收到未分類 Topic: {msg.topic}")
            else:
                print(json.dumps({"topic": msg.topic, "data": data}, ensure_ascii=False))

        if self.pretty_mode:
            self.render_dashboard()

    def connect(self):
        self.client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
        self.client.loop_start()

    def close(self):
        try:
            self.client.loop_stop()
            self.client.disconnect()
        except Exception:
            pass

    def send_single(self, motor_id, intensity, duration_ms, stagger_ms=80, cmd_id=None, wait_ack_sec=3.0):
        motor_id = max(1, min(MOTOR_COUNT, int(motor_id)))
        intensity = max(0, min(100, int(intensity)))
        duration_ms = max(50, min(5000, int(duration_ms)))
        stagger_ms = max(0, min(500, int(stagger_ms)))

        if not cmd_id:
            cmd_id = f"cmd-{uuid.uuid4().hex[:8]}"

        payload = {
            "cmd_id": cmd_id,
            "motor_id": motor_id,
            "intensity": intensity,
            "duration_ms": duration_ms,
            "stagger_ms": stagger_ms,
        }

        self._ack_event.clear()
        self.last_ack = None
        self.client.publish(TOPIC_CMD, json.dumps(payload, ensure_ascii=False))

        if self._ack_event.wait(timeout=wait_ack_sec):
            return self.last_ack
        return {"status": "timeout", "cmd_id": cmd_id}

    def send_multi(self, motors, stagger_ms=80, cmd_id=None, wait_ack_sec=3.0):
        clean = []
        for item in motors:
            try:
                mid = max(1, min(MOTOR_COUNT, int(item["id"])))
                inten = max(0, min(100, int(item["intensity"])))
                dur = max(50, min(5000, int(item["duration_ms"])))
            except Exception:
                continue
            clean.append({"id": mid, "intensity": inten, "duration_ms": dur})

        if not clean:
            return {"status": "error", "message": "no_valid_motor_data"}

        if not cmd_id:
            cmd_id = f"cmd-{uuid.uuid4().hex[:8]}"

        payload = {
            "cmd_id": cmd_id,
            "stagger_ms": max(0, min(500, int(stagger_ms))),
            "motors": clean,
        }

        self._ack_event.clear()
        self.last_ack = None
        self.client.publish(TOPIC_CMD, json.dumps(payload, ensure_ascii=False))

        if self._ack_event.wait(timeout=wait_ack_sec):
            return self.last_ack
        return {"status": "timeout", "cmd_id": cmd_id}

    def stop_all(self, cmd_id=None, wait_ack_sec=3.0):
        if not cmd_id:
            cmd_id = f"stop-{uuid.uuid4().hex[:8]}"
        payload = {"cmd_id": cmd_id, "stop_all": True}

        self._ack_event.clear()
        self.last_ack = None
        self.client.publish(TOPIC_CMD, json.dumps(payload, ensure_ascii=False))

        if self._ack_event.wait(timeout=wait_ack_sec):
            return self.last_ack
        return {"status": "timeout", "cmd_id": cmd_id}


def parse_args():
    parser = argparse.ArgumentParser(description="Minimal MQTT client for smart chair agent integration")
    parser.add_argument("--mode", choices=["listen", "single", "multi", "stop"], default="listen")
    parser.add_argument("--motor-id", type=int, default=1)
    parser.add_argument("--intensity", type=int, default=70)
    parser.add_argument("--duration-ms", type=int, default=800)
    parser.add_argument("--stagger-ms", type=int, default=80)
    parser.add_argument(
        "--motors-json",
        type=str,
        default='[{"id":1,"intensity":60,"duration_ms":900},{"id":2,"intensity":60,"duration_ms":900}]',
    )
    parser.add_argument("--listen-sec", type=int, default=0, help="0 means keep listening")
    parser.add_argument("--raw-output", action="store_true", help="disable table dashboard and print raw JSON lines")
    return parser.parse_args()


def main():
    reconfigure_stdout = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure_stdout):
        reconfigure_stdout(encoding="utf-8", errors="replace")

    args = parse_args()
    pretty_mode = (args.mode == "listen") and (not args.raw_output)
    cli = MinimalClient(pretty_mode=pretty_mode)

    try:
        cli.connect()
        time.sleep(0.4)

        if args.mode == "single":
            ack = cli.send_single(args.motor_id, args.intensity, args.duration_ms, args.stagger_ms)
            print(json.dumps({"result": ack}, ensure_ascii=False))
        elif args.mode == "multi":
            motors = json.loads(args.motors_json)
            ack = cli.send_multi(motors, args.stagger_ms)
            print(json.dumps({"result": ack}, ensure_ascii=False))
        elif args.mode == "stop":
            ack = cli.stop_all()
            print(json.dumps({"result": ack}, ensure_ascii=False))

        if args.mode == "listen" or args.listen_sec > 0:
            if args.listen_sec <= 0:
                while True:
                    time.sleep(1)
            else:
                end_time = time.time() + args.listen_sec
                while time.time() < end_time:
                    time.sleep(0.2)

    except KeyboardInterrupt:
        pass
    finally:
        cli.close()


if __name__ == "__main__":
    main()
