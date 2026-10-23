# 功能：顯示椅子即時姿勢資料、MQTT 連線狀態、電量資訊、重心位置與感測器壓力分佈。
# 預設會嘗試連線到 MQTT 讀取實際感測器資料。
# 啟動方式（在專案根目錄執行）：
#   .\.venv\Scripts\python.exe .\感測器配置\receiver\pose_demo.py
import json
import os
import ssl
import threading
import time
import tkinter as tk
from pathlib import Path
from typing import Dict, Optional, Tuple

import paho.mqtt.client as mqtt
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")
legacy_env = Path(__file__).resolve().parent / ".env"
if legacy_env.exists():
    load_dotenv(legacy_env, override=False)

MQTT_BROKER = os.getenv("MQTT_BROKER", "d8806e09.ala.eu-central-1.emqxsl.com")
MQTT_PORT = int(os.getenv("MQTT_PORT", "8883"))
MQTT_USER = os.getenv("MQTT_USER")
MQTT_PASS = os.getenv("MQTT_PASS")
MQTT_TOPIC_SENSOR = os.getenv("MQTT_TOPIC_SENSOR", "chair/pressure/01")
MQTT_TOPIC_VIB_STATE = os.getenv("MQTT_TOPIC_VIB_STATE", "chair/vibration/01/state")
MQTT_TOPIC_VIB_STATUS = os.getenv("MQTT_TOPIC_VIB_STATUS", "chair/vibration/01/status")

# Sensor map for the 11 positions.
# Seat sensors: 1..8, back sensors: 9..11
# 1 right-back, 2 right-mid, 3 right-front, 4 center-back, 5 center-front,
# 6 left-front, 7 left-mid, 8 left-back, 9 back-lower, 10 back-mid, 11 back-upper
SENSOR_POS = {
    1: (0.82, 0.18),
    2: (0.82, 0.42),
    3: (0.82, 0.72),
    4: (0.50, 0.18),
    5: (0.50, 0.72),
    6: (0.18, 0.72),
    7: (0.18, 0.42),
    8: (0.18, 0.18),
    9: (0.35, 0.10),
    10: (0.50, 0.05),
    11: (0.65, 0.10),
}

SEAT_SENSORS = range(1, 9)
# 與 ESP32 韌體相同：中立點 = 坐墊感測器座標平均，重心在半徑內（綠環）為 normal。
# 收到 ESP32 的 pose.neutral_x / neutral_y / normal_radius 時以韌體數值為準。
DEFAULT_NEUTRAL = (
    sum(SENSOR_POS[i][0] for i in SEAT_SENSORS) / len(SEAT_SENSORS),
    sum(SENSOR_POS[i][1] for i in SEAT_SENSORS) / len(SEAT_SENSORS),
)
DEFAULT_NORMAL_RADIUS = 0.07

MOTOR_POS = {
    1: (0.78, 0.88),
    2: (0.78, 0.20),
    3: (0.22, 0.20),
    4: (0.22, 0.88),
}


def clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, value))


def as_float_or_none(value) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def format_battery_text(power: dict, online: bool) -> str:
    # 電池電壓與 % 數皆由 ESP32 換算（分壓還原 → 平滑 → 與滿電比較），這裡只負責顯示。
    if not power:
        return "電量：--%"
    suffix = "" if online else "（離線）"
    if power.get("battery_present") is False:
        return f"電量：未偵測到電池{suffix}"
    voltage = as_float_or_none(power.get("voltage_v"))
    pct = as_float_or_none(power.get("battery_pct"))
    pct_text = f"{int(clamp(pct, 0.0, 100.0))}%" if pct is not None else "--%"
    if voltage is not None and voltage > 0:
        return f"電量：{pct_text} / {voltage:.2f} V{suffix}"
    return f"電量：{pct_text}{suffix}"


def decide_pose_label(offset_x: float, offset_y: float, normal_radius: float) -> str:
    # 座標：x 小 = 左、y 小 = 後（靠椅背）、y 大 = 前
    if (offset_x ** 2 + offset_y ** 2) ** 0.5 < normal_radius:
        return "normal"
    if abs(offset_x) >= abs(offset_y):
        return "left_lean" if offset_x < 0 else "right_lean"
    return "forward_lean" if offset_y > 0 else "backward_lean"


