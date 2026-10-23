# 功能：重現測試 MQTT 資料流，專門驗證 ACK、STATE、STATUS 等回應是否穩定與延遲是否正常。
# 啟動方式（在專案根目錄執行）： .\.venv\Scripts\python.exe .\感測器配置\receiver\mqtt_repro_test_runner.py
import argparse
import csv
import json
import os
import random
import ssl
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean, median

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
if not MQTT_USER or not MQTT_PASS:
    raise RuntimeError("Missing MQTT_USER / MQTT_PASS in .env. Copy .env.example to .env and fill your values.")

MQTT_TOPIC_CMD = os.getenv("MQTT_TOPIC_CMD", "chair/vibration/01/cmd")
MQTT_TOPIC_ACK = os.getenv("MQTT_TOPIC_ACK", "chair/vibration/01/ack")
MQTT_TOPIC_STATE = os.getenv("MQTT_TOPIC_STATE", "chair/vibration/01/state")
MQTT_TOPIC_STATUS = os.getenv("MQTT_TOPIC_STATUS", "chair/vibration/01/status")

MOTOR_COUNT = 4
INTENSITY_MIN = 0
INTENSITY_MAX = 100
DURATION_MIN_MS = 50
DURATION_MAX_MS = 5000
STAGGER_MIN_MS = 0
STAGGER_MAX_MS = 500


def clamp_int(value: int, min_value: int, max_value: int) -> int:
    if value < min_value:
        return min_value
    if value > max_value:
        return max_value
    return value


def now_cmd_id(prefix: str) -> str:
    return f"{prefix}-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}"


