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
import logging
import ssl

import paho.mqtt.client as mqtt
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from api.models import PostureRecord, ChairSession, Notification, MotorLog
from api.views import predict_posture, _check_sedentary
from api.physio_agent import POSTURE_DISPLAY
from api.sensor_adapter import parse_esp32_payload, total_pressure
from api.mqtt_publisher import publish_motor_command
from api.motor_constants import MOTOR_MAP

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
    'chair/pressure/01',
    'chair/vibration/01/ack',
    'smartchair/sensor/seat',
    'smartchair/sensor/back',
    'smartchair/result/posture',
]

# 暫存緩衝區：{ username: { 'seat': ..., 'back': ... } }
_sensor_buffer = {}

# 上一次空椅狀態（True=有人, False=無人, None=初始）
_last_occupied = None

# 坐姿防手震狀態：{ username: {'candidate': 候選坐姿, 'count': 連續次數, 'confirmed': 上次確認的坐姿} }
_posture_state = {}


def _get_buffer(username):
    if username not in _sensor_buffer:
        _sensor_buffer[username] = {}
    return _sensor_buffer[username]


def _handle_pressure_01(payload: dict):
    """
    處理 chair/pressure/01 的訊息，自動預測坐姿後寫入資料庫。

    支援 ESP32 格式：{"device_id":"chair_01","ts":123,"raw":[...],"norm":[...]}
    使用者需先呼叫 POST /api/chair/checkin 登記為目前座椅使用者。
    """
    global _last_occupied

    # 椅子空置檢查：norm/raw 總壓力過低則寫入 sedentary（僅在狀態轉換時寫一次）
    pressure = total_pressure(payload)
    if pressure < MIN_SEAT_PRESSURE:
        if _last_occupied is not False:
            _last_occupied = False
            session = ChairSession.objects.filter(is_active=True).select_related('user').first()
            if session:
                PostureRecord.objects.create(
                    user=session.user,
                    posture='empty',
                    seat_pressure_data={},
                    back_pressure_data={},
                    source='auto',
                )
                print(f'[MQTT] 無人坐著 → 寫入 empty：{session.user.username}')
            else:
                print(f'[MQTT] 無人坐著（總壓力 {pressure} < {MIN_SEAT_PRESSURE}），無 active session')
        return

    _last_occupied = True

    session = ChairSession.objects.filter(is_active=True).select_related('user').first()
    if session:
        user = session.user
        print(f'[MQTT] 寫入 active session 使用者：{user.username}')
    else:
        username = payload.get('username', DEFAULT_USERNAME)
        user, created = User.objects.get_or_create(username=username)
        if created:
            user.set_password('changeme')
            user.save()
            print(f'[MQTT] 自動建立使用者：{username}（密碼：changeme，請盡快修改）')
        print(f'[MQTT] 無 active session，使用 fallback：{user.username}')

    seat_data, back_data = parse_esp32_payload(payload)

    baseline_seat = session.baseline_seat if (session and session.baseline_seat) else None
    mode_label = '校準' if baseline_seat else '未校準'

    baseline_back = session.baseline_back if (session and session.baseline_back) else None

    posture = predict_posture(
        seat_data,
        back_pressure_data=back_data,
        baseline_seat=baseline_seat,
        baseline_back=baseline_back,
    ) or payload.get('posture', 'normal')
    posture = _check_sedentary(user, posture)

    PostureRecord.objects.create(
        user=user,
        posture=posture,
        seat_pressure_data=seat_data,
        back_pressure_data=back_data,
        source='auto',
    )
    print(f'[MQTT] 寫入資料庫 [{mode_label}] — {user.username}: {posture}')

    # 防手震：連續 STABLE_READINGS 筆讀值一致才算「真的變成這個坐姿」，
    # 過濾單筆雜訊（例如持續 normal 中間突然閃一筆 right 又跳回 normal）。
    state = _posture_state.setdefault(
        user.username, {'candidate': None, 'count': 0, 'confirmed': None}
    )
    if posture == state['candidate']:
        state['count'] += 1
    else:
        state['candidate'] = posture
        state['count'] = 1

    just_confirmed = state['count'] >= STABLE_READINGS and state['confirmed'] != posture
    if just_confirmed:
        state['confirmed'] = posture

    # 邊緣觸發：只在坐姿「確認變成」這個壞坐姿的那一刻提醒＋震動一次，
    # 同一個壞坐姿持續多久都不重複，直到坐姿變回 normal/empty 再變差才會重新觸發。
    if posture not in ('normal', 'empty') and just_confirmed:
        posture_name = POSTURE_DISPLAY.get(posture, posture)
        Notification.objects.create(user=user, message=f'坐姿提醒：{posture_name}')
        print(f'[MQTT] 產生通知 — {user.username}: {posture_name}')

        # 震動馬達：即時偵測管線直接觸發（不經過 Agent，見 mcp_server.py 開頭說明）。
        motors = MOTOR_MAP.get(posture, [])
        if motors:
            MotorLog.objects.create(
                user=user, posture=posture, motors=motors, reason=posture_name,
            )
            publish_motor_command(motors)
            print(f'[MQTT] 觸發馬達 — {user.username}: {motors}')


# ── paho 事件回調 ────────────────────────────────────────────────────────────

def on_connect(client, userdata, flags, reason_code, properties=None):
    if reason_code == 0:
        print(f'[MQTT] 已連線至 {MQTT_HOST}:{MQTT_PORT}')
        for topic in TOPICS:
            client.subscribe(topic)
            print(f'[MQTT] 訂閱：{topic}')
    else:
        print(f'[MQTT] 連線失敗，代碼：{reason_code}')


def on_message(client, userdata, msg):
    topic = msg.topic
    raw_bytes = msg.payload

    try:
        payload = json.loads(raw_bytes.decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.warning(f'[MQTT] 非 JSON 訊息（{topic}）: {raw_bytes}')
        return

    print(f'[MQTT] 收到 {topic}: {payload}')   # ← 方便確認組員的資料格式

    # 單一訊息處理失敗（例如模型維度不合、資料庫瞬斷）不該讓整個訂閱服務掛掉
    # 重開機——那樣等於整批即時資料都收不到，比單筆處理失敗嚴重得多。
    try:
        _dispatch_message(topic, payload)
    except Exception as e:
        logger.error(f'[MQTT] 處理訊息失敗（{topic}）：{e}', exc_info=True)


def _dispatch_message(topic, payload):
    # ── chair/pressure/01（EMQX Cloud，組員裝置）───────────────────────────
    if topic == 'chair/pressure/01':
        _handle_pressure_01(payload)
        return

    # ── chair/vibration/01/ack（馬達指令執行回覆，對應 mqtt_publisher.py）────
    if topic == 'chair/vibration/01/ack':
        print(f'[MQTT] 馬達 ACK — cmd_id={payload.get("cmd_id")} '
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


def on_disconnect(client, userdata, disconnect_flags, reason_code, properties=None):
    print(f'[MQTT] 連線中斷（代碼：{reason_code}），嘗試重新連線...')


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
        client.reconnect_delay_set(min_delay=1, max_delay=30)

        try:
            client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
            client.loop_forever()
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING('\n已停止 MQTT 訂閱服務'))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f'連線錯誤：{e}'))
