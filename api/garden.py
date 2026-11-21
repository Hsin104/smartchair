"""
健康花園的點數、等級與連續天數，由後端依完成紀錄（WellnessCompletion）計算。

原本由 App 自己算並存在本機（Flutter SharedPreferences，網頁版即瀏覽器 localStorage），
換瀏覽器、換埠號、換手機都會歸零。改由後端用全部完成紀錄推算，所有裝置看到同一個數字。

規則與前端 wellness_controller.dart（zhen 分支）相同，使用者看到的數字不會改變：
    - 每完成一個動作 +10 點（每日任務與 AI 建議的動作都算）
    - 當天第一個完成的動作再 +5 點
    - 每 100 點升一級：等級 = 點數 // 100 + 1
    - 連續天數：從今天往回數，每天都有完成才算（今天還沒完成時為 0，與前端相同）
"""

from datetime import timedelta

from django.utils import timezone

from .models import WellnessCompletion

POINTS_PER_TASK = 10
FIRST_OF_DAY_BONUS = 5
LEVEL_SIZE = 100


def garden_state(user) -> dict:
    dates = list(WellnessCompletion.objects.filter(user=user).values_list('date', flat=True))
    days = set(dates)
    points = len(dates) * POINTS_PER_TASK + len(days) * FIRST_OF_DAY_BONUS

    today = timezone.localdate()
    streak, cursor = 0, today
    while cursor in days:
        streak += 1
        cursor -= timedelta(days=1)

    return {
        'points':            points,
        'level':             points // LEVEL_SIZE + 1,
        'points_in_level':   points % LEVEL_SIZE,
        'level_size':        LEVEL_SIZE,
        'streak':            streak,
        'total_completions': len(dates),
        'active_days':       len(days),
        'completed_today':   dates.count(today),
    }