def compute_posture(values: Dict[int, float]) -> Tuple[str, float, float, float, float]:
    # 沒有收到 ESP32 pose 時的備援計算，邏輯與韌體 computePostureSummary 一致。
    s1, s2, s3, s4, s5, s6, s7, s8 = [values.get(i, 0.0) for i in SEAT_SENSORS]
    left_total = s6 + s7 + s8
    right_total = s1 + s2 + s3
    front_total = s3 + s5 + s6
    back_total = s1 + s4 + s8
    total = sum(values.get(i, 0.0) for i in SEAT_SENSORS)
    neutral_x, neutral_y = DEFAULT_NEUTRAL

    if total < 8:
        return "no_occupancy", 0.0, 0.0, neutral_x, neutral_y

    lr = (right_total - left_total) / max(left_total + right_total, 1.0)
    fb = (back_total - front_total) / max(front_total + back_total, 1.0)

    center_x = sum(values.get(i, 0.0) * SENSOR_POS[i][0] for i in SEAT_SENSORS) / total
    center_y = sum(values.get(i, 0.0) * SENSOR_POS[i][1] for i in SEAT_SENSORS) / total
    label = decide_pose_label(center_x - neutral_x, center_y - neutral_y, DEFAULT_NORMAL_RADIUS)
    return label, lr, fb, center_x, center_y


def parse_pose_reference(payload: dict) -> Tuple[float, float, float]:
    pose = payload.get("pose") if isinstance(payload, dict) else None
    if isinstance(pose, dict):
        neutral_x = as_float_or_none(pose.get("neutral_x"))
        neutral_y = as_float_or_none(pose.get("neutral_y"))
        radius = as_float_or_none(pose.get("normal_radius"))
        if neutral_x is not None and neutral_y is not None and radius is not None and radius > 0:
            return neutral_x, neutral_y, radius
    return DEFAULT_NEUTRAL[0], DEFAULT_NEUTRAL[1], DEFAULT_NORMAL_RADIUS


def idle_sensor_values() -> Dict[int, float]:
    return {i: 0.0 for i in range(1, 12)}


def parse_payload_to_sensor_values(payload: dict) -> Dict[int, float]:
    values = idle_sensor_values()
    if not isinstance(payload, dict):
        return values

    if "pose" in payload and isinstance(payload["pose"], dict):
        pose = payload["pose"]
        for key in ("norm", "raw"):
            if key in pose and isinstance(pose[key], list):
                values_list = pose[key]
                for idx, value in enumerate(values_list[:11], start=1):
                    try:
                        values[idx] = clamp(float(value), 0.0, 100.0)
                    except (TypeError, ValueError):
                        continue
                return values

    norm_values = payload.get("norm")
    if isinstance(norm_values, list):
        for idx, value in enumerate(norm_values[:11], start=1):
            try:
                values[idx] = clamp(float(value), 0.0, 100.0)
            except (TypeError, ValueError):
                continue
        return values

    raw_values = payload.get("raw")
    if isinstance(raw_values, list):
        for idx, value in enumerate(raw_values[:11], start=1):
            try:
                normalized = (float(value) / 32767.0) * 100.0
                values[idx] = clamp(normalized, 0.0, 100.0)
            except (TypeError, ValueError):
                continue
    return values


def parse_pose_summary(payload: dict) -> Optional[Tuple[str, float, float, float, float]]:
    if not isinstance(payload, dict):
        return None
    pose = payload.get("pose")
    if not isinstance(pose, dict):
        return None

    label = pose.get("label")
    if not isinstance(label, str):
        return None

    lr_raw = pose.get("left_right_balance")
    fb_raw = pose.get("front_back_balance")
    center_x_raw = pose.get("center_x")
    center_y_raw = pose.get("center_y")

    try:
        lr = float(lr_raw)
        fb = float(fb_raw)
        center_x = clamp(float(center_x_raw), 0.0, 1.0)
        center_y = clamp(float(center_y_raw), 0.0, 1.0)
    except (TypeError, ValueError):
        return None
    return label, lr, fb, center_x, center_y


