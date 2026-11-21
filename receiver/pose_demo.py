# 功能：顯示椅子即時姿勢、重心、感測器壓力、久坐計時、事件紀錄、馬達與 LED 燈條狀態（對應韌體 v2）。
# 啟動方式（在專案根目錄執行）：
#   .\.venv\Scripts\python.exe .\感測器配置\receiver\pose_demo.py
# .env 可設定 CHAIR_DEVICE_ID=chair_A1B2C3 只看一張椅子；不設定則接收所有椅子，可在畫面上方切換。
import colorsys
import json
import os
import ssl
import threading
import time
import tkinter as tk
from collections import deque
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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
# 韌體 v2 起 topic 為 chair/{device_id}/...，device_id 開機時印在序列埠（例如 chair_A1B2C3）。
CHAIR_DEVICE_ID = os.getenv("CHAIR_DEVICE_ID") or "+"
SUBSCRIBE_TOPICS = [
    f"chair/{CHAIR_DEVICE_ID}/pressure",
    f"chair/{CHAIR_DEVICE_ID}/online",
    f"chair/{CHAIR_DEVICE_ID}/vibration/state",
    f"chair/{CHAIR_DEVICE_ID}/vibration/status",
]

# ── 與韌體相同的常數 ──
SENSOR_POS = {
    1: (0.82, 0.18), 2: (0.82, 0.42), 3: (0.82, 0.72), 4: (0.50, 0.18),
    5: (0.50, 0.72), 6: (0.18, 0.72), 7: (0.18, 0.42), 8: (0.18, 0.18),
    9: (0.50, 0.10), 10: (0.50, 0.06), 11: (0.50, 0.02),   # 椅背中線由下而上
}
SEAT_SENSORS = range(1, 9)
DEFAULT_NEUTRAL = (
    sum(SENSOR_POS[i][0] for i in SEAT_SENSORS) / len(SEAT_SENSORS),
    sum(SENSOR_POS[i][1] for i in SEAT_SENSORS) / len(SEAT_SENSORS),
)
DEFAULT_NORMAL_RADIUS = 0.055
DEFAULT_SITTING_LIMIT_MIN = 30

LEDS_PER_STRIP = 35
LED_MIN_PCT, LED_BASE_PCT, LED_MAX_PCT = 20, 50, 80
LED_LEAN_FULL_RADII = 1.0
BACKWARD_RADIUS_SCALE = 0.6   # 與韌體相同（倍率越小越容易判定）
LATERAL_RADIUS_SCALE = 0.8    # 與韌體相同
FORWARD_RADIUS_SCALE = 1.1    # 與韌體相同
LED_SMOOTH_ALPHA = 0.3
LED_ALERT_BLINK_S = 10.0

MOTOR_NAMES = {1: "右扶手", 2: "右靠背", 3: "左靠背", 4: "左扶手"}
LABEL_ZH = {
    "normal": "正常", "left_lean": "左傾", "right_lean": "右傾",
    "forward_lean": "前傾", "backward_lean": "後仰", "no_occupancy": "未入座",
}
LED_OFF_RGB = (0xd6, 0xd9, 0xde)   # 白底上「熄滅／暗」的燈珠顏色
LED_OFF_HEX = "#%02x%02x%02x" % LED_OFF_RGB
MOTOR_HOLD_S = 0.8          # 馬達只震 0.1~0.3 秒，畫面上多亮一下才看得到
# 斷線判斷：韌體有人坐至少每 5 秒、沒人坐每 30 秒送一筆 pressure。
# 超過下列秒數沒收到任何即時訊息就先標「疑似斷線」，不必等 LWT（約 20~25 秒）。
SILENT_LIMIT_SEATED_S = 12.0
SILENT_LIMIT_EMPTY_S = 40.0


# 字型：中文用標楷體，純數字／英文用 Times New Roman
ZH_FONT, EN_FONT = "DFKai-SB", "Times New Roman"


FONT_SCALE = 1.5   # 字級倍率
UI_SCALE = 1.15    # 圖形倍率（畫布用原座標繪製後整體放大）


def fz(size: int, bold: bool = False):
    size = round(size * FONT_SCALE)
    return (ZH_FONT, size, "bold") if bold else (ZH_FONT, size)


def fe(size: int, bold: bool = False):
    size = round(size * FONT_SCALE)
    return (EN_FONT, size, "bold") if bold else (EN_FONT, size)


def ui(v: float) -> int:
    return int(v * UI_SCALE)


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def as_float(value, default: Optional[float] = None) -> Optional[float]:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return default
    return default


def zh_label(label: str) -> str:
    return LABEL_ZH.get(label, label)


