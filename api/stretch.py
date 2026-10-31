"""
伸展動作查表（knowledge_base/stretch_video_map.json），不經過 LLM。

獨立成模組而不放在 views.py：views.py 匯入時會載入 TensorFlow 坐姿模型（約 600MB），
agent_worker 只需要查表，不該為此載入模型。
"""
import json
from pathlib import Path

_STRETCH_MAP = None

# 資料不足或個人化動作不夠時補上的通用安全動作（任何坐姿都適用、沒有關節負擔）
GENERAL_EXERCISE_IDS = [13, 16, 18, 9]


def get_stretch_map():
    global _STRETCH_MAP
    if _STRETCH_MAP is None:
        map_path = Path(__file__).resolve().parent.parent / 'knowledge_base' / 'stretch_video_map.json'
        with open(map_path, encoding='utf-8') as f:
            _STRETCH_MAP = json.load(f)
    return _STRETCH_MAP


def exercises_by_id():
    return {ex['id']: ex for ex in get_stretch_map()['exercises']}


def exercise_payload(ex, posture, description=None):
    """
    AI 建議（recommended_exercises）與每日任務（tasks）共用的動作格式，前端用 id 判斷重複。
    title／description／posture／duration_sec／video_url 是 10/31 統一的新欄位；
    name／youtube_url 等舊欄位保留，舊版 App 不用改。
    """
    return {
        'id':             ex['id'],
        'group':          ex['group'],
        'title':          ex['name'],
        'description':    description or ex['description'],
        'posture':        posture,
        'duration_sec':   ex['duration_sec'],
        'duration':       f'{ex["duration_sec"]} 秒',
        'video_url':      ex['youtube_url'],
        'name':           ex['name'],
        'target_muscles': ex['target_muscles'],
        'reps':           ex['reps'],
        'youtube_url':    ex['youtube_url'],
        'youtube_title':  ex['youtube_title'],
    }


def recommend_exercises(posture, limit=3):
    """依單一坐姿直接查表回傳建議伸展動作（含 YouTube 連結），不經過 LLM。"""
    by_id  = exercises_by_id()
    ex_ids = get_stretch_map()['posture_exercise_map'].get(posture, [])
    return [exercise_payload(by_id[ex_id], posture) for ex_id in ex_ids[:limit] if ex_id in by_id]
