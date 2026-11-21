"""
多張椅子：MQTT topic 與椅子的對應、找出椅子上的使用者。

Topic 規劃（韌體 2.0，demo/esp32_spec_v2.md）：chair/{device_id}/pressure、chair/{device_id}/vibration/cmd …
舊韌體的 chair/pressure/01、chair/vibration/01/…（device_id 固定 chair_01）韌體已不再使用，11/21 移除。
"""

from datetime import datetime, timedelta, timezone as dt_timezone

from django.utils import timezone

from .models import Chair, ChairSession

# paho 訂閱用的萬用字元 topic
PRESSURE_TOPIC_PATTERN = 'chair/+/pressure'
ACK_TOPIC_PATTERN = 'chair/+/vibration/ack'
# 椅子的系統事件（校正結果 calibrated／calibration_failed、設定套用 config_applied 等）
STATUS_TOPIC_PATTERN = 'chair/+/vibration/status'
# 韌體 2.0 的在線狀態（MQTT 遺囑 LWT，retained）：連線時 online=true，斷電斷網約 20～25 秒後 broker 代發 false
ONLINE_TOPIC_PATTERN = 'chair/+/online'


def device_id_from_online_topic(topic: str):
    """chair/{device_id}/online；其他 topic 回傳 None。"""
    parts = topic.split('/')
    if len(parts) == 3 and parts[0] == 'chair' and parts[2] == 'online':
        return parts[1]
    return None


def device_id_from_status_topic(topic: str):
    """chair/{device_id}/vibration/status；其他 topic 回傳 None。"""
    parts = topic.split('/')
    if len(parts) == 4 and parts[0] == 'chair' and parts[2] == 'vibration' and parts[3] == 'status':
        return parts[1]
    return None


def device_id_from_topic(topic: str, payload: dict):
    """回傳這則感測資料（chair/{device_id}/pressure）屬於哪張椅子；不是感測資料 topic 時回傳 None。"""
    parts = topic.split('/')
    if len(parts) == 3 and parts[0] == 'chair' and parts[2] == 'pressure':
        return parts[1]
    return None


def chair_for_device(device_id: str) -> Chair:
    """取得椅子，第一次收到這個 device_id 時自動登記，並更新最後上線時間。"""
    chair, _ = Chair.objects.get_or_create(device_id=device_id)
    Chair.objects.filter(pk=chair.pk).update(last_seen=timezone.now())
    return chair


def active_session(chair: Chair):
    """這張椅子目前坐的人（沒人登記入座時回傳 None）。"""
    return ChairSession.objects.filter(chair=chair, is_active=True).select_related('user').first()


def user_session(user):
    """這位使用者目前坐的椅子（沒有入座時回傳 None）。"""
    return ChairSession.objects.filter(user=user, is_active=True).select_related('chair').first()


def motor_topic(device_id: str) -> str:
    """馬達指令要送到哪個 topic：chair/{device_id}/vibration/cmd。"""
    return f'chair/{device_id}/vibration/cmd'


AUTO_CHECKOUT_MESSAGE = '已自動離座：椅子 {minutes} 分鐘沒有偵測到人，回來後請重新入座'


def auto_checkout(session: ChairSession):
    """
    自動離座（設計 4-2）：結束入座、寫一則 auto_checkout 通知（App 讀到時跳出系統通知與「重新入座」），
    並讓椅子恢復預設中立點，下一位使用者不會沿用前一位的個人校正。
    """
    from django.conf import settings
    from .calibration import push_neutral
    from .models import Notification

    ChairSession.objects.filter(pk=session.pk).update(is_active=False)
    minutes = settings.AUTO_CHECKOUT_SECONDS // 60
    Notification.objects.create(user=session.user, kind=Notification.KIND_AUTO_CHECKOUT,
                                message=AUTO_CHECKOUT_MESSAGE.format(minutes=minutes))
    if session.chair:
        push_neutral(session.chair)


def is_online(chair: Chair, within_seconds: int = 15) -> bool:
    """
    韌體 2.0 以 LWT 回報的在線狀態為準（沒人坐時 30 秒才送一筆資料，不能用最後收到時間判斷）；
    舊韌體沒有 LWT（online 為 null），沿用「within_seconds 秒內收到過資料」。
    """
    if chair.online is not None:
        return chair.online
    return bool(chair.last_seen and (timezone.now() - chair.last_seen).total_seconds() <= within_seconds)


def handle_online(device_id: str, payload: dict) -> Chair:
    """處理 chair/{device_id}/online：記錄在線狀態（狀態有變才更新改變時間）與韌體版本。"""
    chair, _ = Chair.objects.get_or_create(device_id=device_id)
    online = bool(payload.get('online'))
    fields = {}
    if chair.online != online:
        fields.update(online=online, online_changed_at=timezone.now())
    if payload.get('fw') and payload['fw'] != chair.firmware:
        fields['firmware'] = payload['fw']
    if fields:
        Chair.objects.filter(pk=chair.pk).update(**fields)
        for k, v in fields.items():
            setattr(chair, k, v)
    return chair


def update_battery(chair: Chair, payload: dict) -> bool:
    """
    pressure 的 power 欄位（韌體 2.0 只在 sync 筆出現）→ 存最後一次的電量；沒帶 power 時不動。
    回傳有沒有更新。battery_present=False 時電量與電壓沒有意義，存成 null。
    """
    power = payload.get('power')
    if not isinstance(power, dict):
        return False
    present = power.get('battery_present')
    pct, volt = power.get('battery_pct'), power.get('voltage_v')
    fields = {
        'battery_present':    present if isinstance(present, bool) else None,
        'battery_pct':        max(0, min(100, int(pct))) if isinstance(pct, (int, float)) and present is not False else None,
        'battery_voltage':    round(float(volt), 3) if isinstance(volt, (int, float)) and present is not False else None,
        'battery_updated_at': timezone.now(),
    }
    Chair.objects.filter(pk=chair.pk).update(**fields)
    for k, v in fields.items():
        setattr(chair, k, v)
    return True


def battery_json(chair: Chair):
    """椅子狀態 API 回傳的電量；從沒收到過 power 時回傳 None。"""
    if chair.battery_updated_at is None:
        return None
    return {
        'present':    chair.battery_present,
        'percent':    chair.battery_pct,
        'voltage':    chair.battery_voltage,
        'updated_at': timezone.localtime(chair.battery_updated_at).isoformat(),
    }


def event_time(payload: dict):
    """
    椅子訊息的發生時間：斷網期間的事件會在連線後補送，要用椅子的 ts；
    椅子還沒對時（time_synced=false，ts 是開機秒數）或 ts 不合理時，用後端收到的時間。
    """
    now = timezone.now()
    ts = payload.get('ts')
    if payload.get('time_synced') is False or not isinstance(ts, (int, float)) or ts < 1_000_000_000:
        return now
    when = datetime.fromtimestamp(ts, tz=dt_timezone.utc)
    return now if when > now + timedelta(minutes=5) else when


SESSION_CLOCK_TOLERANCE = timedelta(minutes=2)


def session_at(chair: Chair, when):
    """
    when 那時坐在這張椅子上的入座紀錄（補送的舊事件可能屬於前一位使用者）。
    椅子的 ts 只到秒、時鐘也可能跟後端差幾秒，入座後馬上發生的事件會比入座時間早一點，給 2 分鐘寬限。
    """
    return (ChairSession.objects.filter(chair=chair, started_at__lte=when + SESSION_CLOCK_TOLERANCE)
            .select_related('user').order_by('-started_at').first())
