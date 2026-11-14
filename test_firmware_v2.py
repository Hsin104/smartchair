"""
椅子韌體 2.0（蕭芷萱回覆 esp32_spec_v2）後端配合項目測試：
    在線（LWT）、久坐改用椅子判斷、中立點重送／退回、以椅子實際震動產生通知、補送事件時間、校正事件。

直接呼叫 mqtt_subscriber 的處理函式（不經過 broker），所有 MQTT 發送都被攔截，不會讓真的椅子收到任何訊息。
    python test_firmware_v2.py
"""
import os
import sys
import time
from datetime import timedelta
from types import SimpleNamespace

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smartchair_backend.settings')
import django  # noqa: E402

django.setup()
sys.stdout.reconfigure(encoding='utf-8')

from django.conf import settings  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402
from django.utils import timezone  # noqa: E402

from api import mqtt_publisher  # noqa: E402
from api.chairs import is_online  # noqa: E402
from api.models import CalibrationRequest, Chair, ChairSession, Notification, PostureRecord, UserCalibration  # noqa: E402
from api.management.commands import mqtt_subscriber as sub  # noqa: E402

_published = []
mqtt_publisher.mqtt_publish = SimpleNamespace(
    single=lambda topic, payload=None, **kwargs: _published.append((topic, payload)))

User = get_user_model()
DEVICE = 'chair_fw2_test'
CONFIG_TOPIC = f'chair/{DEVICE}/config'
results = []

SEAT_NORMAL = [52, 50, 44, 48, 42, 44, 50, 52, 25, 27, 27]
SEAT_FORWARD = [11, 29, 65, 10, 63, 65, 29, 11, 5, 6, 6]


def check(name, ok, detail=''):
    results.append(ok)
    print(f'  [{"PASS" if ok else "FAIL"}] {name}' + (f'  — {detail}' if detail else ''))


def pressure(label, norm=SEAT_NORMAL, alert=False, seq=[0]):
    seq[0] += 1
    return {'device_id': DEVICE, 'ts': int(time.time()), 'seq': seq[0], 'type': 'change', 'norm': norm,
            'pose': {'label': label}, 'sitting': {'active': label != 'no_occupancy', 'seconds': 60,
                                                  'limit_min': 30, 'alert': alert}}


def event(name, **fields):
    return {'device_id': DEVICE, 'ts': int(time.time()), 'event': name, **fields}


def configs():
    return [p for t, p in _published if t == CONFIG_TOPIC]


def notes(user):
    return list(Notification.objects.filter(user=user, kind=Notification.KIND_POSTURE).order_by('timestamp'))