def is_running_flag(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return int(value) != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "on", "running"}
    return False


def parse_motor_state(payload: dict) -> Optional[set[int]]:
    motors = set()
    if not isinstance(payload, dict):
        return None

    items = payload.get("motors")
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            motor_id = item.get("id")
            running = is_running_flag(item.get("running"))
            if isinstance(motor_id, int) and running:
                motors.add(motor_id)
                continue
            if isinstance(motor_id, str):
                try:
                    motor_id_int = int(motor_id)
                except ValueError:
                    continue
                if running:
                    motors.add(motor_id_int)
        return motors

    has_motor_field = False
    for motor_id in range(1, 5):
        state = payload.get(f"motor_{motor_id}")
        if state is None:
            continue
        has_motor_field = True
        if isinstance(state, dict) and is_running_flag(state.get("running")):
            motors.add(motor_id)
        elif is_running_flag(state):
            motors.add(motor_id)
    if has_motor_field:
        return motors
    return None


class ChairMqttMonitor:
    def __init__(self):
        self.connected = False
        self.latest_sensor_payload = {}
        self.latest_motor_state = {}
        self.latest_motor_status = {}
        self.latest_payload = {}
        self.last_message_time = 0.0
        self.lock = threading.Lock()

        callback_api = getattr(mqtt, "CallbackAPIVersion", None)
        if callback_api and hasattr(callback_api, "VERSION2"):
            self.client = mqtt.Client(callback_api_version=callback_api.VERSION2)
        else:
            self.client = mqtt.Client()

        if MQTT_USER and MQTT_PASS:
            self.client.username_pw_set(MQTT_USER, MQTT_PASS)
        self.client.tls_set(tls_version=ssl.PROTOCOL_TLS_CLIENT)
        self.client.tls_insecure_set(False)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        self.connected = True
        client.subscribe(MQTT_TOPIC_SENSOR)
        client.subscribe(MQTT_TOPIC_VIB_STATE)
        client.subscribe(MQTT_TOPIC_VIB_STATUS)

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties=None):
        self.connected = False

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8", errors="replace"))
        except Exception:
            return

        if not isinstance(payload, dict):
            return

        topic = msg.topic
        with self.lock:
            self.latest_payload = payload
            self.last_message_time = time.time()
            self.connected = True
            if topic == MQTT_TOPIC_SENSOR:
                self.latest_sensor_payload = payload
            elif topic == MQTT_TOPIC_VIB_STATE:
                self.latest_motor_state = payload
            elif topic == MQTT_TOPIC_VIB_STATUS:
                self.latest_motor_status = payload

    def connect(self):
        try:
            self.client.connect(MQTT_BROKER, MQTT_PORT, keepalive=30)
            self.client.loop_start()
        except Exception:
            self.connected = False

    def disconnect(self):
        try:
            self.client.loop_stop()
            self.client.disconnect()
        except Exception:
            pass
        self.connected = False


