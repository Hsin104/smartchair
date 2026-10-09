"""
在「遠端採集電腦」上執行——把該機器資料庫裡的真實坐姿資料（含椅背感測器）
匯出成 JSON，供主開發機 import_remote_posture_data.py 匯入。

只匯出 posture / seat_pressure_data / back_pressure_data / timestamp 四個欄位，
不含 user/id 等跨資料庫不通用的欄位，匯入端會指定一個使用者重新建立紀錄。

執行方式（在遠端電腦、這個專案的資料夾下）：
    python export_remote_posture_data.py

執行後會在專案資料夾產生 posture_real_export.json，
若這台電腦跟主開發機同步同一個 OneDrive 帳號，存在這個資料夾路徑下會自動同步過去；
否則請手動把這個檔案傳到主開發機的同一個專案資料夾。
"""

import json
import os

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smartchair_backend.settings')
django.setup()

from api.models import PostureRecord

OUTPUT_PATH = 'posture_real_export.json'


def main():
    qs = (
        PostureRecord.objects
        .filter(source='real')
        .exclude(back_pressure_data={})
        .exclude(back_pressure_data__isnull=True)
        .exclude(seat_pressure_data__isnull=True)
    )
    count = qs.count()
    print(f'找到含椅背感測器的真實坐姿資料：{count} 筆')
    if count == 0:
        print('[Warning] 0 筆，請確認這台機器的 .env DB_HOST 是否指向當初採集時用的資料庫')
        return

    rows = [
        {
            'posture':            r.posture,
            'seat_pressure_data': r.seat_pressure_data,
            'back_pressure_data': r.back_pressure_data,
            'timestamp':          r.timestamp.isoformat(),
        }
        for r in qs
    ]

    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)

    print(f'已匯出 {count} 筆 → {OUTPUT_PATH}')
    print('請確認這個檔案有同步/傳到主開發機的同一個專案資料夾，再執行 import_remote_posture_data.py')


if __name__ == '__main__':
    main()
