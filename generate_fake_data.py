"""
假資料產生器
產生 10 位受測者 × 6 種坐姿 × 每種 30 筆 = 1800 筆感測器數值
寫入 PostgreSQL 資料庫，供後續模型訓練使用

執行方式：
    python generate_fake_data.py
"""

import os
import sys
import random
import django

# 初始化 Django 環境
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smartchair_backend.settings')
django.setup()

from django.contrib.auth import get_user_model
from api.models import PostureRecord

User = get_user_model()

# ── 受測者清單（10 人）────────────────────────────────────
USERS = [
    {'username': f'user{i:02d}', 'password': 'test1234',
     'height': random.uniform(155, 185),
     'weight': random.uniform(50, 90)}
    for i in range(1, 11)
]

# ── 6 種坐姿的感測器數值範圍 ──────────────────────────────
# FSR：4 個壓力感測器（前左、前右、後左、後右），值域 0~1023
# ToF：距離感測（頭部到螢幕距離），單位 cm
# IMU：pitch（前後傾角）、roll（左右傾角），單位 degree

POSTURE_PROFILES = {
    'normal': {
        # 標準坐姿：椅墊八點均衡、椅背有適中接觸
        'seat': {
            'left_back': (40, 60), 'left_mid': (40, 60), 'left_front': (38, 58),
            'center_back': (38, 55), 'center_front': (38, 55),
            'right_back': (40, 60), 'right_mid': (40, 60), 'right_front': (38, 58),
        },
        'back': {'spine_upper': (20, 40), 'spine_mid': (25, 45), 'spine_lower': (20, 38)},
    },
    'left': {
        # 左傾：左側椅墊明顯重於右側、椅背左側較高
        'seat': {
            'left_back': (60, 80), 'left_mid': (55, 75), 'left_front': (55, 75),
            'center_back': (30, 48), 'center_front': (28, 45),
            'right_back': (8, 22), 'right_mid': (8, 20), 'right_front': (8, 20),
        },
        'back': {'spine_upper': (15, 35), 'spine_mid': (15, 32), 'spine_lower': (12, 30)},
    },
    'right': {
        # 右傾：右側椅墊明顯重於左側
        'seat': {
            'left_back': (8, 22), 'left_mid': (8, 20), 'left_front': (8, 20),
            'center_back': (28, 45), 'center_front': (28, 45),
            'right_back': (60, 80), 'right_mid': (55, 75), 'right_front': (55, 75),
        },
        'back': {'spine_upper': (15, 35), 'spine_mid': (15, 32), 'spine_lower': (12, 30)},
    },
    'forward': {
        # 前傾（烏龜頸）：椅墊前排重、椅背幾乎無接觸
        'seat': {
            'left_back': (5, 18), 'left_mid': (20, 38), 'left_front': (55, 75),
            'center_back': (5, 15), 'center_front': (55, 72),
            'right_back': (5, 18), 'right_mid': (20, 38), 'right_front': (55, 75),
        },
        'back': {'spine_upper': (0, 10), 'spine_mid': (0, 8), 'spine_lower': (0, 8)},
    },
    'recline': {
        # 過度後仰：椅墊後排重、椅背高壓接觸
        'seat': {
            'left_back': (52, 72), 'left_mid': (30, 50), 'left_front': (5, 18),
            'center_back': (55, 72), 'center_front': (5, 18),
            'right_back': (52, 72), 'right_mid': (30, 50), 'right_front': (5, 18),
        },
        'back': {'spine_upper': (50, 78), 'spine_mid': (55, 80), 'spine_lower': (48, 72)},
    },
    # sedentary（久坐未動）改由 API 時間邏輯判斷，不放入訓練資料
}

SAMPLES_PER_POSTURE = 50  # 每人每種坐姿幾筆


def rand(lo, hi):
    return round(random.uniform(lo, hi), 2)


def generate_seat(profile):
    return {k: rand(*v) for k, v in profile['seat'].items()}


def generate_back(profile):
    return {k: rand(*v) for k, v in profile['back'].items()}


def main():
    print('=' * 50)
    print('  智慧辦公椅假資料產生器')
    print('=' * 50)

    # 建立使用者
    print('\n[1/2] 建立受測者帳號...')
    created_users = []
    for u in USERS:
        user, created = User.objects.get_or_create(
            username=u['username'],
            defaults={
                'height': round(u['height'], 1),
                'weight': round(u['weight'], 1),
            }
        )
        if created:
            user.set_password(u['password'])
            user.save()
            print(f'  [OK] 建立 {user.username}（身高 {user.height} cm，體重 {user.weight} kg）')
        else:
            print(f'  [skip] {user.username} 已存在，略過')
        created_users.append(user)

    # 產生坐姿紀錄
    print(f'\n[2/2] 產生坐姿數據（{len(created_users)} 人 × 6 種 × {SAMPLES_PER_POSTURE} 筆）...')
    total = 0
    for user in created_users:
        for posture, profile in POSTURE_PROFILES.items():
            records = [
                PostureRecord(
                    user=user,
                    posture=posture,
                    seat_pressure_data=generate_seat(profile),
                    back_pressure_data=generate_back(profile),
                )
                for _ in range(SAMPLES_PER_POSTURE)
            ]
            PostureRecord.objects.bulk_create(records)
            total += len(records)
        print(f'  [OK] {user.username}：{len(POSTURE_PROFILES) * SAMPLES_PER_POSTURE} 筆')

    print(f'\n完成！共寫入 {total} 筆資料')
    print(f'  受測者：{len(created_users)} 人')
    print(f'  坐姿類別：{len(POSTURE_PROFILES)} 種（不含 sedentary，改由 API 時間判斷）')
    print(f'  每人每種：{SAMPLES_PER_POSTURE} 筆')
    print('\n下一步：執行 python train_model_dl.py 開始訓練模型')


if __name__ == '__main__':
    main()