def safe_json_loads(payload_bytes: bytes):
    payload_text = payload_bytes.decode("utf-8", errors="ignore")
    try:
        return json.loads(payload_text)
    except Exception:
        return {"_raw": payload_text}


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    if q <= 0:
        return min(values)
    if q >= 1:
        return max(values)
    ordered = sorted(values)
    pos = q * (len(ordered) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    if lo == hi:
        return float(ordered[lo])
    frac = pos - lo
    return float(ordered[lo] * (1 - frac) + ordered[hi] * frac)


@dataclass
class RunResult:
    run_id: int
    case_type: str
    cmd_id: str
    motor_ids: str
    intensity: int
    duration_ms: int
    stagger_ms: int
    published_at_iso: str
    ack_at_iso: str
    state_at_iso: str
    ack_latency_ms: float
    state_latency_ms: float
    ack_ok: bool
    state_ok: bool
    error: str


class MqttReproRunner:
    def __init__(
        self,
        ack_timeout_sec: float,
        state_timeout_sec: float,
        tls_insecure: bool,
    ):
        self.ack_timeout_sec = ack_timeout_sec
        self.state_timeout_sec = state_timeout_sec

        self.connected_event = threading.Event()
        self._lock = threading.Lock()

        self._current_cmd_id = ""
        self._ack_event = threading.Event()
        self._state_event = threading.Event()
        self._ack_payload = None
        self._state_payload = None
        self._ack_at = 0.0
        self._state_at = 0.0

        callback_api = getattr(mqtt, "CallbackAPIVersion", None)
        if callback_api and hasattr(callback_api, "VERSION2"):
            self.client = mqtt.Client(callback_api_version=callback_api.VERSION2)
        else:
            self.client = mqtt.Client()

        self.client.username_pw_set(MQTT_USER, MQTT_PASS)
        self.client.tls_set(tls_version=ssl.PROTOCOL_TLS_CLIENT)
        self.client.tls_insecure_set(tls_insecure)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        client.subscribe(MQTT_TOPIC_ACK)
        client.subscribe(MQTT_TOPIC_STATE)
        client.subscribe(MQTT_TOPIC_STATUS)
        self.connected_event.set()
        print(f"[MQTT] connected code={reason_code}")

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties=None):
        self.connected_event.clear()
        print(f"[MQTT] disconnected code={reason_code}")

    def _on_message(self, client, userdata, msg):
        payload = safe_json_loads(msg.payload)
        now_perf = time.perf_counter()

        if msg.topic == MQTT_TOPIC_ACK:
            with self._lock:
                cmd_id = ""
                if isinstance(payload, dict):
                    cmd_id = str(payload.get("cmd_id", ""))
                if cmd_id and cmd_id == self._current_cmd_id:
                    self._ack_payload = payload
                    self._ack_at = now_perf
                    self._ack_event.set()
        elif msg.topic == MQTT_TOPIC_STATE:
            with self._lock:
                self._state_payload = payload
                self._state_at = now_perf
                self._state_event.set()

    def connect(self):
        self.client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
        self.client.loop_start()
        if not self.connected_event.wait(timeout=8.0):
            raise RuntimeError("MQTT connect timeout: broker not reachable or credentials invalid.")

    def close(self):
        try:
            self.client.loop_stop()
            self.client.disconnect()
        except Exception:
            pass

    def _prepare_wait_context(self, cmd_id: str):
        with self._lock:
            self._current_cmd_id = cmd_id
            self._ack_payload = None
            self._state_payload = None
            self._ack_at = 0.0
            self._state_at = 0.0
        self._ack_event.clear()
        self._state_event.clear()

    @staticmethod
    def _extract_running_ids(state_payload) -> set[int]:
        if not isinstance(state_payload, dict):
            return set()
        motors = state_payload.get("motors", [])
        if not isinstance(motors, list):
            return set()
        running = set()
        for m in motors:
            if not isinstance(m, dict):
                continue
            if bool(m.get("running", False)):
                try:
                    running.add(int(m.get("id", 0)))
                except Exception:
                    continue
        return running

    def publish_and_measure(self, payload: dict, expected_running_ids: set[int] | None) -> tuple:
        cmd_id = str(payload.get("cmd_id", ""))
        self._prepare_wait_context(cmd_id)

        payload_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        send_at_perf = time.perf_counter()
        send_at_wall = datetime.now().isoformat(timespec="milliseconds")
        self.client.publish(MQTT_TOPIC_CMD, payload_text)

        ack_ok = self._ack_event.wait(timeout=self.ack_timeout_sec)
        ack_latency_ms = 0.0
        ack_at_iso = ""
        if ack_ok:
            with self._lock:
                ack_latency_ms = max(0.0, (self._ack_at - send_at_perf) * 1000.0)
            ack_at_iso = datetime.now().isoformat(timespec="milliseconds")

        state_ok = False
        state_latency_ms = 0.0
        state_at_iso = ""
        state_error = ""

        deadline = send_at_perf + self.state_timeout_sec
        while time.perf_counter() < deadline:
            remain = max(0.01, deadline - time.perf_counter())
            triggered = self._state_event.wait(timeout=min(0.12, remain))
            if not triggered:
                continue
            self._state_event.clear()
            with self._lock:
                state_payload = self._state_payload
                state_at_perf = self._state_at
            running_ids = self._extract_running_ids(state_payload)

            if expected_running_ids is None:
                state_ok = True
            elif len(expected_running_ids) == 0:
                state_ok = len(running_ids) == 0
                if not state_ok:
                    state_error = f"expected all stop, but running={sorted(running_ids)}"
            else:
                state_ok = expected_running_ids.issubset(running_ids)
                if not state_ok:
                    state_error = f"expected running={sorted(expected_running_ids)}, got={sorted(running_ids)}"

            if state_ok:
                state_latency_ms = max(0.0, (state_at_perf - send_at_perf) * 1000.0)
                state_at_iso = datetime.now().isoformat(timespec="milliseconds")
                break

        return send_at_wall, ack_at_iso, state_at_iso, ack_ok, state_ok, ack_latency_ms, state_latency_ms, state_error


def build_single_payload(motor_id: int, intensity: int, duration_ms: int, stagger_ms: int) -> dict:
    return {
        "cmd_id": now_cmd_id("single"),
        "motor_id": clamp_int(motor_id, 1, MOTOR_COUNT),
        "intensity": clamp_int(intensity, INTENSITY_MIN, INTENSITY_MAX),
        "duration_ms": clamp_int(duration_ms, DURATION_MIN_MS, DURATION_MAX_MS),
        "stagger_ms": clamp_int(stagger_ms, STAGGER_MIN_MS, STAGGER_MAX_MS),
    }


