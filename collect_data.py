"""
真實感測資料採集工具（校準模型用）

流程：
  1. 坐正 → 記錄基準值（baseline）
  2. 依序擺出每種坐姿，腳本自動收 MQTT 資料並存入資料庫
  3. 採集完後執行 python train_model_dl.py --calibrated 重新訓練

執行方式：
    python collect_data.py
"""

import os
import sys
import json
import ssl
import time
import threading
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smartchair_backend.settings')
django.setup()

import paho.mqtt.client as mqtt
from django.conf import settings
from django.contrib.auth import get_user_model
from api.models import PostureRecord

User = get_user_model()

# ── MQTT 設定（與 mqtt_subscriber 相同）─────────────────────────────────────
MQTT_HOST     = getattr(settings, 'MQTT_HOST',     'localhost')
MQTT_PORT     = getattr(settings, 'MQTT_PORT',     1883)
MQTT_USERNAME = getattr(settings, 'MQTT_USERNAME', '')
MQTT_PASSWORD = getattr(settings, 'MQTT_PASSWORD', '')
MQTT_USE_TLS  = getattr(settings, 'MQTT_USE_TLS',  False)

TOPIC = 'chair/pressure/01'

POSTURE_LABELS = {
    '1': ('normal',  '標準坐姿'),
    '2': ('left',    '身體左傾'),
    '3': ('right',   '身體右傾'),
    '4': ('forward', '頭部前傾（烏龜頸）'),
    '5': ('recline', '過度後仰'),
}

SAMPLES_PER_POSTURE = 60   # 每種姿勢收幾筆（可調整）
MIN_PRESSURE        = 30   # 低於此值視為空椅，略過


def _parse_norm(payload: dict):
    norm = payload.get('norm', [])
    if len(norm) < 8:
        return None, None
    seat = {
        'right_back':   norm[0],
        'right_mid':    norm[1],
        'right_front':  norm[2],
        'center_back':  norm[3],
        'center_front': norm[4],
        'left_front':   norm[5],
        'left_mid':     norm[6],
        'left_back':    norm[7],
    }
    back = payload.get('back') or {}
    return seat, back


def _compute_delta(seat: dict, back: dict, baseline_seat: dict, baseline_back: dict):
    delta_seat = {k: round(seat.get(k, 0) - baseline_seat.get(k, 0), 2) for k in seat}
    delta_back = {k: round(back.get(k, 0) - baseline_back.get(k, 0), 2) for k in back} if back else {}
    return delta_seat, delta_back


class Collector:
    def __init__(self, user, baseline_seat, baseline_back):
        self.user          = user
        self.baseline_seat = baseline_seat
        self.baseline_back = baseline_back
        self.target_posture = None
        self.collected      = 0
        self.target_count   = SAMPLES_PER_POSTURE
        self._lock          = threading.Lock()
        self._done_event    = threading.Event()

    def start_posture(self, posture_code, count=SAMPLES_PER_POSTURE):
        with self._lock:
            self.target_posture = posture_code
            self.collected      = 0
            self.target_count   = count
            self._done_event.clear()

    def wait_done(self):
        self._done_event.wait()

    def handle_message(self, payload: dict):
        with self._lock:
            if not self.target_posture:
                return

        norm = payload.get('norm', [])
        if sum(abs(v) for v in norm) < MIN_PRESSURE:
            return

        seat, back = _parse_norm(payload)
        if seat is None:
            return

        # 校準模式：存 delta 值
        delta_seat, delta_back = _compute_delta(seat, back,
                                                self.baseline_seat,
                                                self.baseline_back)

        with self._lock:
            posture = self.target_posture
            self.collected += 1
            count = self.collected
            total = self.target_count

        PostureRecord.objects.create(
            user=self.user,
            posture=posture,
            seat_pressure_data=delta_seat,
            back_pressure_data=delta_back,
            source='real',
        )
        print(f'  [{count}/{total}] 已儲存 {posture}', end='\r')

        if count >= total:
            self._done_event.set()


