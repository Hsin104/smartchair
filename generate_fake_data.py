"""
假資料產生器
模式 A（預設）：產生原始絕對值資料，供未校準模型訓練
模式 B（--calibrated）：產生 delta（相對基準）資料，供校準模型訓練

執行方式：
    python generate_fake_data.py               # 模式 A
    python generate_fake_data.py --calibrated  # 模式 B
"""

import os
import sys
import random
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smartchair_backend.settings')
django.setup()

from django.contrib.auth import get_user_model
from api.models import PostureRecord

User = get_user_model()

USERS = [
    {'username': f'user{i:02d}', 'password': 'test1234',
     'height': random.uniform(155, 185),
     'weight': random.uniform(50, 90)}
    for i in range(1, 11)
]

# ── 模式 A：原始絕對值（未校準模型用）─────────────────────────────────────────
POSTURE_PROFILES = {
    'normal': {
        'seat': {
            'left_back': (40, 60), 'left_mid': (40, 60), 'left_front': (38, 58),
            'center_back': (38, 55), 'center_front': (38, 55),
            'right_back': (40, 60), 'right_mid': (40, 60), 'right_front': (38, 58),
        },
        'back': {'spine_upper': (20, 40), 'spine_mid': (25, 45), 'spine_lower': (20, 38)},
    },
    'left': {
        'seat': {
            'left_back': (60, 80), 'left_mid': (55, 75), 'left_front': (55, 75),
            'center_back': (30, 48), 'center_front': (28, 45),
            'right_back': (8, 22), 'right_mid': (8, 20), 'right_front': (8, 20),
        },
        'back': {'spine_upper': (15, 35), 'spine_mid': (15, 32), 'spine_lower': (12, 30)},
    },
    'right': {
        'seat': {
            'left_back': (8, 22), 'left_mid': (8, 20), 'left_front': (8, 20),
            'center_back': (28, 45), 'center_front': (28, 45),
            'right_back': (60, 80), 'right_mid': (55, 75), 'right_front': (55, 75),
        },
        'back': {'spine_upper': (15, 35), 'spine_mid': (15, 32), 'spine_lower': (12, 30)},
    },
    'forward': {
        'seat': {
            'left_back': (5, 18), 'left_mid': (20, 38), 'left_front': (55, 75),
            'center_back': (5, 15), 'center_front': (55, 72),
            'right_back': (5, 18), 'right_mid': (20, 38), 'right_front': (55, 75),
        },
        'back': {'spine_upper': (0, 10), 'spine_mid': (0, 8), 'spine_lower': (0, 8)},
    },
    'recline': {
        'seat': {
            'left_back': (52, 72), 'left_mid': (30, 50), 'left_front': (5, 18),
            'center_back': (55, 72), 'center_front': (5, 18),
            'right_back': (52, 72), 'right_mid': (30, 50), 'right_front': (5, 18),
        },
        'back': {'spine_upper': (50, 78), 'spine_mid': (55, 80), 'spine_lower': (48, 72)},
    },
}

# ── 模式 B：delta 偏移量（校準模型用）────────────────────────────────────────
# 正常坐姿時 delta ≈ 0；其他姿勢代表與基準的偏差
DELTA_PROFILES = {
    'normal': {
        'seat': {k: (-5, 5) for k in ['left_back','left_mid','left_front',
                                        'center_back','center_front',
                                        'right_back','right_mid','right_front']},
        'back': {'spine_upper': (-4, 4), 'spine_mid': (-4, 4), 'spine_lower': (-4, 4)},
    },
    'left': {
        'seat': {
            'left_back': (15, 30), 'left_mid': (12, 28), 'left_front': (12, 28),
            'center_back': (-5, 5), 'center_front': (-5, 5),
            'right_back': (-25, -10), 'right_mid': (-22, -8), 'right_front': (-22, -8),
        },
        'back': {'spine_upper': (-5, 5), 'spine_mid': (-5, 5), 'spine_lower': (-5, 5)},
    },
    'right': {
        'seat': {
            'left_back': (-25, -10), 'left_mid': (-22, -8), 'left_front': (-22, -8),
            'center_back': (-5, 5), 'center_front': (-5, 5),
            'right_back': (15, 30), 'right_mid': (12, 28), 'right_front': (12, 28),
        },
        'back': {'spine_upper': (-5, 5), 'spine_mid': (-5, 5), 'spine_lower': (-5, 5)},
    },
    'forward': {
        'seat': {
            'left_back': (-20, -8), 'left_mid': (-8, 5), 'left_front': (15, 30),
            'center_back': (-20, -8), 'center_front': (15, 30),
            'right_back': (-20, -8), 'right_mid': (-8, 5), 'right_front': (15, 30),
        },
        'back': {'spine_upper': (-18, -5), 'spine_mid': (-18, -5), 'spine_lower': (-15, -5)},
    },
    'recline': {
        'seat': {
            'left_back': (12, 25), 'left_mid': (-5, 8), 'left_front': (-22, -8),
            'center_back': (12, 25), 'center_front': (-22, -8),
            'right_back': (12, 25), 'right_mid': (-5, 8), 'right_front': (-22, -8),
        },
        'back': {'spine_upper': (20, 38), 'spine_mid': (22, 40), 'spine_lower': (18, 35)},
    },
}

