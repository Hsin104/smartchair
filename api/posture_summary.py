"""
今日坐姿摘要（GET /api/posture/today）：每種坐姿今天坐了幾分鐘、進入幾次。

為什麼不直接數紀錄筆數：韌體 2.0 有變動才送資料（坐著不動約 5 秒一筆、動來動去每秒 1～2 筆），
一筆紀錄代表的時間長短不一，「筆數」既不是次數，比例也不是時間比例。
前端原本拿最近 100 筆來畫「今日分布」，實際只反映最近幾分鐘，舊資料被擠掉時數字還會變小。

計算方式：
    - 分鐘：每筆紀錄算到下一筆的時間，單筆最多 MAX_GAP 秒（超過代表斷線或缺資料，不能一直累計）；
      最後一筆算到現在（同樣最多 MAX_GAP 秒）；遇到 empty（離座）就停止計時，empty 本身不算時間
    - 次數：坐姿改變、離座後回來、或與上一筆相隔超過 MAX_GAP 秒，算新的一次
    - 今天：台灣時間 00:00 起
"""

from collections import defaultdict
from datetime import datetime, time, timedelta

from django.utils import timezone

from .models import PostureRecord
from .physio_agent import POSTURE_DISPLAY

MAX_GAP = timedelta(seconds=60)


def today_summary(user, now=None) -> dict:
    now = now or timezone.now()
    today = timezone.localdate(now)
    start = timezone.make_aware(datetime.combine(today, time.min))
    rows = list(PostureRecord.objects.filter(user=user, timestamp__gte=start, timestamp__lte=now)
                .exclude(source='fake').order_by('timestamp').values_list('timestamp', 'posture'))

    seconds, episodes, records = defaultdict(float), defaultdict(int), defaultdict(int)
    prev_posture, prev_ts = None, None
    for i, (ts, posture) in enumerate(rows):
        if posture == 'empty':
            prev_posture, prev_ts = None, None
            continue
        if posture != prev_posture or prev_ts is None or ts - prev_ts > MAX_GAP:
            episodes[posture] += 1
        records[posture] += 1
        end = rows[i + 1][0] if i + 1 < len(rows) else now
        seconds[posture] += min(end - ts, MAX_GAP).total_seconds()
        prev_posture, prev_ts = posture, ts

    total = sum(seconds.values())
    postures = sorted(
        ({
            'posture':  p,
            'display':  POSTURE_DISPLAY.get(p, p),
            'minutes':  round(s / 60, 1),
            'ratio':    round(s / total, 3) if total else 0,
            'episodes': episodes[p],
            'records':  records[p],
        } for p, s in seconds.items()),
        key=lambda item: -item['minutes'],
    )
    return {
        'date':            today.isoformat(),
        'sitting_minutes': round(total / 60, 1),
        'postures':        postures,
        'updated_at':      timezone.localtime(now).isoformat(),
    }