def collect_baseline(collector_ref: list, client):
    """收 5 筆基準值取平均作為 baseline。"""
    print('\n>>> 第一步：基準校準')
    print('    請坐正，保持標準坐姿，準備好後按 Enter...')
    input()

    seat_samples = []
    back_samples = []
    done = threading.Event()

    def _handler(payload):
        norm = payload.get('norm', [])
        if sum(abs(v) for v in norm) < MIN_PRESSURE:
            return
        seat, back = _parse_norm(payload)
        if seat and len(seat_samples) < 5:
            seat_samples.append(seat)
            if back:
                back_samples.append(back)
            print(f'  基準採集 {len(seat_samples)}/5', end='\r')
        if len(seat_samples) >= 5:
            done.set()

    client._baseline_handler = _handler
    print('  正在採集基準值（5 筆）...')
    done.wait(timeout=60)
    client._baseline_handler = None

    if len(seat_samples) < 3:
        print('\n[Error] 採集失敗，請確認 MQTT 有資料傳入')
        sys.exit(1)

    # 取平均
    keys = list(seat_samples[0].keys())
    baseline_seat = {k: round(sum(s.get(k, 0) for s in seat_samples) / len(seat_samples), 2) for k in keys}

    baseline_back = {}
    if back_samples:
        back_keys = list(back_samples[0].keys())
        baseline_back = {k: round(sum(b.get(k, 0) for b in back_samples) / len(back_samples), 2) for k in back_keys}
    else:
        print('  [警告] 未收到椅背感測器資料，baseline_back 留空（採集到的椅背 delta 將為 0）')

    print(f'\n  基準採集完成：seat={baseline_seat}')
    print(f'                 back={baseline_back}')
    return baseline_seat, baseline_back


def main():
    print('=' * 55)
    print('  智慧辦公椅 真實資料採集工具')
    print('=' * 55)

    # 選擇使用者
    username = input('\n請輸入你的帳號（直接 Enter 使用 dpz）: ').strip() or 'dpz'
    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        print(f'[Error] 找不到帳號 {username}，請先在後端註冊')
        sys.exit(1)
    print(f'  使用者：{user.username}')

    # 建立 MQTT client
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    if MQTT_USERNAME:
        client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    if MQTT_USE_TLS:
        client.tls_set(cert_reqs=ssl.CERT_REQUIRED, tls_version=ssl.PROTOCOL_TLS_CLIENT)

    collector_holder = [None]

    def on_connect(c, ud, flags, rc, props=None):
        if rc == 0:
            c.subscribe(TOPIC)
            print(f'[MQTT] 已連線並訂閱 {TOPIC}')
        else:
            print(f'[MQTT] 連線失敗 rc={rc}')

    def on_message(c, ud, msg):
        try:
            payload = json.loads(msg.payload.decode('utf-8'))
        except Exception:
            return
        # 基準採集
        if hasattr(c, '_baseline_handler') and c._baseline_handler:
            c._baseline_handler(payload)
            return
        # 正式採集
        if collector_holder[0]:
            collector_holder[0].handle_message(payload)

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.loop_start()

    time.sleep(2)  # 等待連線

    # 基準採集
    baseline_seat, baseline_back = collect_baseline(collector_holder, client)

    # 建立採集器
    collector = Collector(user, baseline_seat, baseline_back)
    collector_holder[0] = collector

    # 依序採集每種姿勢
    print(f'\n>>> 第二步：各姿勢採集（每種 {SAMPLES_PER_POSTURE} 筆）')
    print('    坐好後按 Enter 開始，系統會自動計數\n')

    for key, (code, label) in POSTURE_LABELS.items():
        print(f'  [{key}] 準備採集「{label}」')
        print(f'       請擺好姿勢，準備好後按 Enter...')
        input()

        collector.start_posture(code)
        print(f'  開始採集「{label}」，請保持姿勢...')
        collector.wait_done()
        print(f'\n  ✓ 「{label}」完成（{SAMPLES_PER_POSTURE} 筆）')
        time.sleep(1)

    client.loop_stop()
    client.disconnect()

    # 統計
    total = PostureRecord.objects.filter(user=user).count()
    print('\n' + '=' * 55)
    print('  採集完成！')
    for code, label in POSTURE_LABELS.values():
        n = PostureRecord.objects.filter(user=user, posture=code).count()
        print(f'  {label:20s}：{n} 筆')
    print(f'  資料庫總計：{total} 筆')
    print('=' * 55)
    print('\n下一步：')
    print('  python train_model_dl.py --calibrated')


if __name__ == '__main__':
    main()
