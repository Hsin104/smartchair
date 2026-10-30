"""
個人坐姿校正、預設中立點與椅子設定（設計見 demo/calibration_design.md）。

校正（使用者只需做一次，記在使用者身上，換椅子也通用）：
    App  POST /chair/calibration → start_calibration()：送 calibrate 指令給椅子（不保留）
    椅子 取樣 5 秒，回報 calibrated／calibration_failed → handle_device_event()
    App  GET /chair/calibration → refresh_request()：椅子 10 秒內沒回應時，改用後端收到的資料計算（備案）

中立點（椅子判斷坐姿、自動震動用）以 retained 訊息送到 chair/{device_id}/config，椅子重開機會自動收到。
沒校正的人依序使用：這張椅子的預設值 → 全部椅子的平均 → 幾何中心（resolve_neutral）。
預設值由後端保管、每週重新計算（update_default_neutrals），調整時不用重燒韌體。
"""

import logging
import math
from datetime import timedelta

from django.utils import timezone

from .models import CalibrationRequest, Chair, ChairSession, PostureRecord, SystemSetting, UserCalibration
from .mqtt_publisher import publish_json
from .sensor_adapter import BACK_INDEX, SEAT_INDEX

logger = logging.getLogger(__name__)

# 椅墊 8 顆感測器座標（x：0 左～1 右；y：0 後～1 前），與 ESP32 韌體相同（demo/MQTT資料說明.md 第 3 節）
SEAT_POSITIONS = {
    'right_back':   (0.82, 0.18),  # S1
    'right_mid':    (0.82, 0.42),  # S2
    'right_front':  (0.82, 0.72),  # S3
    'center_back':  (0.50, 0.18),  # S4
    'center_front': (0.50, 0.72),  # S5
    'left_front':   (0.18, 0.72),  # S6
    'left_mid':     (0.18, 0.42),  # S7
    'left_back':    (0.18, 0.18),  # S8
}
BACK_KEYS = ['spine_upper', 'spine_mid', 'spine_lower']

# 幾何中心：8 顆感測器座標平均，也是韌體內建的最後備案
GEOMETRIC_NEUTRAL = (
    round(sum(p[0] for p in SEAT_POSITIONS.values()) / len(SEAT_POSITIONS), 4),
    round(sum(p[1] for p in SEAT_POSITIONS.values()) / len(SEAT_POSITIONS), 4),
)
NORMAL_RADIUS = 0.07

CALIBRATION_DURATION_SECONDS = 5     # 椅子取樣秒數（設計 2-2）
DEVICE_TIMEOUT_SECONDS = 10          # 等椅子回報，逾時改後端計算（設計 2-3）
STABILITY_LIMIT = NORMAL_RADIUS / 2  # 重心偏移超過綠環半徑一半＝坐不穩（設計 2-4）
FALLBACK_WINDOW_SECONDS = 20         # 後端備案取最近幾秒的資料
DEFAULT_MIN_SAMPLES = 200            # 椅子累積幾筆正常坐姿才用自己的預設值（設計 3-7）
FLEET_DEFAULT_KEY = 'default_neutral'

FAIL_MESSAGES = {
    'no_occupancy': '沒有偵測到有人坐著，請坐上椅子後再校正',
    'unstable':     '校正時身體有移動，請坐正、保持不動後再試一次',
    'no_data':      f'最近 {FALLBACK_WINDOW_SECONDS} 秒內沒有收到椅子的資料，請確認椅子已開機連線後再試',
    'not_seated':   '請先入座（check-in）再進行校正',
}


def config_topic(device_id: str) -> str:
    return f'chair/{device_id}/config'


def calibration_cmd_topic(device_id: str) -> str:
    return f'chair/{device_id}/calibration/cmd'


def center_of_pressure(seat: dict):
    """以座墊壓力加權算重心 (x, y)；沒有壓力或含負值（校準 delta 格式）時回傳 None。"""
    values = {k: float(seat.get(k, 0) or 0) for k in SEAT_POSITIONS}
    if any(v < 0 for v in values.values()):
        return None
    total = sum(values.values())
    if total <= 0:
        return None
    x = sum(v * SEAT_POSITIONS[k][0] for k, v in values.items()) / total
    y = sum(v * SEAT_POSITIONS[k][1] for k, v in values.items()) / total
    return round(x, 4), round(y, 4)


def user_calibration(user):
    return UserCalibration.objects.filter(user=user).first()


# ── 中立點：分層決定、送給椅子 ────────────────────────────────────────────────

