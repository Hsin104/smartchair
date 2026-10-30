"""
馬達震動指令發布層（依蕭芷萱 Agent Quickstart 規格）。

Topic:
    chair/vibration/01/cmd — 發布指令
    chair/vibration/01/ack — 訂閱韌體回覆（見 mqtt_subscriber.py 的 on_message）

參數限制（韌體端會自動夾限，這裡先做一次防呆，避免夾限行為造成誤解）：
    motor_id: 1~4 | intensity: 0~100 | duration_ms: 50~5000 | stagger_ms: 0~500

硬體限制（組員回報）：多顆馬達不可在同一毫秒同時啟動（瞬間電流/機構限制），
故啟動需靠 stagger_ms 錯開；但停止沒有這個限制，可以同時停（見 build_stop_command）。
"""
import json
import logging
import ssl
import uuid

import paho.mqtt.publish as mqtt_publish
from django.conf import settings

logger = logging.getLogger(__name__)

MOTOR_CMD_TOPIC = 'chair/vibration/01/cmd'

# 我方 "M1".."M4" 字串 ↔ 韌體 1~4 整數 id
MOTOR_ID_MAP = {'M1': 1, 'M2': 2, 'M3': 3, 'M4': 4}

DEFAULT_INTENSITY   = 70
DEFAULT_DURATION_MS = 800
DEFAULT_STAGGER_MS  = 100


def _clamp(value, lo, hi):
    return max(lo, min(hi, value))


def build_motor_command(motors, intensity=DEFAULT_INTENSITY,
                         duration_ms=DEFAULT_DURATION_MS,
                         stagger_ms=DEFAULT_STAGGER_MS, cmd_id=None):
    """把我方 ['M1','M2'] 轉成韌體要的單顆／多顆指令 JSON。"""
    cmd_id      = cmd_id or f'cmd-{uuid.uuid4().hex[:8]}'
    intensity   = _clamp(intensity, 0, 100)
    duration_ms = _clamp(duration_ms, 50, 5000)
    stagger_ms  = _clamp(stagger_ms, 0, 500)

    motor_ids = [MOTOR_ID_MAP[m] for m in motors if m in MOTOR_ID_MAP]

    if len(motor_ids) == 1:
        return {
            'cmd_id':      cmd_id,
            'motor_id':    motor_ids[0],
            'intensity':   intensity,
            'duration_ms': duration_ms,
            'stagger_ms':  stagger_ms,
        }

    return {
        'cmd_id':     cmd_id,
        'stagger_ms': stagger_ms,
        'motors': [
            {'id': mid, 'intensity': intensity, 'duration_ms': duration_ms}
            for mid in motor_ids
        ],
    }


def build_stop_command(cmd_id=None):
    return {'cmd_id': cmd_id or f'cmd-{uuid.uuid4().hex[:8]}', 'stop_all': True}


def publish_json(topic, payload, retain=False):
    """
    發布一則 JSON 訊息到 MQTT（馬達指令、椅子設定共用的連線邏輯）。

    retain=True 時 broker 會保留這則訊息，椅子重開機重新訂閱時會立刻收到最後一則（用於椅子設定）。
    失敗（broker 未連線、硬體未部署等）不拋例外，回傳 False 並記錄警告，
    避免硬體離線時把 API 的正常回應一併打斷。
    """
    auth = None
    if getattr(settings, 'MQTT_USERNAME', ''):
        auth = {'username': settings.MQTT_USERNAME, 'password': settings.MQTT_PASSWORD}

    tls = None
    if getattr(settings, 'MQTT_USE_TLS', False):
        tls = {'cert_reqs': ssl.CERT_REQUIRED, 'tls_version': ssl.PROTOCOL_TLS_CLIENT}

    try:
        mqtt_publish.single(
            topic,
            payload=json.dumps(payload, ensure_ascii=False),
            qos=1,
            retain=retain,
            hostname=settings.MQTT_HOST,
            port=settings.MQTT_PORT,
            auth=auth,
            tls=tls,
            client_id=f'django-publisher-{uuid.uuid4().hex[:6]}',
        )
        logger.info(f'[MQTT] 已發布 → {topic}: {payload}')
        return True
    except Exception as e:
        logger.warning(f'[MQTT] 發布失敗（{topic}，硬體可能未連線）：{e}')
        return False


def publish_motor_command(motors, intensity=DEFAULT_INTENSITY,
                           duration_ms=DEFAULT_DURATION_MS,
                           stagger_ms=DEFAULT_STAGGER_MS, topic=MOTOR_CMD_TOPIC):
    """
    發布馬達震動指令。topic 預設為舊韌體的 chair/vibration/01/cmd；
    多張椅子時傳入 api.chairs.motor_topic(device_id)，只送到使用者坐的那張椅子。
    失敗時回傳 None（見 publish_json）。
    """
    if not motors:
        return None
    payload = build_motor_command(motors, intensity, duration_ms, stagger_ms)
    return payload if publish_json(topic, payload) else None
