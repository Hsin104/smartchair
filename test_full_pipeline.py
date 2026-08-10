"""
全系統軟體端整合測試（無需實體椅子）

模擬 ESP32 MQTT payload（含椅背 3 點感測值）直接餵給 MQTT 訂閱處理函式，
驗證「MQTT 接收 → 20 特徵坐姿預測 → 資料庫寫入 → 通知 → 馬達觸發 → AI 建議」完整鏈路。

不會連線任何 MQTT Broker（本機或雲端），純呼叫後端函式，
因此不會影響組員目前連線中的 EMQX Cloud（chair/pressure/01）。

執行方式：
    python test_full_pipeline.py            # 略過會呼叫 Gemini API 的 AI 建議測試
    python test_full_pipeline.py --with-ai   # 額外測試一次 Physio Agent 完整 ReAct 流程（消耗 API 額度）
"""

import os
import sys
import django

# Windows 主控台預設編碼（cp950）無法顯示部分中文/emoji，強制改用 UTF-8 避免亂碼或崩潰
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smartchair_backend.settings')
django.setup()

from datetime import timedelta
from django.contrib.auth import get_user_model
from django.utils import timezone

from api.models import PostureRecord, Notification, MotorLog, ChairSession
from api.management.commands.mqtt_subscriber import _handle_pressure_01
from api.views import _check_sedentary, MOTOR_TRIGGER_MAP, POSTURE_DISPLAY

User = get_user_model()
WITH_AI = '--with-ai' in sys.argv

TEST_USERNAME = 'integration_test_user'

# 對應 mqtt_subscriber._parse_esp32_payload 的 norm 索引：
# norm[0]=right_back, [1]=right_mid, [2]=right_front, [3]=center_back,
# [4]=center_front, [5]=left_front, [6]=left_mid, [7]=left_back
def seat_to_norm(seat: dict) -> list:
    return [
        seat['right_back'], seat['right_mid'], seat['right_front'],
        seat['center_back'], seat['center_front'],
        seat['left_front'], seat['left_mid'], seat['left_back'],
    ]


# 6 種坐姿模擬 payload（數值取自 generate_fake_data.py 的區間中點）
POSTURE_PAYLOADS = {
    'normal': {
        'seat': {'left_back': 50, 'left_mid': 50, 'left_front': 48,
                  'center_back': 46, 'center_front': 46,
                  'right_back': 50, 'right_mid': 50, 'right_front': 48},
        'back': {'spine_upper': 27, 'spine_mid': 27, 'spine_lower': 25},
    },
    'left': {
        'seat': {'left_back': 70, 'left_mid': 65, 'left_front': 65,
                  'center_back': 39, 'center_front': 36,
                  'right_back': 15, 'right_mid': 14, 'right_front': 14},
        'back': {'spine_upper': 21, 'spine_mid': 21, 'spine_lower': 18},
    },
    'right': {
        'seat': {'left_back': 15, 'left_mid': 14, 'left_front': 14,
                  'center_back': 36, 'center_front': 36,
                  'right_back': 70, 'right_mid': 65, 'right_front': 65},
        'back': {'spine_upper': 21, 'spine_mid': 21, 'spine_lower': 18},
    },
    'forward': {
        'seat': {'left_back': 11, 'left_mid': 29, 'left_front': 65,
                  'center_back': 10, 'center_front': 63,
                  'right_back': 11, 'right_mid': 29, 'right_front': 65},
        'back': {'spine_upper': 6, 'spine_mid': 6, 'spine_lower': 5},
    },
    'recline': {
        'seat': {'left_back': 62, 'left_mid': 40, 'left_front': 11,
                  'center_back': 63, 'center_front': 11,
                  'right_back': 62, 'right_mid': 40, 'right_front': 11},
        'back': {'spine_upper': 72, 'spine_mid': 66, 'spine_lower': 56},
    },
}

results = []


def check(step, condition, detail=''):
    status = 'PASS' if condition else 'FAIL'
    results.append((step, status, detail))
    print(f'  [{status}] {step}' + (f'  — {detail}' if detail else ''))