def resolve_neutral(chair: Chair, user=None):
    """回傳 (neutral_x, neutral_y, source)。source：user／chair／fleet／geometric（設計 3-7）。"""
    calibration = user_calibration(user) if user else None
    if calibration:
        return calibration.neutral_x, calibration.neutral_y, 'user'
    if chair.default_neutral_x is not None and chair.default_samples >= DEFAULT_MIN_SAMPLES:
        return chair.default_neutral_x, chair.default_neutral_y, 'chair'
    fleet = SystemSetting.objects.filter(key=FLEET_DEFAULT_KEY).first()
    if fleet and fleet.value.get('samples', 0) >= DEFAULT_MIN_SAMPLES:
        return fleet.value['neutral_x'], fleet.value['neutral_y'], 'fleet'
    return GEOMETRIC_NEUTRAL[0], GEOMETRIC_NEUTRAL[1], 'geometric'


def push_neutral(chair: Chair, user=None) -> bool:
    """
    把中立點送給椅子（retained）。user 有校正時送個人值（set_neutral），否則送預設值（reset_neutral）。
    設定只含數值，不含帳號名稱（設計 3-3）。
    """
    x, y, source = resolve_neutral(chair, user)
    payload = {
        'cmd': 'set_neutral' if source == 'user' else 'reset_neutral',
        'neutral_x': x, 'neutral_y': y, 'normal_radius': NORMAL_RADIUS, 'source': source,
    }
    return publish_json(config_topic(chair.device_id), payload, retain=True)


# ── 校正流程 ──────────────────────────────────────────────────────────────────

def start_calibration(user, chair: Chair) -> CalibrationRequest:
    """建立校正請求並請椅子開始取樣（指令不保留，避免椅子重開機又自動校正，設計 2-5）。"""
    CalibrationRequest.objects.filter(user=user, status=CalibrationRequest.STATUS_RUNNING).update(
        status=CalibrationRequest.STATUS_FAILED, reason='superseded', finished_at=timezone.now(),
    )
    request = CalibrationRequest.objects.create(user=user, chair=chair)
    publish_json(calibration_cmd_topic(chair.device_id), {
        'cmd': 'calibrate', 'duration_s': CALIBRATION_DURATION_SECONDS, 'request_id': str(request.id),
    })
    return request


def _finish(request, method='', reason=''):
    request.status = CalibrationRequest.STATUS_FAILED if reason else CalibrationRequest.STATUS_DONE
    request.method = method
    request.reason = reason
    request.finished_at = timezone.now()
    request.save(update_fields=['status', 'method', 'reason', 'finished_at'])


def _save_calibration(user, chair, neutral, seat, back, samples, method):
    calibration, _ = UserCalibration.objects.update_or_create(
        user=user,
        defaults={'neutral_x': neutral[0], 'neutral_y': neutral[1], 'baseline_seat': seat,
                  'baseline_back': back, 'samples': samples, 'device_id': chair.device_id, 'method': method},
    )
    # 使用者還坐在這張椅子上才更新椅子的中立點（避免校正途中離座，卻把個人值送給下一位）
    if ChairSession.objects.filter(user=user, chair=chair, is_active=True).exists():
        push_neutral(chair, user)
    return calibration


def handle_device_event(device_id: str, payload: dict):
    """處理椅子在 status topic 回報的校正結果與設定套用回報。"""
    event = payload.get('event')
    if event == 'config_applied':
        logger.info(f'[校正] {device_id} 已套用設定：{payload}')
        return
    if event not in ('calibrated', 'calibration_failed'):
        return

    request = CalibrationRequest.objects.filter(
        id=payload.get('request_id'), status=CalibrationRequest.STATUS_RUNNING,
    ).select_related('user', 'chair').first()
    if request is None:
        logger.warning(f'[校正] {device_id} 回報了不存在或已結束的校正請求：{payload.get("request_id")}')
        return

    if event == 'calibration_failed':
        _finish(request, method=UserCalibration.METHOD_DEVICE, reason=payload.get('reason') or 'unknown')
        return

    norm_avg = payload.get('norm_avg') or []
    seat = {k: norm_avg[i] for k, i in SEAT_INDEX.items()} if len(norm_avg) >= 8 else {}
    back = {k: norm_avg[i] for k, i in BACK_INDEX.items()} if len(norm_avg) >= 11 else None
    neutral = (payload.get('neutral_x'), payload.get('neutral_y'))
    if neutral[0] is None or neutral[1] is None:
        neutral = center_of_pressure(seat) or (None, None)
    if neutral[0] is None or not seat:
        _finish(request, method=UserCalibration.METHOD_DEVICE, reason='invalid_payload')
        return

    _save_calibration(request.user, request.chair, (round(neutral[0], 4), round(neutral[1], 4)),
                      seat, back, payload.get('samples') or 0, UserCalibration.METHOD_DEVICE)
    _finish(request, method=UserCalibration.METHOD_DEVICE)


