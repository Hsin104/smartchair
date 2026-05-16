"""
MQTT 訂閱服務

支援 EMQX Cloud（TLS + 帳密）與本機 Broker（無加密）。
連線參數由 settings.py 讀取，credentials 統一存放在 .env，不進版本控制。

執行方式：
    python manage.py mqtt_subscriber

訂閱的 Topic：
    chair/pressure/01          — 壓力感測數值（EMQX Cloud，組員裝置）
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

from api.models import PostureRecord, ChairSession
from api.views import predict_posture

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

# 所有訂閱 Topic
TOPICS = [
    'chair/pressure/01',
    'smartchair/sensor/seat',
    'smartchair/sensor/back',
    'smartchair/result/posture',
]

# 暫存緩衝區：{ username: { 'seat': ..., 'back': ... } }
_sensor_buffer = {}


def _get_buffer(username):
    if username not in _sensor_buffer:
        _sensor_buffer[username] = {}
    return _sensor_buffer[username]


def _parse_esp32_payload(payload: dict):
    """
    將 ESP32 的 norm 陣列（8個值）轉換為後端需要的 seat_pressure_data 格式。
    感測器順序 S1~S8：left_back, left_mid, left_front,
                      center_back, center_front,
                      right_back, right_mid, right_front
    """
    norm = payload.get('norm', [])
    if len(norm) >= 8:
        seat_data = {
            'left_back':    norm[0],
            'left_mid':     norm[1],
            'left_front':   norm[2],
            'center_back':  norm[3],
            'center_front': norm[4],
            'right_back':   norm[5],
            'right_mid':    norm[6],
            'right_front':  norm[7],
        }
    else:
        seat_data = payload.get('seat') or {}
    back_data = payload.get('back') or {}
    return seat_data, back_data


def _handle_pressure_01(payload: dict):
    """
    處理 chair/pressure/01 的訊息，自動預測坐姿後寫入資料庫。

    支援 ESP32 格式：{"device_id":"chair_01","ts":123,"raw":[...],"norm":[...]}
    使用者需先呼叫 POST /api/chair/checkin 登記為目前座椅使用者。
    """
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

    seat_data, back_data = _parse_esp32_payload(payload)
    posture = predict_posture(seat_data, back_data) or payload.get('posture', 'normal')

    PostureRecord.objects.create(
        user=user,
        posture=posture,
        seat_pressure_data=seat_data,
        back_pressure_data=back_data,
    )
    print(f'[MQTT] 寫入資料庫 — {user.username}: {posture}')


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

    # ── chair/pressure/01（EMQX Cloud，組員裝置）───────────────────────────
    if topic == 'chair/pressure/01':
        _handle_pressure_01(payload)
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
