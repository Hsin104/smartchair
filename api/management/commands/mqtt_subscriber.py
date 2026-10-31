"""
MQTT 訂閱服務

支援 EMQX Cloud（TLS + 帳密）與本機 Broker（無加密）。
連線參數由 settings.py 讀取，credentials 統一存放在 .env，不進版本控制。

執行方式：
    python manage.py mqtt_subscriber

訂閱的 Topic：
    chair/pressure/01          — 壓力感測數值（EMQX Cloud，組員裝置）
    chair/vibration/01/ack     — 馬達指令執行回覆（對應 mqtt_publisher.py 發布的指令）
    smartchair/sensor/seat     — 椅墊 8 個 FSR 數值（本機測試用）
    smartchair/sensor/back     — 椅背 3 個 FSR 數值（本機測試用）
    smartchair/result/posture  — 坐姿辨識結果（含 username）
"""

import json
from datetime import timedelta
import logging
import ssl
import tempfile
import threading
import time
from pathlib import Path

import paho.mqtt.client as mqtt
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from django.db import close_old_connections
from django.utils import timezone

from api.models import ChairSession, PostureRecord, Notification
from api.calibration import handle_device_event, user_calibration
from api.chairs import (
    ACK_TOPIC_PATTERN, LEGACY_PRESSURE_TOPIC, LEGACY_STATUS_TOPIC, PRESSURE_TOPIC_PATTERN, STATUS_TOPIC_PATTERN,
    active_session, auto_checkout, chair_for_device, device_id_from_status_topic, device_id_from_topic,
)
from api.views import predict_posture, _check_sedentary
from api.physio_agent import POSTURE_DISPLAY
from api.sensor_adapter import parse_esp32_payload, total_pressure, device_posture

logger = logging.getLogger(__name__)
User = get_user_model()

# ── 連線設定（從 settings.py / .env 讀取）───────────────────────────────────

MQTT_HOST     = getattr(settings, 'MQTT_HOST',     'localhost')
MQTT_PORT     = getattr(settings, 'MQTT_PORT',     1883)
MQTT_USERNAME = getattr(settings, 'MQTT_USERNAME', '')
MQTT_PASSWORD = getattr(settings, 'MQTT_PASSWORD', '')
MQTT_USE_TLS  = getattr(settings, 'MQTT_USE_TLS',  False)

# 預設使用者（chair/pressure/01 的訊息不帶 username 時使用）
DEFAULT_USERNAME = 'user01'

# 有人坐著的最低總壓力門檻（norm 8 個感測器絕對值總和）
# 椅子空置時 norm 幾乎全 0，此門檻過濾掉空椅訊號
MIN_SEAT_PRESSURE = 30

# 坐姿判斷防手震：連續幾筆讀值一致，才承認「真的變成這個坐姿」。
# ESP32 約 0.5 秒送一次資料，單筆分類結果常因雜訊在 right/normal/left 之間
# 跳一下又跳回去，邊緣觸發若不做防手震，這種單筆雜訊也會誤觸發一次震動。
STABLE_READINGS = 10

# 所有訂閱 Topic
TOPICS = [
    PRESSURE_TOPIC_PATTERN,      # chair/+/pressure：每張椅子各自的感測資料（新韌體）
    ACK_TOPIC_PATTERN,           # chair/+/vibration/ack
    STATUS_TOPIC_PATTERN,        # chair/+/vibration/status：校正結果、設定套用回報
    LEGACY_STATUS_TOPIC,
    'chair/pressure/01',         # 舊韌體（device_id 固定 chair_01）
    'chair/vibration/01/ack',
    'smartchair/sensor/seat',
    'smartchair/sensor/back',
    'smartchair/result/posture',
]

# 心跳檔案：供 Docker HEALTHCHECK 判斷服務是否「真的還活著」，而不只是「process 沒 crash」。
# on_connect／on_disconnect／on_message 都會更新，healthcheck.py 讀取判斷連線狀態與新鮮度。
_HEARTBEAT_PATH = Path(tempfile.gettempdir()) / 'mqtt_heartbeat.json'


def _write_heartbeat(connected: bool):
    try:
        _HEARTBEAT_PATH.write_text(json.dumps({'connected': connected, 'ts': time.time()}))
    except OSError:
        pass  # 心跳檔案寫入失敗不該讓訂閱服務掛掉，純粹監控用途