def build_multi_payload(motors: list[dict], stagger_ms: int) -> dict:
    normalized = []
    for m in motors:
        normalized.append(
            {
                "id": clamp_int(int(m.get("id", 1)), 1, MOTOR_COUNT),
                "intensity": clamp_int(int(m.get("intensity", 0)), INTENSITY_MIN, INTENSITY_MAX),
                "duration_ms": clamp_int(int(m.get("duration_ms", DURATION_MIN_MS)), DURATION_MIN_MS, DURATION_MAX_MS),
            }
        )
    return {
        "cmd_id": now_cmd_id("multi"),
        "motors": normalized,
        "stagger_ms": clamp_int(stagger_ms, STAGGER_MIN_MS, STAGGER_MAX_MS),
    }


def build_stop_payload() -> dict:
    return {
        "cmd_id": now_cmd_id("stop"),
        "stop_all": True,
    }


def run_clamp_checks(iterations: int) -> list[RunResult]:
    results: list[RunResult] = []
    random.seed(42)
    for i in range(1, iterations + 1):
        motor_id_raw = random.choice([-3, -1, 0, 1, 2, 3, 4, 5, 8])
        intensity_raw = random.choice([-30, -1, 0, 35, 60, 100, 130, 999])
        duration_raw = random.choice([-300, 10, 49, 50, 400, 1000, 5000, 9000])
        stagger_raw = random.choice([-90, 0, 20, 200, 500, 900])

        payload = build_single_payload(motor_id_raw, intensity_raw, duration_raw, stagger_raw)
        ok = (
            1 <= payload["motor_id"] <= MOTOR_COUNT
            and INTENSITY_MIN <= payload["intensity"] <= INTENSITY_MAX
            and DURATION_MIN_MS <= payload["duration_ms"] <= DURATION_MAX_MS
            and STAGGER_MIN_MS <= payload["stagger_ms"] <= STAGGER_MAX_MS
        )
        results.append(
            RunResult(
                run_id=i,
                case_type="clamp_local",
                cmd_id=payload["cmd_id"],
                motor_ids=str(payload["motor_id"]),
                intensity=payload["intensity"],
                duration_ms=payload["duration_ms"],
                stagger_ms=payload["stagger_ms"],
                published_at_iso=datetime.now().isoformat(timespec="milliseconds"),
                ack_at_iso="",
                state_at_iso="",
                ack_latency_ms=0.0,
                state_latency_ms=0.0,
                ack_ok=ok,
                state_ok=ok,
                error="" if ok else "clamp result out of expected bounds",
            )
        )
    return results


