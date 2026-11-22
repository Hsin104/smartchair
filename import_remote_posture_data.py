"""
在正式主機執行——讀取 export_remote_posture_data.py 匯出的 posture_real_export.json，
匯入成這邊資料庫的 PostureRecord（source='real'）。

11/22 起：
    - 每筆資料照匯出時的 username 分在各自帳號下（帳號不存在時建立「不能登入」的收集用帳號）
      → 才能做留一人驗證；--user 可強制全部掛在同一個帳號（舊格式檔案沒有 username 時必須指定）
    - 保留原本的收集時間（timestamp）→ 才能做時間切分驗證
    - 保留椅子韌體的判斷（device_posture）
    - 同一帳號、同一時間的紀錄已存在時略過，重複執行不會重複匯入

執行方式：
    python import_remote_posture_data.py
    python import_remote_posture_data.py --user hsin     # 全部掛在 hsin 帳號下

會先印出筆數與分布讓你確認，再詢問是否寫入。
"""

import json
import os
import sys
from collections import Counter

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smartchair_backend.settings')
django.setup()

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils.dateparse import parse_datetime

from api.models import PostureRecord

User = get_user_model()

INPUT_PATH = 'posture_real_export.json'
FORCE_USER = sys.argv[sys.argv.index('--user') + 1] if '--user' in sys.argv[:-1] else None


def main():
    if not os.path.exists(INPUT_PATH):
        print(f'[Error] 找不到 {INPUT_PATH}，請先把採集電腦匯出的檔案放到這個專案資料夾')
        sys.exit(1)
    with open(INPUT_PATH, encoding='utf-8') as f:
        rows = json.load(f)
    if not rows:
        print('[Error] 檔案裡沒有資料')
        sys.exit(1)

    for r in rows:
        r['_user'] = FORCE_USER or r.get('username')
    if any(not r['_user'] for r in rows):
        print('[Error] 有資料沒有 username（舊格式的匯出檔），請用 --user <username> 指定要掛在哪個帳號下')
        sys.exit(1)

    print(f'讀到 {len(rows)} 筆')
    print('各帳號筆數：', dict(Counter(r['_user'] for r in rows)))
    print('各坐姿筆數：', dict(Counter(r['posture'] for r in rows)))
    usernames = sorted({r['_user'] for r in rows})
    missing = [u for u in usernames if not User.objects.filter(username=u).exists()]
    if missing:
        print(f'這些帳號不存在，會建立成不能登入的收集用帳號：{missing}')

    if input('確定要匯入嗎？(yes/no): ').strip().lower() != 'yes':
        print('已取消')
        return

    with transaction.atomic():
        users = {}
        for u in usernames:
            user, created = User.objects.get_or_create(username=u)
            if created:
                user.set_unusable_password()
                user.save()
            users[u] = user

        created_n = skipped = 0
        for r in rows:
            user, ts = users[r['_user']], parse_datetime(r['timestamp'])
            if PostureRecord.objects.filter(user=user, source='real', timestamp=ts).exists():
                skipped += 1
                continue
            rec = PostureRecord.objects.create(
                user=user, posture=r['posture'], source='real',
                seat_pressure_data=r['seat_pressure_data'], back_pressure_data=r['back_pressure_data'],
                device_posture=r.get('device_posture'),
            )
            # timestamp 是 auto_now_add，建立時一定會被設成現在，要另外改回收集時間
            PostureRecord.objects.filter(pk=rec.pk).update(timestamp=ts)
            created_n += 1

    print(f'已匯入 {created_n} 筆（略過已存在 {skipped} 筆），保留原收集時間與韌體判斷')
    print('接下來可以在容器內執行：python - --strict < compare_esp32_rule.py 做時間切分與留一人驗證')


if __name__ == '__main__':
    main()
