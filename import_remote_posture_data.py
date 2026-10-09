"""
在主開發機執行——讀取 export_remote_posture_data.py 在遠端電腦匯出的
posture_real_export.json，匯入成這邊資料庫的 PostureRecord（source='real'）。

執行方式：
    python import_remote_posture_data.py                # 預設掛在 hsin 帳號下（既有 real 資料的慣例）
    python import_remote_posture_data.py --user xiao     # 指定掛在其他使用者底下

會先印出筆數與坐姿分布讓你確認，再詢問是否要真的寫入資料庫，避免誤匯入或重複匯入。
"""

import json
import os
import sys
from collections import Counter

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smartchair_backend.settings')
django.setup()

from django.contrib.auth import get_user_model
from django.utils.dateparse import parse_datetime
from api.models import PostureRecord

User = get_user_model()

INPUT_PATH = 'posture_real_export.json'

if '--user' in sys.argv:
    idx = sys.argv.index('--user')
    USERNAME = sys.argv[idx + 1]
else:
    USERNAME = 'hsin'


def main():
    if not os.path.exists(INPUT_PATH):
        print(f'[Error] 找不到 {INPUT_PATH}，請先確認遠端匯出的檔案有同步/傳到這個專案資料夾')
        sys.exit(1)

    with open(INPUT_PATH, encoding='utf-8') as f:
        rows = json.load(f)

    if not rows:
        print('[Error] 檔案裡沒有資料')
        sys.exit(1)

    print(f'讀到 {len(rows)} 筆，坐姿分布：{Counter(r["posture"] for r in rows)}')

    try:
        user = User.objects.get(username=USERNAME)
    except User.DoesNotExist:
        print(f'[Error] 找不到使用者 {USERNAME}，請用 --user <username> 指定既有帳號')
        sys.exit(1)

    existing = PostureRecord.objects.filter(user=user, source='real').count()
    print(f'{USERNAME} 目前已有 {existing} 筆 real 資料（匯入後不會檢查重複，請確認這批資料沒匯入過）')

    answer = input(f'確定要把這 {len(rows)} 筆資料匯入到 {USERNAME} 帳號下嗎？(yes/no): ').strip().lower()
    if answer != 'yes':
        print('已取消')
        return

    records = [
        PostureRecord(
            user=user,
            posture=r['posture'],
            seat_pressure_data=r['seat_pressure_data'],
            back_pressure_data=r['back_pressure_data'],
            source='real',
        )
        for r in rows
    ]
    PostureRecord.objects.bulk_create(records)
    print(f'已匯入 {len(records)} 筆到 {USERNAME} 帳號下（source=real）')
    print('接下來可以執行 python analyze_posture_model.py 用真實資料重跑混淆矩陣分析')


if __name__ == '__main__':
    main()
