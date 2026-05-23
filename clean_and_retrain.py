"""
清除非真實資料並重新訓練模型

執行方式：
    python clean_and_retrain.py
"""
import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smartchair_backend.settings')
django.setup()

from api.models import PostureRecord
from collections import Counter

print('=' * 55)
print('  清理資料庫 — 僅保留真實採集資料')
print('=' * 55)

total  = PostureRecord.objects.count()
real   = PostureRecord.objects.filter(source='real').count()
others = PostureRecord.objects.exclude(source='real').count()

print(f'\n目前資料庫：')
print(f'  總計        : {total} 筆')
print(f'  真實 (real) : {real} 筆')
print(f'  其他 (清除) : {others} 筆')

if real == 0:
    print('\n[Error] 沒有真實資料，請先執行 python collect_data.py')
    sys.exit(1)

postures = Counter(PostureRecord.objects.filter(source='real').values_list('posture', flat=True))
print(f'\n真實資料各姿勢分佈：')
for posture, count in sorted(postures.items()):
    print(f'  {posture:12s}: {count} 筆')

print(f'\n即將刪除 {others} 筆非真實資料，保留 {real} 筆真實資料。')
confirm = input('確認刪除？(y/N): ').strip().lower()
if confirm != 'y':
    print('已取消')
    sys.exit(0)

deleted, _ = PostureRecord.objects.exclude(source='real').delete()
print(f'\n已刪除 {deleted} 筆，資料庫剩餘 {PostureRecord.objects.count()} 筆')
print('\n下一步：重新訓練模型')
print('  python train_model_dl.py --calibrated')
