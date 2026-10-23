"""
Physio Agent 非同步任務處理服務：python manage.py agent_worker

流程：
    App ──POST /api/agent/jobs──▶ django（只建立 queued 任務，立刻回 202）
                                     │
                              PostgreSQL（AgentJob 資料表當作任務佇列）
                                     │
    agent_worker（本程式，單一 event loop）：每 0.5 秒認領空出來的名額數量的任務，
    每筆任務是一個 asyncio Task，await OpenAI／MCP 時不佔用執行緒，同時可以有數十筆在等待回應。
                                     │
    App ──GET /api/agent/jobs/<id>──▶ 查詢 queued／running／done／failed

為什麼這樣能撐住大量使用者：
    舊的同步 POST /api/agent 每個請求佔住 Gunicorn 一條執行緒 6～25 秒，3 worker × 8 thread
    最多同時 24 個，第 25 個人就要排隊、甚至被 timeout。這裡等待 OpenAI 時只是一個暫停中的
    coroutine，同時處理數量由 AGENT_WORKER_CONCURRENCY 控制（受 OpenAI 速率限制，不是伺服器）；
    要再提高，直接多開幾個 agent_worker 容器即可：認領任務用 SELECT ... FOR UPDATE SKIP LOCKED，
    多個 worker 不會搶到同一筆。

沒有回應的保護：
    get_advice_async 內部以 asyncio.wait_for 限制 60 秒，逾時任務標記 failed 並附中文原因，
    App 不會無限期等待。worker 本身被重啟時，正在處理中的任務會在下次啟動時標記為 failed。
"""

import asyncio
import json
import logging
import os
import tempfile
import time
from pathlib import Path

from asgiref.sync import sync_to_async
from django.core.management.base import BaseCommand
from django.db import close_old_connections, transaction
from django.utils import timezone

from api.models import AgentJob, AgentLog
from api.physio_agent import POSTURE_DISPLAY, get_advice_async
from api.stretch import recommend_exercises

logger = logging.getLogger(__name__)

CONCURRENCY   = int(os.getenv('AGENT_WORKER_CONCURRENCY', 50))
POLL_INTERVAL = 0.5

# healthcheck.py 的 agent 模式讀這個心跳檔，主迴圈每輪更新；超過 60 秒沒更新代表 event loop 卡住
HEARTBEAT_PATH = Path(tempfile.gettempdir()) / 'agent_worker_heartbeat.json'


def _write_heartbeat(running: int):
    try:
        HEARTBEAT_PATH.write_text(json.dumps({'ts': time.time(), 'running': running}))
    except OSError:
        pass


# ── 資料庫操作（同步，透過 sync_to_async 在獨立執行緒執行，不阻塞 event loop）──────

def _recover_interrupted():
    """worker 重啟前沒處理完的任務：無法得知做到哪一步，標記失敗讓 App 提示使用者重送。"""
    close_old_connections()
    return AgentJob.objects.filter(status=AgentJob.STATUS_RUNNING).update(
        status=AgentJob.STATUS_FAILED,
        error='處理中斷（服務重新啟動），請重新送出',
        finished_at=timezone.now(),
    )


def _claim(limit: int) -> list[AgentJob]:
    """認領最多 limit 筆排隊中的任務；SKIP LOCKED 讓多個 worker 同時跑也不會搶到同一筆。"""
    close_old_connections()
    with transaction.atomic():
        jobs = list(
            AgentJob.objects.select_for_update(skip_locked=True)
            .filter(status=AgentJob.STATUS_QUEUED)
            .order_by('created_at')[:limit]
        )
        if jobs:
            AgentJob.objects.filter(id__in=[j.id for j in jobs]).update(
                status=AgentJob.STATUS_RUNNING, started_at=timezone.now(),
            )
    return jobs


def _finish(job: AgentJob, advice: str = '', steps=None, error: str = ''):
    close_old_connections()
    if error:
        AgentJob.objects.filter(id=job.id).update(
            status=AgentJob.STATUS_FAILED, error=error, finished_at=timezone.now(),
        )
        return

    result = {
        'posture':               job.posture,
        'posture_display':       POSTURE_DISPLAY.get(job.posture, job.posture),
        'advice':                advice,
        'steps':                 steps or [],
        'recommended_exercises': recommend_exercises(job.posture),
    }
    AgentJob.objects.filter(id=job.id).update(
        status=AgentJob.STATUS_DONE, result=result, finished_at=timezone.now(),
    )
    AgentLog.objects.create(
        user_id=job.user_id, posture=job.posture, user_message=job.user_message,
        agent_reply=advice, steps=steps or [],
    )


# ── 非同步主流程 ──────────────────────────────────────────────────────────────

async def _process(job: AgentJob):
    try:
        try:
            advice, steps = await get_advice_async(job.posture, job.user_id, job.user_message)
        except Exception as e:
            # get_advice_async 已把逾時／額度／MCP 斷線轉成中文訊息
            logger.warning(f'[agent_worker] 任務 {job.id} 失敗：{e}')
            await sync_to_async(_finish)(job, error=f'Agent 暫時無法使用：{e}')
            return
        await sync_to_async(_finish)(job, advice=advice, steps=steps)
    except Exception:
        # 寫回結果失敗（例如資料庫瞬斷）：記錄後放棄這筆，不讓例外影響其他任務
        logger.exception(f'[agent_worker] 任務 {job.id} 寫回結果失敗')


async def _main():
    recovered = await sync_to_async(_recover_interrupted)()
    if recovered:
        logger.warning(f'[agent_worker] {recovered} 筆中斷任務已標記為失敗')
    print(f'[agent_worker] 啟動，同時處理上限 {CONCURRENCY} 筆', flush=True)

    running: set[asyncio.Task] = set()
    while True:
        _write_heartbeat(len(running))
        free = CONCURRENCY - len(running)
        if free > 0:
            try:
                jobs = await sync_to_async(_claim)(free)
            except Exception as e:
                # 資料庫暫時連不上不該讓整個 worker 結束，下一輪再試
                logger.error(f'[agent_worker] 認領任務失敗：{e}')
                jobs = []
            for job in jobs:
                task = asyncio.create_task(_process(job))
                running.add(task)
                task.add_done_callback(running.discard)
        await asyncio.sleep(POLL_INTERVAL)


class Command(BaseCommand):
    help = 'Physio Agent 非同步任務處理服務（async/await 同時處理多筆 AgentJob）'
    # 不跑 Django 系統檢查：檢查會載入 urls → views → TensorFlow 坐姿模型（約 600MB），worker 用不到
    requires_system_checks = []

    def handle(self, *args, **options):
        asyncio.run(_main())