def calibrate_from_recent(user, chair: Chair):
    """
    後端備案：用這位使用者最近 FALLBACK_WINDOW_SECONDS 秒收到的資料計算校正。
    回傳 (UserCalibration, 失敗原因代碼)；重心偏移超過 STABILITY_LIMIT 視為坐不穩。
    """
    cutoff = timezone.now() - timedelta(seconds=FALLBACK_WINDOW_SECONDS)
    records = [
        r for r in PostureRecord.objects.filter(
            user=user, seat_pressure_data__isnull=False, timestamp__gte=cutoff,
        ).order_by('-timestamp')[:40]
        if r.seat_pressure_data and center_of_pressure(r.seat_pressure_data)
    ]
    if not records:
        return None, 'no_data'

    centers = [center_of_pressure(r.seat_pressure_data) for r in records]
    mean = (sum(c[0] for c in centers) / len(centers), sum(c[1] for c in centers) / len(centers))
    if max(math.dist(c, mean) for c in centers) > STABILITY_LIMIT:
        return None, 'unstable'

    seat = {k: round(sum(r.seat_pressure_data[k] for r in records) / len(records), 2) for k in SEAT_POSITIONS}
    back_records = [r for r in records if r.back_pressure_data]
    back = ({k: round(sum(r.back_pressure_data.get(k, 0) for r in back_records) / len(back_records), 2)
             for k in BACK_KEYS} if back_records else None)
    calibration = _save_calibration(user, chair, center_of_pressure(seat), seat, back, len(records),
                                    UserCalibration.METHOD_BACKEND)
    return calibration, None


def refresh_request(request: CalibrationRequest) -> CalibrationRequest:
    """查詢時檢查是否逾時：椅子 DEVICE_TIMEOUT_SECONDS 秒內沒回應，就改用後端計算（設計 2-3）。"""
    if request.status != CalibrationRequest.STATUS_RUNNING:
        return request
    if (timezone.now() - request.created_at).total_seconds() < DEVICE_TIMEOUT_SECONDS:
        return request
    _, reason = calibrate_from_recent(request.user, request.chair)
    _finish(request, method=UserCalibration.METHOD_BACKEND, reason=reason or '')
    return request


# ── 預設中立點：每週依真實資料重新計算 ───────────────────────────────────────

def update_default_neutrals():
    """
    重新計算每張椅子與全部椅子的預設中立點，並把每張椅子目前該用的中立點重送一次。

    資料：AI 判定為正常坐姿（posture=normal）、且使用者沒有個人校正的紀錄（校正過的人會讓預設值偏向個人）。
    限制：「正常坐姿」是 AI 模型判斷的，不是人工標註。回傳每張椅子的結果摘要。
    """
    calibrated_users = UserCalibration.objects.values_list('user_id', flat=True)
    records = (PostureRecord.objects.filter(posture='normal', seat_pressure_data__isnull=False)
               .exclude(user_id__in=calibrated_users).values_list('chair_id', 'seat_pressure_data'))

    per_chair, all_centers = {}, []
    for chair_id, seat in records.iterator():
        center = center_of_pressure(seat or {})
        if center is None:
            continue
        all_centers.append(center)
        if chair_id:
            per_chair.setdefault(chair_id, []).append(center)

    def mean(centers):
        return (round(sum(c[0] for c in centers) / len(centers), 4),
                round(sum(c[1] for c in centers) / len(centers), 4))

    now = timezone.now()
    summary = {}
    if all_centers:
        fx, fy = mean(all_centers)
        SystemSetting.objects.update_or_create(key=FLEET_DEFAULT_KEY, defaults={'value': {
            'neutral_x': fx, 'neutral_y': fy, 'samples': len(all_centers), 'computed_at': now.isoformat(),
        }})
        summary['fleet'] = {'neutral': (fx, fy), 'samples': len(all_centers)}

    for chair in Chair.objects.all():
        centers = per_chair.get(chair.id, [])
        if centers:
            chair.default_neutral_x, chair.default_neutral_y = mean(centers)
        chair.default_samples = len(centers)
        chair.default_updated_at = now
        chair.save(update_fields=['default_neutral_x', 'default_neutral_y', 'default_samples', 'default_updated_at'])
        summary[chair.device_id] = {'neutral': (chair.default_neutral_x, chair.default_neutral_y),
                                    'samples': len(centers), 'source': resolve_neutral(chair)[2]}

        # 每張椅子都重送一次目前該用的值：坐的人有校正送個人值，其他送新的預設值。
        # 不能只送「沒人坐／沒校正」的椅子：部署前就入座的人從沒收到過個人值，椅子上會完全沒有設定
        session = ChairSession.objects.filter(chair=chair, is_active=True).select_related('user').first()
        push_neutral(chair, session.user if session else None)
    return summary
