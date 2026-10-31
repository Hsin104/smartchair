"""
健康花園每日任務（GET /api/agent/stretch-plan 的 tasks）。

規則（10/31 與前端確認）：
- 每人每天一份、3 個任務，同一天內固定（前端用任務 id 判斷今天做過沒）
- 動作只從知識庫 stretch_video_map.json 挑，影片連結查表帶入，不讓 LLM 產生網址
- 不與使用者最近一次 AI 建議（recommended_exercises）重複，以動作類別 group 判斷，
  名稱不同但實際動作相同（例如 4 胸部擴展、14 胸椎伸展）也算重複
- 當天之後才問 AI 時，只換掉重複的任務，其他任務不動
- 昨天完成過的動作盡量不重複出（輪替）
- 7 天坐姿資料不足 → 通用安全動作；LLM 失敗 → 依坐姿頻率查表（source=rule）
"""
import json
import logging
from collections import Counter
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError
from django.utils import timezone

from .models import AgentJob, DailyStretchPlan, PostureRecord, WellnessCompletion
from .stretch import GENERAL_EXERCISE_IDS, exercise_payload, exercises_by_id, get_stretch_map

logger = logging.getLogger(__name__)

TASK_COUNT  = 3
PERIOD_DAYS = 7
MIN_RECORDS = 100   # 7 天內坐姿紀錄少於這個數（每 5 秒一筆約 8 分鐘）視為資料不足
BAD_POSTURES = ('forward', 'left', 'right', 'recline', 'sedentary')

POSTURE_NAMES = {
    'forward': '頭部前傾', 'left': '身體左傾', 'right': '身體右傾', 'recline': '過度後仰', 'sedentary': '久坐',
}

_PROMPT = """你是物理治療師助理，要從「候選動作」中挑選 3 個今天最適合這位使用者的伸展動作，並各寫一句個人化說明。

規則：
1. 只能用候選清單裡的 id，3 個 id 的 group 必須都不同
2. 優先處理使用者最常出現的壞坐姿；近期完成次數多的動作可以換成其他部位
3. posture 填這個動作要改善的坐姿代碼，必須是該動作 postures 裡的其中一個
4. description 用繁體中文 1～2 句（60 字以內），說明為什麼今天建議做、做的時候注意什麼；
   不要寫網址、不要做醫療診斷、不要寫候選資料中沒有的數字
5. 只輸出 JSON：{"tasks": [{"id": 數字, "posture": "代碼", "description": "..."}]}

使用者近 7 天坐姿統計：
%(stats)s

近 30 天完成次數（動作 id: 次數）：%(done)s

候選動作：
%(candidates)s"""


def _seven_day_stats(user):
    since = timezone.now() - timedelta(days=PERIOD_DAYS)
    postures = list(
        PostureRecord.objects.filter(user=user, timestamp__gte=since)
        .exclude(posture='empty').values_list('posture', flat=True)
    )
    bad = Counter(p for p in postures if p in BAD_POSTURES)
    return len(postures), bad


def latest_ai_job(user):
    """最近 7 天內完成的 AI 建議。"""
    return (AgentJob.objects
            .filter(user=user, status=AgentJob.STATUS_DONE,
                    finished_at__gte=timezone.now() - timedelta(days=PERIOD_DAYS))
            .order_by('-finished_at').first())


def _ai_groups(job):
    """AI 建議中出現的動作類別；舊任務的結果沒有 group 欄位，用 id 查知識庫補上。"""
    if not job or not job.result:
        return set()
    by_id = exercises_by_id()
    return {by_id[ex['id']]['group'] for ex in job.result.get('recommended_exercises') or []
            if ex.get('id') in by_id}


def _candidates(bad_counts, exclude_groups, avoid_ids):
    """依壞坐姿頻率由高到低列出候選動作 [(動作, 對應坐姿)]，同類別只留一個；昨天做過的排到最後。"""
    by_id   = exercises_by_id()
    ex_map  = get_stretch_map()['posture_exercise_map']
    picked, groups = [], set(exclude_groups)
    for posture, _ in bad_counts.most_common():
        for ex_id in ex_map.get(posture, []):
            ex = by_id[ex_id]
            if ex['group'] not in groups:
                groups.add(ex['group'])
                picked.append((ex, posture))
    return ([c for c in picked if c[0]['id'] not in avoid_ids]
            + [c for c in picked if c[0]['id'] in avoid_ids])


def _fill_general(tasks, exclude_groups):
    """個人化動作不足 3 個時，用通用安全動作補足（不與 AI 建議、已選任務同類別）。"""
    by_id  = exercises_by_id()
    groups = set(exclude_groups) | {t['group'] for t in tasks}
    extra  = GENERAL_EXERCISE_IDS + get_stretch_map()['posture_exercise_map']['sedentary']
    for ex_id in extra:
        if len(tasks) >= TASK_COUNT:
            break
        ex = by_id[ex_id]
        if ex['group'] not in groups:
            groups.add(ex['group'])
            tasks.append(exercise_payload(ex, 'sedentary'))
    return tasks


