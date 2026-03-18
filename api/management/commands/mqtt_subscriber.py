"""
MQTT 訂閱服務

執行方式：
    python manage.py mqtt_subscriber

訂閱的 Topic：
    smartchair/sensor/fsr    — FSR 壓力感測數值
    smartchair/sensor/tof    — ToF 距離感測數值
    smartchair/sensor/imu    — IMU 姿態角數值
    smartchair/result/posture — 坐姿辨識結果（含 username）
"""

import json
import logging

import paho.mqtt.client as mqtt
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from api.models import PostureRecord

logger = logging.getLogger(__name__)
User = get_user_model()

# MQTT Broker 連線設定
MQTT_HOST = getattr(settings, 'MQTT_HOST', 'localhost')
MQTT_PORT = getattr(settings, 'MQTT_PORT', 1883)

# 訂閱的 Topic 清單
TOPICS = [
    'smartchair/sensor/fsr',
    'smartchair/sensor/tof',
    'smartchair/sensor/imu',
    'smartchair/result/posture',
]

# 暫存感測器數值，等 posture 結果到了再一起寫入資料庫
# 結構：{ username: { 'fsr': ..., 'tof': ..., 'imu': ... } }
_sensor_buffer = {}


def _get_buffer(username):
    if username not in _sensor_buffer:
        _sensor_buffer[username] = {}
    return _sensor_buffer[username]


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
    try:
        payload = json.loads(msg.payload.decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.warning(f'[MQTT] 無法解析訊息：{msg.payload}')
        return

    print(f'[MQTT] 收到 {topic}: {payload}')

    # 取得 username（payload 必須帶 username 欄位）
    username = payload.get('username')
    if not username:
        logger.warning(f'[MQTT] payload 缺少 username，略過')
        return

    buf = _get_buffer(username)

    if topic == 'smartchair/sensor/fsr':
        buf['fsr'] = payload.get('data')

    elif topic == 'smartchair/sensor/tof':
        buf['tof'] = payload.get('data')

    elif topic == 'smartchair/sensor/imu':
        buf['imu'] = payload.get('data')

    elif topic == 'smartchair/result/posture':
        # 坐姿結果到了，寫入資料庫
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
            fsr_data=buf.get('fsr'),
            tof_data=buf.get('tof'),
            imu_data=buf.get('imu'),
        )
        print(f'[MQTT] 已寫入資料庫 — {username}: {posture}')

        # 清除該使用者的暫存
        _sensor_buffer.pop(username, None)


def on_disconnect(client, userdata, disconnect_flags, reason_code, properties=None):
    print(f'[MQTT] 連線中斷（代碼：{reason_code}），嘗試重新連線...')


class Command(BaseCommand):
    help = 'MQTT 訂閱服務：監聽感測器數據並自動寫入資料庫'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('啟動 MQTT 訂閱服務...'))

        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        client.on_connect = on_connect
        client.on_message = on_message
        client.on_disconnect = on_disconnect

        # 連線失敗時自動重試
        client.reconnect_delay_set(min_delay=1, max_delay=30)

        try:
            client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
            client.loop_forever()
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING('\n已停止 MQTT 訂閱服務'))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f'連線錯誤：{e}'))