def main():
    user, _ = User.objects.get_or_create(username='fw2_test_user')
    Chair.objects.filter(device_id=DEVICE).delete()
    UserCalibration.objects.filter(user=user).delete()
    Notification.objects.filter(user=user).delete()

    print('\n[1] 在線判斷改用 LWT（chair/{id}/online）')
    sub._dispatch_message(f'chair/{DEVICE}/online', {'device_id': DEVICE, 'online': True, 'fw': '2.0.0'})
    chair = Chair.objects.get(device_id=DEVICE)
    Chair.objects.filter(pk=chair.pk).update(last_seen=timezone.now() - timedelta(minutes=5))
    chair.refresh_from_db()
    check('收到 online=true → 在線，記下韌體版本', chair.online is True and chair.firmware == '2.0.0', chair.firmware)
    check('沒人坐 5 分鐘沒送資料仍算在線（不再用 15 秒判斷）', is_online(chair) is True)
    sub._dispatch_message(f'chair/{DEVICE}/online', {'device_id': DEVICE, 'online': False})
    chair.refresh_from_db()
    changed = chair.online_changed_at
    check('broker 代發 online=false → 離線', chair.online is False and is_online(chair) is False)
    sub._dispatch_message(f'chair/{DEVICE}/online', {'device_id': DEVICE, 'online': False})
    chair.refresh_from_db()
    check('重複收到相同狀態（retained）不更新改變時間', chair.online_changed_at == changed)

    print('\n[2] 離線太久自動離座：以 LWT 離線時間為準')
    over = timedelta(seconds=settings.AUTO_CHECKOUT_SECONDS + 1)
    session = ChairSession.objects.create(user=user, chair=chair)
    Chair.objects.filter(pk=chair.pk).update(online=True, last_seen=timezone.now() - over)
    sub.offline_sweep(chair_ids=[chair.pk])
    session.refresh_from_db()
    check('在線但很久沒資料（沒人坐）→ 不會自動離座', session.is_active is True)
    Chair.objects.filter(pk=chair.pk).update(online=False, online_changed_at=timezone.now() - over)
    sub.offline_sweep(chair_ids=[chair.pk])
    session.refresh_from_db()
    check('離線超過門檻 → 自動離座', session.is_active is False)

    print('\n[3] 久坐改用椅子的 sitting.alert')
    Chair.objects.filter(pk=chair.pk).update(online=True)
    session = ChairSession.objects.create(user=user, chair=chair)
    PostureRecord.objects.filter(user=user).delete()
    sub._handle_pressure(DEVICE, pressure('normal', alert=False))
    first = PostureRecord.objects.filter(user=user).order_by('-timestamp').first()
    sub._handle_pressure(DEVICE, pressure('normal', alert=True))
    second = PostureRecord.objects.filter(user=user).order_by('-timestamp').first()
    check('alert=false → 不是久坐', first.posture != 'sedentary', first.posture)
    check('alert=true → 紀錄為 sedentary', second.posture == 'sedentary', second.posture)

    print('\n[4] 中立點：人坐回來重送個人值、離座／退回時 retained 換成預設值')
    UserCalibration.objects.create(user=user, neutral_x=0.51, neutral_y=0.42, baseline_seat={}, samples=125,
                                   method=UserCalibration.METHOD_DEVICE)
    _published.clear()
    sub._handle_pressure(DEVICE, pressure('no_occupancy', norm=[0] * 11))
    check('站起來（no_occupancy）→ 先不送（椅子 30 秒後自己退回）', configs() == [], str(configs()))
    sub._handle_pressure(DEVICE, pressure('normal'))
    sent = configs()
    check('坐回來 → 重送個人中立點 set_neutral', len(sent) == 1 and '"set_neutral"' in sent[0] and '0.51' in sent[0],
          str(sent))
    sub._handle_pressure(DEVICE, pressure('normal'))
    check('一直坐著不會重複送', len(configs()) == 1)
    _published.clear()
    sub._dispatch_message(f'chair/{DEVICE}/vibration/status', event('neutral_reset'))
    check('neutral_reset → retained 換成 reset_neutral', len(configs()) == 1 and '"reset_neutral"' in configs()[0])
    _published.clear()
    sub._dispatch_message(f'chair/{DEVICE}/vibration/status', event('left_seat', sitting_min=12, sitting_s=720))
    chair.refresh_from_db()
    check('left_seat → retained 換成 reset_neutral、記為沒人坐',
          len(configs()) == 1 and '"reset_neutral"' in configs()[0] and chair.occupied is False)

    print('\n[5] 通知改以椅子實際震動產生')
    Notification.objects.filter(user=user).delete()
    sub._handle_pressure(DEVICE, pressure('normal'))
    for _ in range(sub.STABLE_READINGS + 2):
        sub._handle_pressure(DEVICE, pressure('forward_lean', norm=SEAT_FORWARD))
    check('韌體 2.0：後端模型判斷壞坐姿不再自己產生通知', notes(user) == [], str([n.message for n in notes(user)]))
    status = f'chair/{DEVICE}/vibration/status'
    sub._dispatch_message(status, event('posture_reminder', message='forward_lean', motors=[1, 4], level=1, duration_s=10))
    sub._dispatch_message(status, event('posture_reminder', message='forward_lean', motors=[1, 4], level=2, duration_s=40))
    check('椅子震動 → 1 則坐姿提醒；同一段壞坐姿再震不重複通知',
          len(notes(user)) == 1 and '頭部前傾' in notes(user)[0].message, str([n.message for n in notes(user)]))
    sub._handle_pressure(DEVICE, pressure('normal'))
    sub._dispatch_message(status, event('posture_reminder', message='forward_lean', motors=[1, 4], level=1, duration_s=10))
    check('坐正後又前傾 → 新的一則', len(notes(user)) == 2)
    sub._dispatch_message(status, event('posture_reminder', message='left_lean', motors=[4, 3], level=1, duration_s=10))
    check('換成另一種壞坐姿 → 新的一則', len(notes(user)) == 3 and '左傾' in notes(user)[-1].message)

    Notification.objects.filter(user=user).delete()
    sub._dispatch_message(status, event('sedentary_reminder', sitting_min=30, limit_min=30, motors=[1, 2, 3, 4]))
    sub._dispatch_message(status, event('sedentary_reminder', sitting_min=35, limit_min=30, motors=[1, 2, 3, 4]))
    check('久坐提醒：同一段坐著只通知一次', len(notes(user)) == 1 and '30 分鐘' in notes(user)[0].message,
          str([n.message for n in notes(user)]))
    sub._dispatch_message(status, event('left_seat', sitting_min=36, sitting_s=2160))
    sub._dispatch_message(status, event('sedentary_reminder', sitting_min=30, limit_min=30, motors=[1, 2, 3, 4]))
    check('離座後再坐滿 → 再通知一次', len(notes(user)) == 2)

    print('\n[6] 斷網補送的事件用椅子的 ts')
    Notification.objects.filter(user=user).delete()
    sub._handle_pressure(DEVICE, pressure('normal'))
    old_ts = int(time.time()) - 600
    ChairSession.objects.filter(pk=session.pk).update(started_at=timezone.now() - timedelta(hours=1))
    sub._dispatch_message(status, {'device_id': DEVICE, 'ts': old_ts, 'event': 'posture_reminder',
                                   'message': 'backward_lean', 'motors': [2, 3]})
    n = notes(user)[-1]
    check('補送事件 → 通知時間是 10 分鐘前', abs((timezone.now() - n.timestamp).total_seconds() - 600) < 5,
          str(n.timestamp))
    sub._handle_pressure(DEVICE, pressure('normal'))
    sub._dispatch_message(status, {'device_id': DEVICE, 'ts': 1234, 'time_synced': False, 'event': 'posture_reminder',
                                   'message': 'right_lean', 'motors': [1, 2]})
    n = notes(user)[-1]
    check('椅子沒對時（time_synced=false）→ 用收到的時間', (timezone.now() - n.timestamp).total_seconds() < 5)

    print('\n[7] 校正事件：開始、穩定比例、設定被拒絕、硬體報告')
    req = CalibrationRequest.objects.create(user=user, chair=chair)
    sub._dispatch_message(status, event('calibration_started', request_id=str(req.id), duration_s=5))
    req.refresh_from_db()
    check('calibration_started 不影響狀態', req.status == CalibrationRequest.STATUS_RUNNING)
    sub._dispatch_message(status, event('calibrated', request_id=str(req.id), neutral_x=0.5012, neutral_y=0.4266,
                                        norm_avg=SEAT_NORMAL, samples=125, stable_pct=98))
    req.refresh_from_db()
    check('calibrated → 完成並記下 stable_pct', req.status == 'done' and req.stable_pct == 98, str(req.stable_pct))
    req = CalibrationRequest.objects.create(user=user, chair=chair)
    sub._dispatch_message(status, event('calibration_failed', request_id=str(req.id), reason='unstable', stable_pct=81))
    req.refresh_from_db()
    check('calibration_failed → 失敗並記下 stable_pct', req.reason == 'unstable' and req.stable_pct == 81)
    sub._dispatch_message(status, event('config_rejected', reason='out_of_range'))
    check('config_rejected 只記 log、不出錯', True)
    Chair.objects.filter(pk=chair.pk).update(firmware='')
    sub._dispatch_message(status, event('hardware_report', fw='2.0.1', sitting_limit_min=30, sample_hz=25))
    chair.refresh_from_db()
    check('hardware_report → 更新韌體版本', chair.firmware == '2.0.1', chair.firmware)

    # 收尾
    Chair.objects.filter(device_id=DEVICE).delete()
    PostureRecord.objects.filter(user=user).delete()
    user.delete()
    print(f'\n=== 結果：{sum(results)}/{len(results)} 項通過 ===')


if __name__ == '__main__':
    main()