def fmt_mmss(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def format_battery_text(power: dict) -> str:
    # 電池電壓與 % 數皆由 ESP32 換算，這裡只負責顯示。v2 起 power 只在 sync 筆出現，顯示最後一次的值。
    if not power:
        return "電量：--%"
    if power.get("battery_present") is False:
        return "電量：未偵測到電池"
    voltage = as_float(power.get("voltage_v"))
    pct = as_float(power.get("battery_pct"))
    pct_text = f"{int(clamp(pct, 0, 100))}%" if pct is not None else "--%"
    if voltage:
        return f"電量：{pct_text} / {voltage:.2f} V"
    return f"電量：{pct_text}"


def decide_pose_label(offset_x: float, offset_y: float, normal_radius: float) -> str:
    if (offset_x ** 2 + offset_y ** 2) ** 0.5 < normal_radius:
        return "normal"
    if abs(offset_x) >= abs(offset_y):
        return "left_lean" if offset_x < 0 else "right_lean"
    return "forward_lean" if offset_y > 0 else "backward_lean"


def compute_posture(values: Dict[int, float]) -> Tuple[str, float, float, float, float]:
    # 沒有收到 ESP32 pose 時的備援計算，邏輯與韌體 computePostureSummary 一致。
    s1, s2, s3, s4, s5, s6, s7, s8 = [values.get(i, 0.0) for i in SEAT_SENSORS]
    left_total, right_total = s6 + s7 + s8, s1 + s2 + s3
    front_total, back_total = s3 + s5 + s6, s1 + s4 + s8
    total = sum(values.get(i, 0.0) for i in SEAT_SENSORS)
    nx, ny = DEFAULT_NEUTRAL
    if total < 8:
        return "no_occupancy", 0.0, 0.0, nx, ny
    lr = (right_total - left_total) / max(left_total + right_total, 1.0)
    fb = (back_total - front_total) / max(front_total + back_total, 1.0)
    cx = sum(values.get(i, 0.0) * SENSOR_POS[i][0] for i in SEAT_SENSORS) / total
    cy = sum(values.get(i, 0.0) * SENSOR_POS[i][1] for i in SEAT_SENSORS) / total
    return decide_pose_label(cx - nx, cy - ny, DEFAULT_NORMAL_RADIUS), lr, fb, cx, cy


def parse_sensor_values(payload: dict) -> Dict[int, float]:
    values = {i: 0.0 for i in range(1, 12)}
    norm = payload.get("norm") if isinstance(payload, dict) else None
    if isinstance(norm, list):
        for idx, v in enumerate(norm[:11], start=1):
            f = as_float(v)
            if f is not None:
                values[idx] = clamp(f, 0.0, 100.0)
    return values


def parse_pose(payload: dict) -> Optional[Tuple[str, float, float, float, float]]:
    pose = payload.get("pose") if isinstance(payload, dict) else None
    if not isinstance(pose, dict) or not isinstance(pose.get("label"), str):
        return None
    lr, fb = as_float(pose.get("left_right_balance")), as_float(pose.get("front_back_balance"))
    cx, cy = as_float(pose.get("center_x")), as_float(pose.get("center_y"))
    if None in (lr, fb, cx, cy):
        return None
    return pose["label"], lr, fb, clamp(cx, 0, 1), clamp(cy, 0, 1)


def parse_pose_reference(payload: dict) -> Tuple[float, float, float]:
    pose = payload.get("pose") if isinstance(payload, dict) else None
    if isinstance(pose, dict):
        nx, ny, r = as_float(pose.get("neutral_x")), as_float(pose.get("neutral_y")), as_float(pose.get("normal_radius"))
        if nx is not None and ny is not None and r:
            return nx, ny, r
    return DEFAULT_NEUTRAL[0], DEFAULT_NEUTRAL[1], DEFAULT_NORMAL_RADIUS


def running_motor_ids(payload: dict) -> Optional[set]:
    items = payload.get("motors") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return None
    running = set()
    for item in items:
        if isinstance(item, dict) and item.get("running") is True:
            try:
                running.add(int(item.get("id")))
            except (TypeError, ValueError):
                continue
    return running


def motor_names(ids) -> str:
    try:
        return "、".join(MOTOR_NAMES.get(int(i), f"M{i}") for i in ids)
    except (TypeError, ValueError):
        return str(ids)


def format_event(p: dict) -> Optional[str]:
    e = p.get("event")
    if e == "posture_reminder":
        return (f"坐姿提醒：{zh_label(p.get('message', ''))} 第 {p.get('level', '?')} 級，"
                f"已持續 {p.get('duration_s', '?')} 秒，震 {motor_names(p.get('motors', []))} {p.get('intensity', '?')}%")
    if e == "sedentary_reminder":
        return f"久坐提醒：已坐 {p.get('sitting_min', '?')} 分鐘（上限 {p.get('limit_min', '?')}），四顆馬達震動"
    if e == "left_seat":
        return f"起身離開：這次坐了 {fmt_mmss(as_float(p.get('sitting_s'), 0))}，久坐計時歸零"
    if e == "config_applied":
        return f"套用中立點 {p.get('cmd')}：({p.get('neutral_x')}, {p.get('neutral_y')}) 半徑 {p.get('normal_radius')}"
    if e == "config_rejected":
        return f"拒絕中立點設定：{p.get('reason')}"
    if e == "neutral_reset":
        return "離座，中立點退回預設值"
    if e == "calibration_started":
        return f"開始校正（{p.get('duration_s')} 秒，請坐正不動）"
    if e == "calibrated":
        return f"校正成功：中立點 ({p.get('neutral_x')}, {p.get('neutral_y')})，穩定 {p.get('stable_pct')}%"
    if e == "calibration_failed":
        return f"校正失敗：{p.get('reason')}"
    if e == "hardware_report":
        ads = p.get("ads", {})
        ok = [k for k, v in ads.items() if v] if isinstance(ads, dict) else []
        return f"硬體報告：韌體 {p.get('fw', '?')}，ADS {len(ok)}/3，久坐上限 {p.get('sitting_limit_min', '?')} 分"
    if e == "sensor_state_changed":
        states = p.get("sensor_state", [])
        bad = [f"S{i + 1}:{s}" for i, s in enumerate(states) if s != "installed"] if isinstance(states, list) else []
        return "感測器狀態：" + ("全部正常" if not bad else "、".join(bad))
    if e == "mqtt_connected":
        return "椅子連上 MQTT"
    if e == "safety_timeout":
        return "馬達異常開太久，已強制停機"
    return f"{e}" if e else None


class ChairState:
    def __init__(self, device_id: str):
        self.device_id = device_id
        self.pressure: dict = {}
        self.pressure_time = 0.0
        self.power: dict = {}
        self.online: Optional[bool] = None
        self.fw = ""
        self.events: deque = deque(maxlen=30)   # (本機時間, 文字)
        self.events_version = 0
        self.last_seq: Optional[int] = None
        self.lost_packets = 0
        self.packets = 0
        self.motor_last_running: Dict[int, float] = {i: 0.0 for i in range(1, 5)}
        self.sedentary_blink_start = 0.0
        self.sitting_limit_min = DEFAULT_SITTING_LIMIT_MIN
        self.last_live = time.time()   # 最後一次收到「即時」訊息（不含 retained 舊訊息）
        self.suspect = False           # 太久沒收到資料，疑似斷線

    def silent_limit(self) -> float:
        label = (self.pressure.get("pose") or {}).get("label") if self.pressure else None
        seated = label not in (None, "no_occupancy")
        return SILENT_LIMIT_SEATED_S if seated else SILENT_LIMIT_EMPTY_S

    def add_event(self, text: str, when: Optional[float] = None):
        self.events.appendleft((when or time.time(), text))
        self.events_version += 1


class ChairMqttMonitor:
    def __init__(self):
        self.connected = False
        self.chairs: Dict[str, ChairState] = {}
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

    def _on_connect(self, client, *_args):
        self.connected = True
        for topic in SUBSCRIBE_TOPICS:
            client.subscribe(topic)

    def _on_disconnect(self, *_args):
        self.connected = False

    def _chair(self, device_id: str) -> ChairState:
        if device_id not in self.chairs:
            self.chairs[device_id] = ChairState(device_id)
        return self.chairs[device_id]

    def _on_message(self, _client, _userdata, msg):
        parts = msg.topic.split("/")
        if len(parts) < 3 or parts[0] != "chair":
            return
        device_id, kind = parts[1], "/".join(parts[2:])
        try:
            payload = json.loads(msg.payload.decode("utf-8", errors="replace"))
        except Exception:
            return
        if not isinstance(payload, dict):
            return

        now = time.time()
        with self.lock:
            chair = self._chair(device_id)
            # retained 訊息可能是很久以前的，LWT 的 online:false 也不代表椅子還活著
            is_lwt = kind == "online" and payload.get("online") is not True
            if not getattr(msg, "retain", False) and not is_lwt:
                if chair.suspect:
                    chair.add_event(f"恢復收到資料（中斷約 {int(now - chair.last_live)} 秒）", now)
                chair.suspect = False
                chair.last_live = now
            if kind == "pressure":
                self._handle_pressure(chair, payload, now)
            elif kind == "online":
                online = payload.get("online") is True
                if chair.online is not None and online != chair.online:
                    chair.add_event("椅子上線" if online else "椅子斷線（LWT）", now)
                chair.online = online
                chair.fw = payload.get("fw", chair.fw)
            elif kind == "vibration/state":
                running = running_motor_ids(payload) or set()
                for mid in running:
                    if mid in chair.motor_last_running:
                        chair.motor_last_running[mid] = now
            elif kind == "vibration/status":
                self._handle_status(chair, payload, now)

    @staticmethod
    def _handle_pressure(chair: ChairState, payload: dict, now: float):
        chair.pressure = payload
        chair.pressure_time = now
        chair.packets += 1
        if isinstance(payload.get("power"), dict):
            chair.power = payload["power"]
        sitting = payload.get("sitting")
        if isinstance(sitting, dict) and as_float(sitting.get("limit_min")):
            chair.sitting_limit_min = as_float(sitting.get("limit_min"))
        seq = payload.get("seq")
        if isinstance(seq, int):
            if chair.last_seq is not None:
                if seq > chair.last_seq + 1:
                    chair.lost_packets += seq - chair.last_seq - 1
                elif seq <= chair.last_seq:
                    chair.add_event(f"椅子重開機（seq {chair.last_seq} → {seq}）", now)
            chair.last_seq = seq

    @staticmethod
    def _handle_status(chair: ChairState, payload: dict, now: float):
        event = payload.get("event")
        ts = as_float(payload.get("ts"))
        synced = payload.get("time_synced") is not False and ts is not None and ts > 1.7e9
        # 斷網期間暫存、連線後補送的事件：用椅子的時間顯示，也不觸發閃燈動畫
        when = ts if synced else now
        is_fresh = (not synced) or abs(now - ts) < 15

        if event == "sedentary_reminder" and is_fresh:
            chair.sedentary_blink_start = now
        if event in ("posture_reminder", "sedentary_reminder") and is_fresh:
            # 依實際震動時長亮燈（事件裡的 vibration_ms），畫面才跟實際震動一樣久
            dur_s = (as_float(payload.get("vibration_ms"), 0.0) or 0.0) / 1000.0
            for mid in payload.get("motors", []) or []:
                if isinstance(mid, int) and mid in chair.motor_last_running:
                    chair.motor_last_running[mid] = now + max(0.0, dur_s - MOTOR_HOLD_S)
        if event == "hardware_report":
            chair.fw = payload.get("fw", chair.fw)
            limit = as_float(payload.get("sitting_limit_min"))
            if limit:
                chair.sitting_limit_min = limit
        text = format_event(payload)
        if text:
            chair.add_event(text, when)

    def check_links(self, now: float):
        # 依預期送資料間隔判斷疑似斷線（每 100 ms 由畫面呼叫）
        with self.lock:
            for chair in self.chairs.values():
                if chair.online is False or chair.suspect:
                    continue
                silent = now - chair.last_live
                if silent > chair.silent_limit():
                    chair.suspect = True
                    chair.add_event(f"{int(silent)} 秒沒收到資料，疑似斷線", now)

    def connect(self):
        # connect_async + loop_start：一開始連不上或中途斷線都會自動重試
        self.client.reconnect_delay_set(min_delay=1, max_delay=10)
        try:
            self.client.connect_async(MQTT_BROKER, MQTT_PORT, keepalive=30)
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
    BG = "#f2f2f2"

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Chair Pose Demo v2")
        self.root.geometry("1880x1000+0+0")
        self.root.configure(bg=self.BG)
        self.monitor = ChairMqttMonitor()
        self.monitor.connect()

        self.selected_id = tk.StringVar(value="")
        self.connection_var = tk.StringVar(value="MQTT：連線中...")
        self.online_var = tk.StringVar(value="椅子：--")
        self.battery_var = tk.StringVar(value="電量：--%")
        self.last_update_var = tk.StringVar(value="最後更新：--")
        self.status_var = tk.StringVar(value="")

        top = tk.Frame(root, bg="#edf6ff", relief="solid", bd=1)
        top.pack(fill="x", padx=10, pady=(10, 0))
        font_b, font = fz(15, True), fz(15)
        tk.Label(top, textvariable=self.connection_var, bg="#edf6ff", fg="#1b3a5b", font=font_b, padx=10, pady=8).pack(side="left")
        tk.Label(top, text="椅子：", bg="#edf6ff", fg="#1b3a5b", font=font).pack(side="left")
        self.chair_menu = tk.OptionMenu(top, self.selected_id, "")
        self.chair_menu.configure(font=fe(14), width=14)
        self.chair_menu.pack(side="left")
        self.known_ids: List[str] = []
        self.online_label = tk.Label(top, textvariable=self.online_var, bg="#edf6ff", fg="#1b3a5b", font=font_b, padx=10)
        self.online_label.pack(side="left")
        tk.Label(top, textvariable=self.battery_var, bg="#edf6ff", fg="#1b3a5b", font=font, padx=10).pack(side="left")
        tk.Label(top, textvariable=self.status_var, bg="#edf6ff", fg="#1b3a5b", font=font, padx=10).pack(side="left")
        tk.Label(top, textvariable=self.last_update_var, bg="#edf6ff", fg="#1b3a5b", font=font, padx=10).pack(side="left")

        main = tk.Frame(root, bg=self.BG)
        main.pack(fill="x", padx=10, pady=(8, 0))
        self.cop_canvas = tk.Canvas(main, width=ui(520), height=ui(430), bg="#fafafa", highlightthickness=0)
        self.cop_canvas.pack(side="left", padx=(0, 8))
        self.sensor_canvas = tk.Canvas(main, width=ui(440), height=ui(430), bg="#fafafa", highlightthickness=0)
        self.sensor_canvas.pack(side="left", padx=(0, 8))

        side = tk.Frame(main, bg=self.BG)
        side.pack(side="left", fill="both", expand=True)
        self.sit_canvas = tk.Canvas(side, width=ui(470), height=ui(135), bg="#fafafa", highlightthickness=0)
        self.sit_canvas.pack(fill="x")
        tk.Label(side, text="事件紀錄", bg=self.BG, font=fz(16, True), anchor="w").pack(fill="x", pady=(8, 2))
        self.event_list = tk.Listbox(side, font=fz(13), height=7, activestyle="none")
        self.event_list.pack(fill="both", expand=True)
        self.shown_events_key = None

        self.chair_canvas = tk.Canvas(root, height=ui(360), bg="white", highlightthickness=1, highlightbackground="#d0d4da")
        self.chair_canvas.pack(fill="x", padx=10, pady=10)

        self.led_lean_left = 0.0
        self.led_lean_front = 0.0
        self.led_pos = [2 * (1 - abs(2 * i / (LEDS_PER_STRIP - 1) - 1)) - 1 for i in range(LEDS_PER_STRIP)]
        self._tick()

    # ── 資料 ──
    def _sync_chair_menu(self):
        ids = sorted(self.monitor.chairs.keys())
        if ids != self.known_ids:
            self.known_ids = ids
            menu = self.chair_menu["menu"]
            menu.delete(0, "end")
            for device_id in ids:
                menu.add_command(label=device_id, command=lambda v=device_id: self.selected_id.set(v))
        if not self.selected_id.get() and ids:
            self.selected_id.set(ids[0])

    def _snapshot(self) -> Optional[dict]:
        with self.monitor.lock:
            self._sync_chair_menu()
            chair = self.monitor.chairs.get(self.selected_id.get())
            if chair is None:
                return None
            return {
                "id": chair.device_id,
                "pressure": dict(chair.pressure),
                "pressure_time": chair.pressure_time,
                "power": dict(chair.power),
                "online": chair.online,
                "fw": chair.fw,
                "events": list(chair.events),
                "events_key": (chair.device_id, chair.events_version),
                "seq": chair.last_seq,
                "lost": chair.lost_packets,
                "packets": chair.packets,
                "motor_last": dict(chair.motor_last_running),
                "suspect": chair.suspect,
                "silent_s": time.time() - chair.last_live,
                "live": self.monitor.connected and chair.online is not False and not chair.suspect,
                "blink_start": chair.sedentary_blink_start,
                "limit_min": chair.sitting_limit_min,
            }

    def _tick(self):
        now = time.time()
        self.connection_var.set("MQTT：已連線" if self.monitor.connected else "MQTT：未連線（自動重試中）")
        self.monitor.check_links(now)
        snap = self._snapshot()

        if snap is None:
            self.online_var.set("（等待椅子連線…）")
            self.status_var.set("")
            payload, snap_view = {}, None
        else:
            payload, snap_view = snap["pressure"], snap
            if snap["online"] is False:
                online_text, online_fg = "● 離線（LWT 確認）", "#c0392b"
            elif not self.monitor.connected:
                online_text, online_fg = "● 電腦未連上 MQTT", "#c0392b"
            elif snap["suspect"]:
                online_text, online_fg = f"● 疑似斷線：{int(snap['silent_s'])} 秒沒資料", "#d35400"
            elif snap["online"] is True:
                online_text, online_fg = "● 在線", "#1e8449"
            else:
                online_text, online_fg = "● 收到資料（尚未收到 online）", "#1e8449"
            self.online_var.set(f"{online_text}" + (f"  韌體 {snap['fw']}" if snap["fw"] else ""))
            self.online_label.config(fg=online_fg)
            self.battery_var.set(format_battery_text(snap["power"]))
            self.last_update_var.set(
                "更新 " + (time.strftime("%H:%M:%S", time.localtime(snap["pressure_time"])) if snap["pressure_time"] else "--"))

        values = parse_sensor_values(payload)
        posture = parse_pose(payload) or compute_posture(values)
        reference = parse_pose_reference(payload)
        label, lr, fb, cx, cy = posture

        if snap_view is not None:
            pkt = payload.get("type", "-")
            self.status_var.set(
                f"已收 {snap_view['packets']} 筆，漏 {snap_view['lost']} 筆")

        sitting = payload.get("sitting") if isinstance(payload.get("sitting"), dict) else {}
        self.draw_cop(label, cx, cy, reference)
        self.draw_sensors(values)
        self.draw_sitting(sitting, snap_view, now)
        self.draw_events(snap_view)
        self.draw_chair(label, cx, cy, reference, sitting, snap_view, now)
        self.root.after(100, self._tick)

    def _sitting_seconds(self, sitting: dict, snap: Optional[dict], now: float) -> float:
        seconds = as_float(sitting.get("seconds"), 0.0)
        # pressure 最慢 5 秒一筆，中間用本機時間補上，計時才會平順；斷線時停在最後收到的值
        if sitting.get("active") and snap and snap["pressure_time"] and snap["live"]:
            seconds += now - snap["pressure_time"]
        return seconds

    # ── 繪圖 ──
    def draw_cop(self, label, center_x, center_y, reference):
        c = self.cop_canvas
        c.delete("all")
        x0, y0, w, h = 34, 34, 452, 360
        c.create_rectangle(x0, y0, x0 + w, y0 + h, outline="black", width=2)
        cx, cy = x0 + w / 2, y0 + h / 2
        c.create_line(cx, y0, cx, y0 + h, fill="black")
        c.create_line(x0, cy, x0 + w, cy, fill="black")
        nx, ny, radius = reference
        px = clamp(cx + (center_x - nx) * w, x0, x0 + w)
        py = clamp(cy + (center_y - ny) * h, y0, y0 + h)
        for color, scale in (("#7ad676", 1.0), ("#ffd966", 2.0), ("#ff8d5c", 3.0)):
            rx, ry = radius * scale * w, radius * scale * h
            c.create_oval(cx - rx, cy - ry, cx + rx, cy + ry, outline=color, width=2 if scale == 1.0 else 1, dash=(6, 5))
        if label == "no_occupancy":
            fill, text = "#bdbdbd", "未入座"
        elif label == "normal":
            fill, text = "#2ecc71", "正常"
        else:
            fill, text = "#e74c3c", zh_label(label)
        if label != "no_occupancy":
            c.create_oval(px - 9, py - 9, px + 9, py + 9, fill=fill, outline="black", width=2)
        c.create_text(cx, y0 + 10, text=f"重心：{text}", font=fz(17, True), anchor="n")
        c.create_text(cx, y0 - 4, text="後（椅背）", anchor="s", font=fz(15))
        c.create_text(cx, y0 + h + 4, text="前", anchor="n", font=fz(15))
        c.create_text(x0 - 8, cy, text="左", anchor="e", font=fz(15))
        c.create_text(x0 + w + 8, cy, text="右", anchor="w", font=fz(15))
        c.scale("all", 0, 0, UI_SCALE, UI_SCALE)

    def draw_sensors(self, values: Dict[int, float]):
        c = self.sensor_canvas
        c.delete("all")
        c.create_text(220, 4, text="感測器壓力", font=fz(17, True), anchor="n")
        c.create_text(166, 52, text="坐墊", font=fz(14), fill="#555")
        c.create_text(375, 52, text="椅背", font=fz(14), fill="#555")
        x0, base, bar_w, gap = 14, 395, 26, 12
        for i in range(1, 12):
            value = values.get(i, 0.0)
            hgt = 300 * value / 100.0
            x = x0 + (i - 1) * (bar_w + gap)
            color = f"#{int(40 + value * 1.4):02x}{int(100 + value * 1.1):02x}{int(180 + value * 0.7):02x}"
            c.create_rectangle(x, base - hgt, x + bar_w, base, fill=color, outline="black")
            c.create_text(x + bar_w / 2, base - hgt - 2, text=str(int(value)), font=fe(13), anchor="s")
            c.create_text(x + bar_w / 2, base + 16, text=f"S{i}", font=fe(12))
        c.create_line(x0 + 8 * (bar_w + gap) - gap / 2, 64, x0 + 8 * (bar_w + gap) - gap / 2, base, fill="#999", dash=(3, 3))
        c.scale("all", 0, 0, UI_SCALE, UI_SCALE)

    def _bar_color(self, seconds: float, limit_s: float, alert: bool) -> Tuple[int, int, int]:
        if alert:
            return 255, 0, 0
        t = clamp(seconds / limit_s, 0.0, 1.0) if limit_s > 0 else 0.0
        # 韌體送 r+g=255 的漸變；螢幕上改用色相漸變（綠→黃→紅），看起來才跟實際燈條一樣鮮豔
        r, g, b = colorsys.hsv_to_rgb((1 - t) * 120 / 360, 0.95, 1.0)
        return int(r * 255), int(g * 255), int(b * 255)

    def draw_sitting(self, sitting: dict, snap: Optional[dict], now: float):
        c = self.sit_canvas
        c.delete("all")
        limit_min = snap["limit_min"] if snap else DEFAULT_SITTING_LIMIT_MIN
        limit_s = limit_min * 60
        active = bool(sitting.get("active"))
        alert = bool(sitting.get("alert"))
        seconds = self._sitting_seconds(sitting, snap, now) if active else 0.0
        c.create_text(12, 8, text="久坐計時", font=fz(17, True), anchor="nw")
        c.create_text(456, 10, text=f"上限 {int(limit_min)} 分鐘", font=fz(15), anchor="ne", fill="#555")
        x0, y0, w, h = 12, 46, 446, 36
        c.create_rectangle(x0, y0, x0 + w, y0 + h, outline="#888", fill="#eee")
        if active:
            frac = 1.0 if alert else clamp(seconds / limit_s, 0, 1)
            r, g, b = self._bar_color(seconds, limit_s, alert)
            c.create_rectangle(x0, y0, x0 + w * frac, y0 + h, outline="", fill=f"#{r:02x}{g:02x}{b:02x}")
        c.create_text(x0 + w / 2, y0 + h / 2, text=f"{fmt_mmss(seconds)} / {fmt_mmss(limit_s)}", font=fe(18, True))
        if snap and not snap["live"]:
            msg, color = "連線中斷（停在最後資料）", "#d35400"
        elif alert:
            msg, color = "該起來動一動了！", "#c0392b"
        elif active:
            msg, color = "計時中（短暫起身不中斷）", "#333"
        else:
            msg, color = "未入座", "#777"
        c.create_text(12, 98, text=msg, font=fz(16), anchor="nw", fill=color)
        c.scale("all", 0, 0, UI_SCALE, UI_SCALE)

    def draw_events(self, snap: Optional[dict]):
        key = snap["events_key"] if snap else None
        if key == self.shown_events_key:
            return
        self.shown_events_key = key
        self.event_list.delete(0, "end")
        if not snap:
            return
        for when, text in snap["events"]:
            self.event_list.insert("end", f"{time.strftime('%H:%M:%S', time.localtime(when))}  {text}")

    def _led_frames(self, label, center_x, center_y, reference, sitting, snap, now) -> Tuple[List[str], List[str]]:
        # 與韌體 ledUpdate() 相同：顏色 = 久坐進度，亮度 = 重心偏移（20%~80%）
        off = LED_OFF_HEX
        on = label != "no_occupancy" and snap is not None and snap["pressure_time"] > 0 and snap["live"]
        nx, ny, radius = reference
        tl = tf = 0.0
        if on:
            full = radius * LED_LEAN_FULL_RADII
            tl = clamp(-(center_x - nx) / (full * LATERAL_RADIUS_SCALE), -1, 1)
            oy = center_y - ny
            oy /= BACKWARD_RADIUS_SCALE if oy < 0 else FORWARD_RADIUS_SCALE   # 與韌體相同
            tf = clamp(oy / full, -1, 1)
        self.led_lean_left += (tl - self.led_lean_left) * LED_SMOOTH_ALPHA
        self.led_lean_front += (tf - self.led_lean_front) * LED_SMOOTH_ALPHA
        if not on:
            return [off] * LEDS_PER_STRIP, [off] * LEDS_PER_STRIP

        alert = bool(sitting.get("alert"))
        if alert:
            blinking = now - snap["blink_start"] < LED_ALERT_BLINK_S
            lit = (not blinking) or int(now * 2) % 2 == 0
            base = (255, 0, 0) if lit else None
        else:
            base = self._bar_color(self._sitting_seconds(sitting, snap, now), snap["limit_min"] * 60, False)

        frames = []
        for side_sign in (1, -1):  # 左扶手、右扶手
            frame = []
            for pos in self.led_pos:
                s = clamp(side_sign * self.led_lean_left + self.led_lean_front * pos, -1, 1)
                pct = LED_BASE_PCT + s * (LED_MAX_PCT - LED_BASE_PCT if s >= 0 else LED_BASE_PCT - LED_MIN_PCT)
                if base is None:
                    frame.append(off)
                else:
                    # 與韌體相同用 gamma 2 換算實際輸出，再以「80% = 全亮」顯示在螢幕上
                    k = (pct / 100) ** 2 / (LED_MAX_PCT / 100) ** 2
                    r, g, b = (int(o + (v - o) * k) for v, o in zip(base, LED_OFF_RGB))
                    frame.append(f"#{r:02x}{g:02x}{b:02x}")
            frames.append(frame)
        return frames[0], frames[1]

    @staticmethod
    def _u_path_points(x_out, x_in, y_back, y_front, n) -> List[Tuple[float, float]]:
        # 燈條包覆扶手：外側由後往前 → 繞過前端 → 內側由前往後；中段 = 扶手前端
        segs = [((x_out, y_back), (x_out, y_front)), ((x_out, y_front), (x_in, y_front)), ((x_in, y_front), (x_in, y_back))]
        lengths = [abs(b[0] - a[0]) + abs(b[1] - a[1]) for a, b in segs]
        total = sum(lengths)
        points = []
        for i in range(n):
            d = total * i / (n - 1)
            for (a, b), length in zip(segs, lengths):
                if d <= length or (a, b) == segs[-1]:
                    t = d / length if length else 0
                    points.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
                    break
                d -= length
        return points

    def draw_chair(self, label, center_x, center_y, reference, sitting, snap, now):
        c = self.chair_canvas
        c.delete("all")
        width = max(c.winfo_width() / UI_SCALE, 1000)
        mid = width / 2
        ink, line = "#222", "#8a9099"
        c.create_text(18, 14, text="椅子俯視圖（上方：椅背）", fill=ink, font=fz(18, True), anchor="nw")

        back_y0, back_y1 = 58, 96
        seat_x0, seat_x1, seat_y0, seat_y1 = mid - 200, mid + 200, 110, 318
        arm_w, arm_gap = 70, 44
        left_arm = (seat_x0 - arm_gap - arm_w, seat_x0 - arm_gap)
        right_arm = (seat_x1 + arm_gap, seat_x1 + arm_gap + arm_w)
        arm_y0, arm_y1 = 124, 300

        c.create_rectangle(seat_x0 - 20, back_y0, seat_x1 + 20, back_y1, fill="#e6e9ed", outline=line, width=2)
        c.create_text(mid, (back_y0 + back_y1) / 2, text="椅背", fill=ink, font=fz(16))
        c.create_rectangle(seat_x0, seat_y0, seat_x1, seat_y1, fill="#f3f5f7", outline=line, width=2)
        c.create_text(mid, (seat_y0 + seat_y1) / 2, text=zh_label(label), fill=ink, font=fz(26, True))
        for ax0, ax1 in (left_arm, right_arm):
            c.create_rectangle(ax0, arm_y0, ax1, arm_y1, fill="#e6e9ed", outline=line, width=2)
        c.create_text((left_arm[0] + left_arm[1]) / 2, arm_y1 + 36, text="左扶手", fill=ink, font=fz(16))
        c.create_text((right_arm[0] + right_arm[1]) / 2, arm_y1 + 36, text="右扶手", fill=ink, font=fz(16))

        # LED 燈條（中段＝扶手前端、兩端＝扶手後端）
        left_frame, right_frame = self._led_frames(label, center_x, center_y, reference, sitting, snap, now)
        pad = 11
        left_pts = self._u_path_points(left_arm[0] - pad, left_arm[1] + pad, arm_y0 + 6, arm_y1 + pad, LEDS_PER_STRIP)
        right_pts = self._u_path_points(right_arm[1] + pad, right_arm[0] - pad, arm_y0 + 6, arm_y1 + pad, LEDS_PER_STRIP)
        for pts, frame in ((left_pts, left_frame), (right_pts, right_frame)):
            for (x, y), color in zip(pts, frame):
                c.create_oval(x - 7, y - 7, x + 7, y + 7, fill=color, outline="#b5bac1")

        # 馬達：M1 右扶手、M2 右靠背、M3 左靠背、M4 左扶手
        motor_xy = {
            1: ((right_arm[0] + right_arm[1]) / 2, (arm_y0 + arm_y1) / 2),
            2: (mid + 130, (back_y0 + back_y1) / 2),
            3: (mid - 130, (back_y0 + back_y1) / 2),
            4: ((left_arm[0] + left_arm[1]) / 2, (arm_y0 + arm_y1) / 2),
        }
        motor_last = snap["motor_last"] if snap else {}
        for mid_id, (x, y) in motor_xy.items():
            active = now - motor_last.get(mid_id, 0.0) < MOTOR_HOLD_S
            r = 25 if active else 21
            c.create_oval(x - r, y - r, x + r, y + r, fill="#ffcc00" if active else "#cfd3d8",
                          outline="#ff6600" if active else "#6f757d", width=3 if active else 2)
            c.create_text(x, y, text=f"M{mid_id}", font=fe(14, True), fill=ink)

        legend = "燈色：久坐時間\n亮度：重心偏向\n黃色馬達：震動中"
        c.create_text(width - 20, 16, text=legend, fill="#333", font=fz(16), anchor="ne", justify="left")

        if snap and not snap["live"]:
            c.create_rectangle(mid - 140, 160, mid + 140, 230, fill="#fdecea", outline="#c0392b", width=3)
            c.create_text(mid, 195, text="連線中斷", fill="#c0392b", font=fz(24, True))
        c.scale("all", 0, 0, UI_SCALE, UI_SCALE)

if __name__ == "__main__":
    root = tk.Tk()
    app = ChairPoseDemo(root)

    def on_close():
        app.monitor.disconnect()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()
