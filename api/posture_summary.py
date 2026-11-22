"""
今日坐姿摘要（GET /api/posture/today）：每種坐姿今天坐了幾分鐘、進入幾次。

為什麼不直接數紀錄筆數：韌體 2.0 有變動才送資料（坐著不動約 5 秒一筆、動來動去每秒 1～2 筆），
一筆紀錄代表的時間長短不一，「筆數」既不是次數，比例也不是時間比例。
前端原本拿最近 100 筆來畫「今日分布」，實際只反映最近幾分鐘，舊資料被擠掉時數字還會變小。

計算方式：
    - 分鐘：每筆紀錄算到下一筆的時間，單筆最多 MAX_GAP 秒；最後一筆算到現在（同樣最多 MAX_GAP 秒）；
      遇到 empty（離座）就停止計時，empty 本身不算時間
      MAX_GAP＝10 秒：韌體 2.0 有人坐著時最慢每 5 秒送一筆，間隔超過 10 秒代表斷線、換人入座或離開，
      不能算進同一個坐姿（11/22 由 60 秒改為 10 秒：備用帳號 user01 的紀錄與入座者交錯時，60 秒會灌大時間）
    - 次數：同一坐姿連續（中間沒有離座、沒有超過 MAX_GAP 的空檔）持續 MIN_EPISODE 秒以上才算一次。
      模型逐筆判斷時常在相鄰坐姿間跳動，不設門檻的話 12 分鐘會算出上百次（與通知的防跳動同樣道理）；
      短暫跳動的時間仍算進分鐘數，只是不算成一次
    - 今天：台灣時間 00:00 起
"""

from collections import defaultdict
from datetime import datetime, time, timedelta

from django.utils import timezone

from .models import PostureRecord
from .physio_agent import POSTURE_DISPLAY

MAX_GAP = timedelta(seconds=10)
MIN_EPISODE_SECONDS = 10


def today_summary(user, now=None) -> dict:
    now = now or timezone.now()
    today = timezone.localdate(now)
    start = timezone.make_aware(datetime.combine(today, time.min))
    rows = list(PostureRecord.objects.filter(user=user, timestamp__gte=start, timestamp__lte=now)
                .exclude(source='fake').order_by('timestamp').values_list('timestamp', 'posture'))

    seconds, episodes, records = defaultdict(float), defaultdict(int), defaultdict(int)
    run_posture, run_seconds = None, 0.0      # 目前這段連續同一坐姿

    def close_run():
        if run_posture and run_seconds >= MIN_EPISODE_SECONDS:
            episodes[run_posture] += 1

    prev_ts = None
    for i, (ts, posture) in enumerate(rows):
        if posture == 'empty':
            close_run()
            run_posture, run_seconds, prev_ts = None, 0.0, None
            continue
        if posture != run_posture or prev_ts is None or ts - prev_ts > MAX_GAP:
            close_run()
            run_posture, run_seconds = posture, 0.0
        end = rows[i + 1][0] if i + 1 < len(rows) else now
        duration = min(end - ts, MAX_GAP).total_seconds()
        records[posture] += 1
        seconds[posture] += duration
        run_seconds += duration
        prev_ts = ts
    close_run()

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