class ChairPoseDemo:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Chair Pose Demo")
        self.root.geometry("1280x760")
        self.root.configure(bg="#f2f2f2")
        self.mqtt_monitor = ChairMqttMonitor()
        self.mqtt_monitor.connect()

        self.connection_var = tk.StringVar(value="MQTT 連線狀態：檢查中...")
        self.battery_var = tk.StringVar(value="電量：--%")
        self.last_update_var = tk.StringVar(value="最後更新：--")
        self.status_var = tk.StringVar(value="等待裝置資料...")

        top = tk.Frame(root, bg="#edf6ff", relief="solid", bd=1)
        top.pack(fill="x", padx=10, pady=(10, 0))
        tk.Label(top, textvariable=self.connection_var, bg="#edf6ff", fg="#1b3a5b", font=("Arial", 12, "bold"), padx=12, pady=8).pack(side="left")
        tk.Label(top, textvariable=self.battery_var, bg="#edf6ff", fg="#1b3a5b", font=("Arial", 12), padx=12, pady=8).pack(side="left")
        tk.Label(top, textvariable=self.last_update_var, bg="#edf6ff", fg="#1b3a5b", font=("Arial", 12), padx=12, pady=8).pack(side="left", fill="x", expand=True)

        tk.Label(root, textvariable=self.status_var, bg="#dfefff", relief="solid", padx=10, pady=6,
                 font=("Arial", 12)).pack(fill="x", padx=10, pady=(8, 0))

        self.main = tk.Frame(root, bg="#f2f2f2")
        self.main.pack(fill="both", expand=True, padx=10, pady=10)

        self.left = tk.Frame(self.main, bg="#f2f2f2")
        self.left.pack(side="left", fill="both", expand=True)
        self.cop_canvas = tk.Canvas(self.left, width=520, height=420, bg="#fafafa", highlightthickness=0)
        self.cop_canvas.pack(padx=8, pady=8)

        self.right = tk.Frame(self.main, bg="#f2f2f2")
        self.right.pack(side="left", fill="both", expand=True)
        self.sensor_canvas = tk.Canvas(self.right, width=320, height=420, bg="#fafafa", highlightthickness=0)
        self.sensor_canvas.pack(padx=8, pady=8)

        self.chair_canvas = tk.Canvas(root, width=700, height=270, bg="#fafafa", highlightthickness=0)
        self.chair_canvas.pack(fill="x", padx=10, pady=(0, 10))

        self.sensor_values = idle_sensor_values()
        self.motor_active = {1: False, 2: False, 3: False, 4: False}
        self.current_posture = ("normal", 0.0, 0.0, DEFAULT_NEUTRAL[0], DEFAULT_NEUTRAL[1])
        self.pose_reference = (DEFAULT_NEUTRAL[0], DEFAULT_NEUTRAL[1], DEFAULT_NORMAL_RADIUS)
        self.last_label = "normal"
        self.last_payload = {}
        self._tick()

    def _tick(self):
        self.sensor_values = idle_sensor_values()
        payload = {}
        motor_payload = {}
        with self.mqtt_monitor.lock:
            payload = self.mqtt_monitor.latest_sensor_payload.copy()
            motor_payload = self.mqtt_monitor.latest_motor_state.copy()
        if self.mqtt_monitor.connected:
            if payload:
                self.sensor_values = parse_payload_to_sensor_values(payload)
            self.connection_var.set("MQTT 連線狀態：已連線")
        else:
            self.connection_var.set("MQTT 連線狀態：未連線")
        power = payload.get("power", {}) if isinstance(payload, dict) else {}
        self.battery_var.set(format_battery_text(power, self.mqtt_monitor.connected))
        if self.mqtt_monitor.last_message_time:
            self.last_update_var.set(f"最後更新：{time.strftime('%H:%M:%S', time.localtime(self.mqtt_monitor.last_message_time))}")
        else:
            self.last_update_var.set("最後更新：尚未接收到資料")

        active = parse_motor_state(motor_payload)
        if active is not None:
            self.motor_active = {motor_id: motor_id in active for motor_id in range(1, 5)}
        pose_summary = parse_pose_summary(payload)
        if pose_summary is not None:
            self.current_posture = pose_summary
        else:
            self.current_posture = compute_posture(self.sensor_values)
        self.pose_reference = parse_pose_reference(payload)

        label, lr, fb, center_x, center_y = self.current_posture
        self.status_var.set(f"姿勢: {label} | 左右偏移={lr:.2f} | 前後偏移={fb:.2f} | 重心=({center_x:.2f}, {center_y:.2f})")
        self.draw_cop()
        self.draw_sensors()
        self.draw_chair()
        self.root.after(120, self._tick)

    def draw_cop(self):
        self.cop_canvas.delete("all")
        x0, y0 = 20, 20
        w, h = 460, 360
        self.cop_canvas.create_rectangle(x0, y0, x0 + w, y0 + h, outline="black", width=2)
        cx = x0 + w / 2
        cy = y0 + h / 2
        self.cop_canvas.create_line(cx, y0, cx, y0 + h, fill="black", width=1.5)
        self.cop_canvas.create_line(x0, cy, x0 + w, cy, fill="black", width=1.5)

        label, _, _, center_x, center_y = self.current_posture
        neutral_x, neutral_y, normal_radius = self.pose_reference
        # 圖中心 = 中立點；紅點與圓環使用同一座標換算，紅點在綠環內 ⇔ 判定 normal
        px = clamp(cx + (center_x - neutral_x) * w, x0, x0 + w)
        py = clamp(cy + (center_y - neutral_y) * h, y0, y0 + h)

        ring_colors = [("#7ad676", 1.0), ("#ffd966", 2.0), ("#ff8d5c", 3.0)]
        for color, scale in ring_colors:
            rx = normal_radius * scale * w
            ry = normal_radius * scale * h
            ring_width = 2 if scale == 1.0 else 1
            self.cop_canvas.create_oval(cx - rx, cy - ry, cx + rx, cy + ry, outline=color, width=ring_width, dash=(6, 5))

        if label == "no_occupancy":
            dot_fill = "#bdbdbd"
            dot_text = "未入座"
        elif label == "normal":
            dot_fill = "#2ecc71"
            dot_text = "正常"
        else:
            dot_fill = "#e74c3c"
            dot_text = "姿勢偏移"

        self.cop_canvas.create_oval(px - 6, py - 6, px + 6, py + 6, fill=dot_fill, outline="black", width=2)
        self.cop_canvas.create_text(cx, y0 + 12, text=f"重心區域：{dot_text}", font=("Arial", 11), anchor="n")
        self.cop_canvas.create_text(cx, y0 - 8, text="重心", font=("Arial", 12), anchor="s")
        self.cop_canvas.create_text(x0 + w + 8, cy, text="右", anchor="w", font=("Arial", 11))
        self.cop_canvas.create_text(x0 - 8, cy, text="左", anchor="e", font=("Arial", 11))
        self.cop_canvas.create_text(cx, y0 + h + 14, text="前", anchor="n", font=("Arial", 11))
        self.cop_canvas.create_text(cx, y0 - 14, text="後", anchor="s", font=("Arial", 11))

    def draw_sensors(self):
        self.sensor_canvas.delete("all")
        x0, y0 = 20, 30
        bar_w = 18
        gap = 8
        for i in range(1, 12):
            value = self.sensor_values.get(i, 0.0)
            h = 220 * (value / 100.0)
            x = x0 + (i - 1) * (bar_w + gap)
            y = 240 - h
            r = int(40 + value * 1.4)
            g = int(100 + value * 1.1)
            b = int(180 + value * 0.7)
            color = f"#{r:02x}{g:02x}{b:02x}"
            self.sensor_canvas.create_rectangle(x, y, x + bar_w, 240, fill=color, outline="black", width=1)
            self.sensor_canvas.create_text(x + bar_w / 2, 255, text=str(i), font=("Arial", 8))

    def draw_chair(self):
        self.chair_canvas.delete("all")
        x0, y0 = 30, 30
        w, h = 620, 200
        self.chair_canvas.create_rectangle(x0, y0, x0 + w, y0 + h, outline="black", width=2)
        self.chair_canvas.create_rectangle(x0 + 80, y0 + 20, x0 + w - 80, y0 + h - 30, outline="black", width=2)

        for motor_id, (px, py) in MOTOR_POS.items():
            mx = x0 + px * w
            my = y0 + py * h
            r = 14 if self.motor_active[motor_id] else 10
            fill = "#ffcc00" if self.motor_active[motor_id] else "#d4d4d4"
            outline = "#ff6600" if self.motor_active[motor_id] else "#666666"
            self.chair_canvas.create_oval(mx - r, my - r, mx + r, my + r, fill=fill, outline=outline, width=2)

        label = self.current_posture[0]
        self.chair_canvas.create_text(x0 + w / 2, y0 + h + 22, text=f"目前姿勢：{label}", font=("Arial", 12, "bold"), anchor="n")


if __name__ == "__main__":
    root = tk.Tk()
    ChairPoseDemo(root)
    root.mainloop()