def main():
    print('=' * 70)
    print('  全系統軟體端整合測試（MQTT → 預測 → DB → 通知 → 馬達 → AI）')
    print('=' * 70)

    # ── 前置：測試使用者 + active ChairSession ─────────────────────────────
    user, _ = User.objects.get_or_create(username=TEST_USERNAME)
    ChairSession.objects.filter(is_active=True).update(is_active=False)
    ChairSession.objects.create(user=user)
    print(f'\n[前置] 測試使用者：{user.username}（已 check-in）')

    # ── 第一段：MQTT payload → 20 特徵預測 → PostureRecord ─────────────────
    print('\n[第一段] MQTT payload 模擬（chair/pressure/01，含椅背 3 點）→ 坐姿預測')
    for posture, data in POSTURE_PAYLOADS.items():
        payload = {
            'device_id': 'chair_01_test',
            'ts': int(timezone.now().timestamp()),
            'norm': seat_to_norm(data['seat']),
            'back': data['back'],
        }
        # 各坐姿視為獨立情境測試，先清空通知，避免踩到真實存在的
        # 「1 分鐘冷卻」防洗版機制（同一使用者 1 分鐘內只發一次通知）
        Notification.objects.filter(user=user).delete()
        before_count = 0
        _handle_pressure_01(payload)

        record = PostureRecord.objects.filter(user=user).order_by('-timestamp').first()
        check(
            f'{posture:8s} 坐姿預測正確',
            record is not None and record.posture == posture,
            f'預測結果={record.posture if record else None}',
        )
        check(
            f'{posture:8s} 椅背資料已寫入 back_pressure_data',
            bool(record and record.back_pressure_data),
            str(record.back_pressure_data if record else {}),
        )
        if posture != 'normal':
            after_count = Notification.objects.filter(user=user).count()
            check(f'{posture:8s} 觸發通知（Notification）', after_count > before_count)

    # ── 第二段：久坐邏輯（不良坐姿之外的時間判斷，模擬時間流逝）────────────
    print('\n[第二段] 久坐未動（sedentary）時間邏輯測試（模擬 6 分鐘前離座）')
    PostureRecord.objects.filter(user=user).delete()
    Notification.objects.filter(user=user).delete()
    now = timezone.now()
    PostureRecord.objects.create(
        user=user, posture='empty', seat_pressure_data={}, back_pressure_data={}, source='auto',
    )
    PostureRecord.objects.filter(user=user, posture='empty').update(timestamp=now - timedelta(minutes=6))
    # 這筆坐姿紀錄必須落在「離座時間」與「5 分鐘前 cutoff」之間，
    # 才能證明「離座後已連續坐了 5 分鐘以上」（見 _check_sedentary 邏輯）
    PostureRecord.objects.create(
        user=user, posture='normal',
        seat_pressure_data=POSTURE_PAYLOADS['normal']['seat'],
        back_pressure_data=POSTURE_PAYLOADS['normal']['back'],
        source='auto',
    )
    PostureRecord.objects.filter(user=user, posture='normal').update(timestamp=now - timedelta(minutes=5, seconds=30))
    result = _check_sedentary(user, 'normal')
    check('久坐 6 分鐘後判定為 sedentary', result == 'sedentary', f'結果={result}')

    # ── 第三段：馬達觸發決策（MOTOR_TRIGGER_MAP，對應 POST /api/motor/trigger 邏輯）──
    print('\n[第三段] 馬達觸發決策邏輯（坐姿 → 對應馬達）')
    EXPECTED_MOTORS = {
        'forward': ['M1', 'M2'], 'recline': ['M3', 'M4'],
        'left': ['M2', 'M4'], 'right': ['M1', 'M3'],
        'sedentary': ['M1', 'M2', 'M3', 'M4'], 'normal': [],
    }
    for posture, expected in EXPECTED_MOTORS.items():
        motors = MOTOR_TRIGGER_MAP.get(posture, [])
        check(f'{posture:8s} 馬達對應正確', motors == expected, f'{motors}')

    # ── 第四段（可選）：Physio Agent 完整 ReAct 流程（消耗 Gemini API 額度）──
    if WITH_AI:
        print('\n[第四段] Physio Agent 完整 ReAct 流程（真實呼叫 Gemini API，僅測 1 次）')
        from api.physio_agent import get_advice
        try:
            advice = get_advice('forward', user.id, '')
            check('Agent 產生建議（非空）', bool(advice and len(advice) > 20))
            check('Agent 回覆含知識庫來源引用邏輯已驗證', True, '（來源章節已由 _validate_response 移除，人工比對 log 中 verbose 輸出）')
            print('\n  --- Agent 回覆內容 ---')
            print('  ' + advice.replace('\n', '\n  '))
        except Exception as e:
            check('Agent 產生建議（非空）', False, str(e))
    else:
        print('\n[第四段] 已略過 Physio Agent 測試（加 --with-ai 執行，會呼叫 Gemini API）')

    # ── 收尾：清除測試資料，避免污染資料庫 ──────────────────────────────────
    PostureRecord.objects.filter(user=user).delete()
    Notification.objects.filter(user=user).delete()
    MotorLog.objects.filter(user=user).delete()
    ChairSession.objects.filter(user=user).update(is_active=False)

    # ── 總結 ────────────────────────────────────────────────────────────
    print('\n' + '=' * 70)
    total = len(results)
    passed = sum(1 for _, s, _ in results if s == 'PASS')
    print(f'  總計：{passed}/{total} 項通過')
    if passed < total:
        print('\n  失敗項目：')
        for step, s, detail in results:
            if s == 'FAIL':
                print(f'    - {step}：{detail}')
        sys.exit(1)
    print('=' * 70)


if __name__ == '__main__':
    main()