def run_mqtt_control_suite(
    runner: MqttReproRunner,
    iterations: int,
    per_case_sleep_sec: float,
    pacing_mode: str,
    settle_factor: float,
    settle_min_sec: float,
    settle_max_sec: float,
    ack_retries: int,
    retry_backoff_sec: float,
    timeout_cooldown_sec: float,
) -> list[RunResult]:
    random.seed(42)
    results: list[RunResult] = []

    def compute_delay(case_type: str, duration_ms: int, stagger_ms: int, motor_count: int) -> float:
        base = max(0.0, per_case_sleep_sec)
        if pacing_mode == "fixed":
            return base
        if case_type == "stop_all":
            dynamic = 0.25
        else:
            active_ms = max(0, duration_ms) + max(0, motor_count - 1) * max(0, stagger_ms)
            dynamic = (active_ms / 1000.0) * max(0.0, settle_factor)
        dynamic = min(max(settle_min_sec, dynamic), settle_max_sec)
        return max(base, dynamic)

    for i in range(1, iterations + 1):
        pattern = i % 10
        if pattern in (1, 2, 3, 4, 5, 6):
            motor_id = ((i - 1) % MOTOR_COUNT) + 1
            intensity = random.choice([30, 45, 60, 75, 90])
            duration = random.choice([200, 350, 500, 900, 1200])
            stagger = random.choice([0, 20, 50])
            payload = build_single_payload(motor_id, intensity, duration, stagger)
            expected_running = {motor_id}
            case_type = "single_control"
            motor_ids = str(motor_id)
            rec_intensity = payload["intensity"]
            rec_duration = payload["duration_ms"]
            rec_stagger = payload["stagger_ms"]
            case_motor_count = 1
        elif pattern in (7, 8):
            m1 = ((i - 1) % MOTOR_COUNT) + 1
            m2 = (m1 % MOTOR_COUNT) + 1
            intensity = random.choice([45, 60, 80])
            duration = random.choice([500, 800, 1100])
            stagger = random.choice([30, 50, 80, 120])
            payload = build_multi_payload(
                [
                    {"id": m1, "intensity": intensity, "duration_ms": duration},
                    {"id": m2, "intensity": intensity, "duration_ms": duration},
                ],
                stagger_ms=stagger,
            )
            expected_running = {m1, m2}
            case_type = "multi_stagger"
            motor_ids = f"{m1},{m2}"
            rec_intensity = intensity
            rec_duration = duration
            rec_stagger = stagger
            case_motor_count = 2
        else:
            payload = build_stop_payload()
            expected_running = set()
            case_type = "stop_all"
            motor_ids = "-"
            rec_intensity = 0
            rec_duration = 0
            rec_stagger = 0
            case_motor_count = 0

        try:
            attempts = max(1, ack_retries + 1)
            send_iso = datetime.now().isoformat(timespec="milliseconds")
            ack_iso = ""
            state_iso = ""
            ack_ok = False
            state_ok = False
            ack_latency_ms = 0.0
            state_latency_ms = 0.0
            state_error = ""
            error_text = ""

            for attempt_idx in range(attempts):
                (
                    send_iso,
                    ack_iso,
                    state_iso,
                    ack_ok,
                    state_ok,
                    ack_latency_ms,
                    state_latency_ms,
                    state_error,
                ) = runner.publish_and_measure(payload, expected_running)

                if ack_ok and state_ok:
                    error_text = ""
                    break

                if not ack_ok:
                    error_text = f"ack timeout (attempt {attempt_idx + 1}/{attempts})"
                else:
                    error_text = (
                        f"state mismatch: {state_error} (attempt {attempt_idx + 1}/{attempts})"
                        if state_error
                        else f"state timeout (attempt {attempt_idx + 1}/{attempts})"
                    )

                if attempt_idx < attempts - 1:
                    time.sleep(max(0.0, retry_backoff_sec * (attempt_idx + 1)))

            error_text = ""
            if not ack_ok:
                error_text = "ack timeout"
            elif not state_ok:
                error_text = f"state mismatch: {state_error}" if state_error else "state timeout"
        except Exception as exc:
            send_iso = datetime.now().isoformat(timespec="milliseconds")
            ack_iso = ""
            state_iso = ""
            ack_ok = False
            state_ok = False
            ack_latency_ms = 0.0
            state_latency_ms = 0.0
            error_text = str(exc)

        results.append(
            RunResult(
                run_id=i,
                case_type=case_type,
                cmd_id=str(payload.get("cmd_id", "")),
                motor_ids=motor_ids,
                intensity=rec_intensity,
                duration_ms=rec_duration,
                stagger_ms=rec_stagger,
                published_at_iso=send_iso,
                ack_at_iso=ack_iso,
                state_at_iso=state_iso,
                ack_latency_ms=ack_latency_ms,
                state_latency_ms=state_latency_ms,
                ack_ok=ack_ok,
                state_ok=state_ok,
                error=error_text,
            )
        )

        if not ack_ok:
            time.sleep(max(0.0, timeout_cooldown_sec))
        else:
            time.sleep(compute_delay(case_type, rec_duration, rec_stagger, case_motor_count))
    return results