# 暫存緩衝區：{ username: { 'seat': ..., 'back': ... } }
_sensor_buffer = {}

# 每張椅子上一次的空椅狀態：{ device_id: True=有人 / False=無人 }（沒有 key＝初始）
_last_occupied = {}

# 每張椅子從什麼時候開始連續沒人坐：{ device_id: datetime }，用於自動離座（設計 4-2）
_empty_since = {}

# 坐姿防手震狀態：{ 'device_id:username': {'candidate': 候選坐姿, 'count': 連續次數, 'confirmed': 上次確認的坐姿} }
# 以「椅子＋使用者」為單位，多張椅子各自計數，不會互相干擾
_posture_state = {}


def _get_buffer(username):
    if username not in _sensor_buffer:
        _sensor_buffer[username] = {}
    return _sensor_buffer[username]


def _handle_pressure_01(payload: dict):
    """舊 topic chair/pressure/01 的進入點（舊韌體與整合測試使用），device_id 取自 payload，預設 chair_01。"""
    _handle_pressure(device_id_from_topic(LEGACY_PRESSURE_TOPIC, payload), payload)


def _handle_pressure(device_id: str, payload: dict):
    """
    處理一張椅子的感測資料（chair/{device_id}/pressure 或舊的 chair/pressure/01），預測坐姿後寫入資料庫。

    支援 ESP32 格式：{"device_id":"chair_01","ts":123,"norm":[...],"pose":{...}}
    資料寫進「這張椅子」目前入座的使用者名下（POST /api/chair/checkin 帶 device_id 登記）。
    """
    chair = chair_for_device(device_id)
    session = active_session(chair)

    # 椅子空置檢查：norm/raw 總壓力過低則寫入 empty（每張椅子各自判斷，僅在狀態轉換時寫一次）
    pressure = total_pressure(payload)
    if pressure < MIN_SEAT_PRESSURE:
        # 連續沒人坐超過 AUTO_CHECKOUT_SECONDS → 自動離座（新韌體沒人坐時每 30 秒同步一次，仍會收到訊息）
        empty_since = _empty_since.setdefault(device_id, timezone.now())
        if session and (timezone.now() - empty_since).total_seconds() >= settings.AUTO_CHECKOUT_SECONDS:
            auto_checkout(session)
            print(f'[MQTT] {device_id} 連續無人 → 自動離座：{session.user.username}')
            session = None
        if _last_occupied.get(device_id) is not False:
            _last_occupied[device_id] = False
            if session:
                PostureRecord.objects.create(
                    user=session.user,
                    posture='empty',
                    seat_pressure_data={},
                    back_pressure_data={},
                    source='auto',
                    device_posture=device_posture(payload),
                    chair=chair,
                )
                print(f'[MQTT] {device_id} 無人坐著 → 寫入 empty：{session.user.username}')
            else:
                print(f'[MQTT] {device_id} 無人坐著（總壓力 {pressure} < {MIN_SEAT_PRESSURE}），無人入座')
        return

    _last_occupied[device_id] = True
    _empty_since.pop(device_id, None)

    if session:
        user = session.user
        print(f'[MQTT] {device_id} → 入座使用者：{user.username}')
    else:
        username = payload.get('username', DEFAULT_USERNAME)
        user, created = User.objects.get_or_create(username=username)
        if created:
            user.set_password('changeme')
            user.save()
            print(f'[MQTT] 自動建立使用者：{username}（密碼：changeme，請盡快修改）')
        print(f'[MQTT] 無 active session，使用 fallback：{user.username}')

    seat_data, back_data = parse_esp32_payload(payload)

    # 個人校正記在使用者身上（換椅子也通用），有校正過就用 AI 模型的校準模式
    calibration = user_calibration(user)
    baseline_seat = calibration.baseline_seat if calibration else None
    baseline_back = calibration.baseline_back if calibration else None
    mode_label = '校準' if baseline_seat else '未校準'

    predicted, confidence = predict_posture(
        seat_data,
        back_pressure_data=back_data,
        baseline_seat=baseline_seat,
        baseline_back=baseline_back,
    )
    predicted = predicted or payload.get('posture', 'normal')
    posture = _check_sedentary(user, predicted)
    # sedentary 是依坐著時長覆蓋的規則判斷，不是這次 softmax 機率對應的類別，信心分數不適用
    if posture != predicted:
        confidence = None

    PostureRecord.objects.create(
        user=user,
        posture=posture,
        seat_pressure_data=seat_data,
        back_pressure_data=back_data,
        source='auto',
        confidence=confidence,
        device_posture=device_posture(payload),
        chair=chair,
    )
    print(f'[MQTT] {device_id} 寫入資料庫 [{mode_label}] — {user.username}: {posture}')

    # 防手震：連續 STABLE_READINGS 筆讀值一致才算「真的變成這個坐姿」，
    # 過濾單筆雜訊（例如持續 normal 中間突然閃一筆 right 又跳回 normal）。
    # 以「這次入座」為單位，重新入座就重新計算，不沿用上一次入座確認過的坐姿。
    state = _posture_state.setdefault(
        f'{device_id}:{session.pk if session else user.username}', {'candidate': None, 'count': 0, 'confirmed': None}
    )
    if posture == state['candidate']:
        state['count'] += 1
    else:
        state['candidate'] = posture
        state['count'] = 1

    just_confirmed = state['count'] >= STABLE_READINGS and state['confirmed'] != posture
    if just_confirmed:
        state['confirmed'] = posture

    # 邊緣觸發：只在坐姿「確認變成」這個壞坐姿的那一刻產生一則通知（給 App），
    # 同一個壞坐姿持續多久都不重複，直到坐姿變回 normal/empty 再變差才會重新觸發。
    # 震動不在這裡發：ESP32 內建自動姿勢提醒（壞坐姿 10 秒後自己震動對應馬達，斷網也能用），
    # 後端若再發一次指令會重複震動。手動測試請用 POST /api/motor/trigger。
    if posture not in ('normal', 'empty') and just_confirmed:
        posture_name = POSTURE_DISPLAY.get(posture, posture)
        Notification.objects.create(user=user, message=f'坐姿提醒：{posture_name}')
        print(f'[MQTT] 產生通知 — {user.username}: {posture_name}')