def _llm_pick(bad_counts, candidates, done_counts):
    """請 LLM 從候選中挑 3 個並寫說明；回傳通過檢查的任務（可能少於 3 個），失敗丟例外。"""
    from langchain_openai import ChatOpenAI

    total = sum(bad_counts.values())
    stats = '\n'.join(f'- {p}（{POSTURE_NAMES[p]}）：{c} 筆，佔壞坐姿 {c / total:.0%}'
                      for p, c in bad_counts.most_common())
    cand  = '\n'.join(
        json.dumps({'id': ex['id'], 'group': ex['group'], 'name': ex['name'], 'target': ex['target_muscles'],
                    'postures': [p for p in ex['posture_trigger'] if p in BAD_POSTURES]}, ensure_ascii=False)
        for ex, _ in candidates)
    llm = ChatOpenAI(model=settings.OPENAI_MODEL, api_key=settings.OPENAI_API_KEY, temperature=0.3, timeout=20,
                     model_kwargs={'response_format': {'type': 'json_object'}})
    reply = llm.invoke(_PROMPT % {'stats': stats, 'done': json.dumps(done_counts) if done_counts else '無',
                                  'candidates': cand})
    picks = json.loads(reply.content).get('tasks') or []

    allowed = {ex['id']: (ex, posture) for ex, posture in candidates}
    tasks, groups = [], set()
    for item in picks:
        ex, default_posture = allowed.get(item.get('id') if isinstance(item, dict) else None, (None, None))
        if ex is None or ex['group'] in groups:
            continue
        posture = item.get('posture') if item.get('posture') in ex['posture_trigger'] else default_posture
        desc = str(item.get('description') or '').strip()
        if not desc or len(desc) > 120 or 'http' in desc:
            desc = None   # 說明不合格就用知識庫原本的說明
        groups.add(ex['group'])
        tasks.append(exercise_payload(ex, posture, desc))
        if len(tasks) == TASK_COUNT:
            break
    return tasks


def _build(user, exclude_groups):
    total, bad_counts = _seven_day_stats(user)
    if total < MIN_RECORDS or not bad_counts:
        return _fill_general([], exclude_groups), DailyStretchPlan.SOURCE_GENERAL

    today = timezone.localdate()
    yesterday_ids = set(WellnessCompletion.objects.filter(user=user, date=today - timedelta(days=1))
                        .values_list('exercise_id', flat=True))
    done_counts = dict(Counter(WellnessCompletion.objects.filter(user=user, date__gte=today - timedelta(days=30))
                               .values_list('exercise_id', flat=True)))
    candidates = _candidates(bad_counts, exclude_groups, yesterday_ids)
    if not candidates:   # 對應的動作都已在 AI 建議裡，不必呼叫 LLM
        return _fill_general([], exclude_groups), DailyStretchPlan.SOURCE_GENERAL

    try:
        tasks, source = _llm_pick(bad_counts, candidates, done_counts), DailyStretchPlan.SOURCE_AI
    except Exception:
        logger.exception('每日任務 LLM 產生失敗，改用查表')
        tasks, source = [], DailyStretchPlan.SOURCE_RULE
    if not tasks:
        source = DailyStretchPlan.SOURCE_RULE
    picked = {t['group'] for t in tasks}
    for ex, posture in candidates:
        if len(tasks) >= TASK_COUNT:
            break
        if ex['group'] not in picked:
            picked.add(ex['group'])
            tasks.append(exercise_payload(ex, posture))
    return _fill_general(tasks, exclude_groups), source


def _replace_duplicates(user, plan, ai_groups):
    """有新的 AI 建議時，只換掉同類別的任務，其餘任務（與它們的 id）保持不變。"""
    keep = [t for t in plan.tasks if t['group'] not in ai_groups]
    if len(keep) == len(plan.tasks):
        return plan.tasks
    _, bad_counts = _seven_day_stats(user)
    used = ai_groups | {t['group'] for t in keep}
    replacements = [exercise_payload(ex, posture) for ex, posture in _candidates(bad_counts, used, set())]
    replacements = _fill_general(replacements[:len(plan.tasks) - len(keep)], used)
    it = iter(replacements)
    return [t if t['group'] not in ai_groups else next(it) for t in plan.tasks]


def get_daily_plan(user):
    """取得（必要時產生或更新）使用者今天的每日任務。"""
    today  = timezone.localdate()
    job    = latest_ai_job(user)
    groups = _ai_groups(job)
    plan   = DailyStretchPlan.objects.filter(user=user, date=today).first()

    if plan is None:
        tasks, source = _build(user, groups)
        try:
            plan = DailyStretchPlan.objects.create(user=user, date=today, tasks=tasks, source=source,
                                                   agent_job_id=job.id if job else None)
        except IntegrityError:   # 同一時間有另一個請求先建好了
            plan = DailyStretchPlan.objects.get(user=user, date=today)
    elif job and plan.agent_job_id != job.id:
        plan.tasks = _replace_duplicates(user, plan, groups)
        plan.agent_job_id = job.id
        plan.save(update_fields=['tasks', 'agent_job_id', 'updated_at'])
    return plan