def summarize_results(results: list[RunResult]) -> dict:
    ack_rows = [r for r in results if r.case_type != "clamp_local"]
    clamp_rows = [r for r in results if r.case_type == "clamp_local"]

    ack_total = len(ack_rows)
    ack_success = sum(1 for r in ack_rows if r.ack_ok)
    state_success = sum(1 for r in ack_rows if r.state_ok)

    ack_lat_values = [r.ack_latency_ms for r in ack_rows if r.ack_ok and r.ack_latency_ms > 0]
    state_lat_values = [r.state_latency_ms for r in ack_rows if r.state_ok and r.state_latency_ms > 0]

    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "ack_total": ack_total,
        "ack_success": ack_success,
        "ack_success_rate_pct": (ack_success / ack_total * 100.0) if ack_total else 0.0,
        "state_success": state_success,
        "state_success_rate_pct": (state_success / ack_total * 100.0) if ack_total else 0.0,
        "ack_latency_avg_ms": mean(ack_lat_values) if ack_lat_values else 0.0,
        "ack_latency_p95_ms": percentile(ack_lat_values, 0.95) if ack_lat_values else 0.0,
        "ack_latency_median_ms": median(ack_lat_values) if ack_lat_values else 0.0,
        "state_latency_avg_ms": mean(state_lat_values) if state_lat_values else 0.0,
        "state_latency_p95_ms": percentile(state_lat_values, 0.95) if state_lat_values else 0.0,
        "state_latency_median_ms": median(state_lat_values) if state_lat_values else 0.0,
        "clamp_total": len(clamp_rows),
        "clamp_success": sum(1 for r in clamp_rows if r.ack_ok and r.state_ok),
        "clamp_success_rate_pct": (
            sum(1 for r in clamp_rows if r.ack_ok and r.state_ok) / len(clamp_rows) * 100.0
        ) if clamp_rows else 0.0,
    }
    return summary


def write_results(output_dir: Path, run_label: str, results: list[RunResult], summary: dict):
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = output_dir / f"{run_label}_{stamp}_runs.csv"
    json_path = output_dir / f"{run_label}_{stamp}_summary.json"

    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "run_id",
                "case_type",
                "cmd_id",
                "motor_ids",
                "intensity",
                "duration_ms",
                "stagger_ms",
                "published_at",
                "ack_at",
                "state_at",
                "ack_latency_ms",
                "state_latency_ms",
                "ack_ok",
                "state_ok",
                "error",
            ]
        )
        for r in results:
            writer.writerow(
                [
                    r.run_id,
                    r.case_type,
                    r.cmd_id,
                    r.motor_ids,
                    r.intensity,
                    r.duration_ms,
                    r.stagger_ms,
                    r.published_at_iso,
                    r.ack_at_iso,
                    r.state_at_iso,
                    f"{r.ack_latency_ms:.3f}",
                    f"{r.state_latency_ms:.3f}",
                    "1" if r.ack_ok else "0",
                    "1" if r.state_ok else "0",
                    r.error,
                ]
            )

    with json_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    return csv_path, json_path


def print_summary(summary: dict):
    print("\n=== 測試摘要 ===")
    print(f"ACK 成功率          : {summary['ack_success']}/{summary['ack_total']} ({summary['ack_success_rate_pct']:.2f}%)")
    print(f"STATE 成功率        : {summary['state_success']}/{summary['ack_total']} ({summary['state_success_rate_pct']:.2f}%)")
    print(
        "ACK 延遲 (ms)       : "
        f"avg={summary['ack_latency_avg_ms']:.2f}, "
        f"median={summary['ack_latency_median_ms']:.2f}, "
        f"p95={summary['ack_latency_p95_ms']:.2f}"
    )
    print(
        "STATE 延遲 (ms)     : "
        f"avg={summary['state_latency_avg_ms']:.2f}, "
        f"median={summary['state_latency_median_ms']:.2f}, "
        f"p95={summary['state_latency_p95_ms']:.2f}"
    )
    print(
        "夾限測試成功率      : "
        f"{summary['clamp_success']}/{summary['clamp_total']} ({summary['clamp_success_rate_pct']:.2f}%)"
    )


