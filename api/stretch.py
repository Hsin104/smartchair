"""
伸展動作查表（knowledge_base/stretch_video_map.json），不經過 LLM。

獨立成模組而不放在 views.py：views.py 匯入時會載入 TensorFlow 坐姿模型（約 600MB），
agent_worker 只需要查表，不該為此載入模型。
"""
import json
from pathlib import Path

_STRETCH_MAP = None


def get_stretch_map():
    global _STRETCH_MAP
    if _STRETCH_MAP is None:
        map_path = Path(__file__).resolve().parent.parent / 'knowledge_base' / 'stretch_video_map.json'
        with open(map_path, encoding='utf-8') as f:
            _STRETCH_MAP = json.load(f)
    return _STRETCH_MAP


def recommend_exercises(posture, limit=3):
    """依單一坐姿直接查表回傳建議伸展動作（含 YouTube 連結），不經過 LLM。"""
    stretch_map     = get_stretch_map()
    exercises_by_id = {ex['id']: ex for ex in stretch_map['exercises']}
    ex_ids          = stretch_map['posture_exercise_map'].get(posture, [])

    return [
        {
            'id':             ex['id'],
            'name':           ex['name'],
            'target_muscles': ex['target_muscles'],
            'reps':           ex['reps'],
            'duration_sec':   ex['duration_sec'],
            'youtube_url':    ex['youtube_url'],
            'youtube_title':  ex['youtube_title'],
            'description':    ex['description'],
        }
        for ex_id in ex_ids[:limit]
        if (ex := exercises_by_id.get(ex_id))
    ]