SAMPLES_PER_POSTURE = 50


def rand(lo, hi):
    return round(random.uniform(lo, hi), 2)


def generate_absolute(profile):
    seat = {k: rand(*v) for k, v in profile['seat'].items()}
    back = {k: rand(*v) for k, v in profile['back'].items()}
    return seat, back


def generate_delta(delta_profile):
    """產生 delta 值（以 0 為中心的偏移量）直接作為 seat/back 數值存入資料庫。"""
    seat = {k: rand(*v) for k, v in delta_profile['seat'].items()}
    back = {k: rand(*v) for k, v in delta_profile['back'].items()}
    return seat, back


def run_mode_a(users):
    """模式 A：原始絕對值。"""
    print(f'\n[2/2] 模式 A — 產生原始數據（{len(users)} 人 × 5 種 × {SAMPLES_PER_POSTURE} 筆）...')
    total = 0
    for user in users:
        for posture, profile in POSTURE_PROFILES.items():
            records = []
            for _ in range(SAMPLES_PER_POSTURE):
                seat, back = generate_absolute(profile)
                records.append(PostureRecord(
                    user=user, posture=posture,
                    seat_pressure_data=seat, back_pressure_data=back,
                ))
            PostureRecord.objects.bulk_create(records)
            total += len(records)
        print(f'  [OK] {user.username}：{len(POSTURE_PROFILES) * SAMPLES_PER_POSTURE} 筆')
    print(f'\n完成！共寫入 {total} 筆（未校準模型用）')
    print('下一步：python train_model_dl.py')


def run_mode_b(users):
    """模式 B：delta 偏移量（校準模型用）。"""
    print(f'\n[2/2] 模式 B — 產生 delta 數據（{len(users)} 人 × 5 種 × {SAMPLES_PER_POSTURE} 筆）...')
    total = 0
    for user in users:
        for posture, delta_profile in DELTA_PROFILES.items():
            records = []
            for _ in range(SAMPLES_PER_POSTURE):
                seat, back = generate_delta(delta_profile)
                records.append(PostureRecord(
                    user=user, posture=posture,
                    seat_pressure_data=seat, back_pressure_data=back,
                ))
            PostureRecord.objects.bulk_create(records)
            total += len(records)
        print(f'  [OK] {user.username}：{len(DELTA_PROFILES) * SAMPLES_PER_POSTURE} 筆')
    print(f'\n完成！共寫入 {total} 筆（校準模型用）')
    print('下一步：python train_model_dl.py --calibrated')


def main():
    calibrated_mode = '--calibrated' in sys.argv
    mode_label = 'B（delta / 校準）' if calibrated_mode else 'A（絕對值 / 未校準）'

    print('=' * 55)
    print(f'  智慧辦公椅假資料產生器 — 模式 {mode_label}')
    print('=' * 55)

    print('\n[1/2] 建立受測者帳號...')
    created_users = []
    for u in USERS:
        user, created = User.objects.get_or_create(
            username=u['username'],
            defaults={'height': round(u['height'], 1), 'weight': round(u['weight'], 1)},
        )
        if created:
            user.set_password(u['password'])
            user.save()
            print(f'  [OK] 建立 {user.username}')
        else:
            print(f'  [skip] {user.username} 已存在')
        created_users.append(user)

    if calibrated_mode:
        run_mode_b(created_users)
    else:
        run_mode_a(created_users)


if __name__ == '__main__':
    main()