def parse_args():
    parser = argparse.ArgumentParser(
        description="智慧椅可重現性測試：自動執行 MQTT 控制測試並輸出論文可用 CSV/JSON"
    )
    parser.add_argument("--iterations", type=int, default=120, help="MQTT 控制測試次數（預設 120）")
    parser.add_argument("--clamp-iterations", type=int, default=30, help="參數夾限測試次數（預設 30）")
    parser.add_argument("--ack-timeout-sec", type=float, default=3.0, help="等待 ACK 秒數（預設 3.0）")
    parser.add_argument("--state-timeout-sec", type=float, default=1.2, help="等待 STATE 秒數（預設 1.2）")
    parser.add_argument("--per-case-sleep-sec", type=float, default=0.20, help="每筆測試最小間隔秒數（預設 0.20）")
    parser.add_argument(
        "--pacing-mode",
        choices=["realistic", "fixed"],
        default="realistic",
        help="節奏模式：realistic 依命令持續時間動態調整，fixed 固定間隔（預設 realistic）",
    )
    parser.add_argument(
        "--settle-factor",
        type=float,
        default=0.45,
        help="realistic 模式下，命令活動時間乘數（預設 0.45）",
    )
    parser.add_argument("--settle-min-sec", type=float, default=0.18, help="realistic 模式最小停頓秒數（預設 0.18）")
    parser.add_argument("--settle-max-sec", type=float, default=1.50, help="realistic 模式最大停頓秒數（預設 1.50）")
    parser.add_argument("--ack-retries", type=int, default=1, help="ACK timeout 時重試次數（預設 1，代表最多送 2 次）")
    parser.add_argument("--retry-backoff-sec", type=float, default=0.40, help="重試退避秒數（預設 0.40）")
    parser.add_argument("--timeout-cooldown-sec", type=float, default=1.20, help="遇到 timeout 後額外冷卻秒數（預設 1.20）")
    parser.add_argument("--output-dir", default="test_outputs", help="輸出目錄（預設 receiver/test_outputs）")
    parser.add_argument("--run-label", default="repro", help="輸出檔名標籤")
    parser.add_argument("--clamp-only", action="store_true", help="只跑參數夾限測試，不連 MQTT")
    parser.add_argument(
        "--tls-insecure",
        action="store_true",
        help="跳過 TLS 憑證驗證（與現有測試工具一致，僅建議開發/研究環境使用）",
    )
    return parser.parse_args()


def main():
    reconfigure_stdout = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure_stdout):
        reconfigure_stdout(encoding="utf-8", errors="replace")

    args = parse_args()
    base_dir = Path(__file__).resolve().parent
    output_dir = (base_dir / args.output_dir).resolve()

    all_results: list[RunResult] = []
    if args.clamp_iterations > 0:
        all_results.extend(run_clamp_checks(args.clamp_iterations))

    runner = None
    if not args.clamp_only:
        runner = MqttReproRunner(
            ack_timeout_sec=args.ack_timeout_sec,
            state_timeout_sec=args.state_timeout_sec,
            tls_insecure=args.tls_insecure,
        )
        try:
            print("[INFO] connecting MQTT...")
            runner.connect()
            print("[INFO] running MQTT control suite...")
            all_results.extend(
                run_mqtt_control_suite(
                    runner=runner,
                    iterations=max(1, args.iterations),
                    per_case_sleep_sec=args.per_case_sleep_sec,
                    pacing_mode=args.pacing_mode,
                    settle_factor=args.settle_factor,
                    settle_min_sec=args.settle_min_sec,
                    settle_max_sec=args.settle_max_sec,
                    ack_retries=max(0, args.ack_retries),
                    retry_backoff_sec=args.retry_backoff_sec,
                    timeout_cooldown_sec=args.timeout_cooldown_sec,
                )
            )
        finally:
            runner.close()

    summary = summarize_results(all_results)
    csv_path, json_path = write_results(output_dir, args.run_label, all_results, summary)
    print_summary(summary)
    print("\n=== 輸出檔案 ===")
    print(csv_path)
    print(json_path)


if __name__ == "__main__":
    main()
