"""
在「採集電腦」上執行——把這台機器資料庫裡的真實標註坐姿資料（source='real'）匯出成 JSON，
供正式主機用 import_remote_posture_data.py 匯入。

11/22 起匯出的欄位（多人、分天收集用）：
    username        誰收集的（匯入後仍分在不同帳號下，才能做留一人驗證）
    timestamp       收集時間（匯入後保留原時間，才能做時間切分驗證）
    device_posture  椅子韌體當下的判斷（評估韌體準確率用）
    posture、seat_pressure_data、back_pressure_data

執行方式（在採集電腦、這個專案的資料夾下）：
    python export_remote_posture_data.py                     # 全部真實標註資料
    python export_remote_posture_data.py --since 2026-11-22  # 只匯出這天起收集的（建議，避免重複匯入舊資料）

輸出 posture_real_export.json（已列在 .gitignore，含使用者名稱，不進版控）。
"""

import json
import os
import sys
from collections import Counter
from datetime import date, datetime, time

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smartchair_backend.settings')
django.setup()

from django.utils import timezone

from api.models import PostureRecord

OUTPUT_PATH = 'posture_real_export.json'


def main():
    qs = (
        PostureRecord.objects
        .filter(source='real')
        .exclude(back_pressure_data={})
        .exclude(back_pressure_data__isnull=True)
        .exclude(seat_pressure_data__isnull=True)
        .select_related('user')
        .order_by('timestamp')
    )
    if '--since' in sys.argv:
        since = date.fromisoformat(sys.argv[sys.argv.index('--since') + 1])
        qs = qs.filter(timestamp__gte=timezone.make_aware(datetime.combine(since, time.min)))
        print(f'只匯出 {since} 起收集的資料')

    rows = [
        {
            'username':           r.user.username if r.user_id else None,
            'timestamp':          r.timestamp.isoformat(),
            'posture':            r.posture,
            'device_posture':     r.device_posture,
            'seat_pressure_data': r.seat_pressure_data,
            'back_pressure_data': r.back_pressure_data,
        }
        for r in qs
    ]
    print(f'找到含椅背感測器的真實坐姿資料：{len(rows)} 筆')
    if not rows:
        print('[Warning] 0 筆，請確認這台機器的 .env DB_HOST 是否指向當初採集時用的資料庫')
        return
    print('各收集者筆數：', dict(Counter(r['username'] for r in rows)))
    print('各坐姿筆數：', dict(Counter(r['posture'] for r in rows)))
    print('有韌體判斷的筆數：', sum(1 for r in rows if r['device_posture']))

    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    print(f'已匯出 {len(rows)} 筆 → {OUTPUT_PATH}')


if __name__ == '__main__':
    main()
