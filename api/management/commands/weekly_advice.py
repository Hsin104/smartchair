"""
每週坐姿報告通知（AI 個人化版）

彙整每位使用者近 7 天的壞坐姿統計，交給 Physio Agent（Gemini + MCP + ReAct 迴圈，
與 POST /api/agent 走同一套 get_advice() 邏輯）產生個人化建議：
    - 寫入 AgentLog（完整 ReAct 步驟，供 Django admin 檢視）
    - 寫入 Notification（完整建議文字，供前端通知頁顯示）

執行前置需求：
    MCP Server 必須先啟動（python manage.py mcp_server，監聽 localhost:8010），
    否則呼叫 Physio Agent 會失敗。單一使用者失敗不影響其他人（見例外處理）。

設計為冪等：同一使用者 7 天內已有週報通知就不重複產生，
避免排程器重複觸發（例如手動補跑）造成重複消耗 Gemini API 額度。

執行方式：
    python manage.py weekly_advice

部署環境為 Linux 主機，排程用 cron，一過週日（週六 24:00／週日 00:00）就執行：
    crontab -e 加入：
        0 0 * * 0 cd /path/to/smartchair && /path/to/python manage.py weekly_advice >> weekly_advice.log 2>&1
"""

import logging
from collections import Counter
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from api.models import AgentLog, Notification, PostureRecord
from api.physio_agent import get_advice

User = get_user_model()
logger = logging.getLogger(__name__)

REPORT_TAG = '【每週坐姿報告】'

_WEEKLY_PROMPT = (
    '請幫我做這週的坐姿回顧：統整近 7 天各項壞坐姿問題的頻率，'
    '指出最需要優先改善的坐姿，並給出本週的具體改善建議。'
)


class Command(BaseCommand):
    help = '彙整近 7 天壞坐姿統計，交給 Physio Agent 產生個人化建議並寫入通知'

    def handle(self, *args, **options):
        cutoff  = timezone.now() - timedelta(days=7)
        created = 0
        failed  = 0

        for user in User.objects.filter(is_active=True):
            already_sent = Notification.objects.filter(
                user=user, message__startswith=REPORT_TAG, timestamp__gte=cutoff,
            ).exists()
            if already_sent:
                continue

            records = PostureRecord.objects.filter(
                user=user, timestamp__gte=cutoff,
            ).exclude(posture__in=['normal', 'empty'])
            if records.count() == 0:
                continue

            top_posture, _ = Counter(records.values_list('posture', flat=True)).most_common(1)[0]

            try:
                # posture 刻意留空：這是回顧過去 7 天的統計，不是「現在偵測到」的坐姿，
                # 傳 top_posture 進去會讓 Agent 誤判成即時坐姿。top_posture 只留給
                # AgentLog 存證，Agent 本身透過 get_posture_history 自己查 7 天統計。
                advice, steps = get_advice('', user.id, _WEEKLY_PROMPT)
            except Exception as e:
                failed += 1
                logger.warning(f'[weekly_advice] user={user.id} Physio Agent 呼叫失敗：{e}')
                continue

            AgentLog.objects.create(
                user=user,
                posture=top_posture,
                user_message=_WEEKLY_PROMPT,
                agent_reply=advice,
                steps=steps,
            )
            Notification.objects.create(user=user, message=f'{REPORT_TAG}{advice}')
            created += 1

        self.stdout.write(self.style.SUCCESS(
            f'週報通知完成：建立 {created} 筆，Agent 失敗 {failed} 筆'
        ))