# ── paho 事件回調 ────────────────────────────────────────────────────────────

def on_connect(client, userdata, flags, reason_code, properties=None):
    if reason_code == 0:
        print(f'[MQTT] 已連線至 {MQTT_HOST}:{MQTT_PORT}')
        for topic in TOPICS:
            client.subscribe(topic)
            print(f'[MQTT] 訂閱：{topic}')
        _write_heartbeat(connected=True)
    else:
        print(f'[MQTT] 連線失敗，代碼：{reason_code}')
        _write_heartbeat(connected=False)


def on_message(client, userdata, msg):
    topic = msg.topic
    raw_bytes = msg.payload

    try:
        payload = json.loads(raw_bytes.decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.warning(f'[MQTT] 非 JSON 訊息（{topic}）: {raw_bytes}')
        return

    print(f'[MQTT] 收到 {topic}: {payload}')   # ← 方便確認組員的資料格式
    _write_heartbeat(connected=True)

    # 單一訊息處理失敗（例如模型維度不合、資料庫瞬斷）不該讓整個訂閱服務掛掉
    # 重開機——那樣等於整批即時資料都收不到，比單筆處理失敗嚴重得多。
    try:
        _dispatch_message(topic, payload)
    except Exception as e:
        logger.error(f'[MQTT] 處理訊息失敗（{topic}）：{e}', exc_info=True)


def _dispatch_message(topic, payload):
    # ── 感測資料：新 chair/{device_id}/pressure 與舊 chair/pressure/01 ─────────
    device_id = device_id_from_topic(topic, payload)
    if device_id:
        _handle_pressure(device_id, payload)
        return

    # ── 椅子系統事件：校正結果、設定套用回報（其餘事件如 posture_reminder 不需處理）──
    status_device = device_id_from_status_topic(topic)
    if status_device:
        handle_device_event(status_device, payload)
        return

    # ── 馬達指令執行回覆：新 chair/{device_id}/vibration/ack 與舊 chair/vibration/01/ack ──
    if topic.startswith('chair/') and topic.endswith('/vibration/ack'):
        print(f'[MQTT] 馬達 ACK（{topic}）— cmd_id={payload.get("cmd_id")} '
              f'status={payload.get("status")} message={payload.get("message")}')
        return

    # ── 原本的本機 Topics ─────────────────────────────────────────────────
    username = payload.get('username')
    if not username:
        logger.warning(f'[MQTT] payload 缺少 username（{topic}），略過')
        return

    buf = _get_buffer(username)

    if topic == 'smartchair/sensor/seat':
        buf['seat'] = payload.get('data')

    elif topic == 'smartchair/sensor/back':
        buf['back'] = payload.get('data')

    elif topic == 'smartchair/result/posture':
        posture = payload.get('posture')
        if not posture:
            logger.warning('[MQTT] posture 欄位缺失，略過')
            return

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            logger.warning(f'[MQTT] 使用者 {username} 不存在，略過')
            return

        PostureRecord.objects.create(
            user=user,
            posture=posture,
            seat_pressure_data=buf.get('seat'),
            back_pressure_data=buf.get('back'),
        )
        print(f'[MQTT] 寫入資料庫 — {username}: {posture}')
        _sensor_buffer.pop(username, None)


def on_log(client, userdata, level, buf):
    # 椅子沒人坐時不會有任何訊息進來，只靠 on_message 更新心跳的話，連線正常但閒置超過
    # 120 秒就會被 healthcheck.py 誤判為不健康。keepalive=60 時 paho 在閒置期間每 60 秒
    # 送一次 PINGREQ，收到 broker 的 PINGRESP 代表網路迴圈還在跑、連線也真的通，用它更新心跳。
    if buf.startswith('Received PINGRESP'):
        _write_heartbeat(connected=True)


def on_disconnect(client, userdata, disconnect_flags, reason_code, properties=None):
    print(f'[MQTT] 連線中斷（代碼：{reason_code}），嘗試重新連線...')
    _write_heartbeat(connected=False)


def offline_sweep(chair_ids=None):
    """
    椅子直接斷電或斷網時不會再送任何訊息，上面「連續沒人坐」的判斷永遠不會執行；
    這裡把最後收到資料已超過 AUTO_CHECKOUT_SECONDS 的椅子視同沒人坐，對上面的使用者自動離座。
    """
    close_old_connections()
    cutoff = timezone.now() - timedelta(seconds=settings.AUTO_CHECKOUT_SECONDS)
    stale = ChairSession.objects.filter(is_active=True, chair__last_seen__lt=cutoff).select_related('chair', 'user')
    if chair_ids is not None:      # 測試時只檢查指定的椅子
        stale = stale.filter(chair_id__in=chair_ids)
    for session in stale:
        auto_checkout(session)
        print(f'[MQTT] {session.chair.device_id} 離線超過 {settings.AUTO_CHECKOUT_SECONDS} 秒 → 自動離座：'
              f'{session.user.username}')


def _offline_sweep_loop(interval_seconds=60):
    while True:
        time.sleep(interval_seconds)
        try:
            offline_sweep()
        except Exception as e:
            logger.error(f'[MQTT] 離線椅子檢查失敗：{e}', exc_info=True)


# ── Django management command ────────────────────────────────────────────────

class Command(BaseCommand):
    help = 'MQTT 訂閱服務：監聽感測器數據並自動寫入資料庫'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS(
            f'啟動 MQTT 訂閱服務（{"TLS" if MQTT_USE_TLS else "無加密"}）...'
        ))

        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

        # 帳密驗證
        if MQTT_USERNAME:
            client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

        # TLS（EMQX Cloud 需要 port 8883）
        if MQTT_USE_TLS:
            client.tls_set(cert_reqs=ssl.CERT_REQUIRED, tls_version=ssl.PROTOCOL_TLS_CLIENT)

        client.on_connect    = on_connect
        client.on_message    = on_message
        client.on_disconnect = on_disconnect
        client.on_log        = on_log
        client.reconnect_delay_set(min_delay=1, max_delay=30)

        threading.Thread(target=_offline_sweep_loop, daemon=True).start()

        try:
            client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
            client.loop_forever()
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING('\n已停止 MQTT 訂閱服務'))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f'連線錯誤：{e}'))
