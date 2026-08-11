"""
椅子硬體感測資料轉換層。

真實韌體（蕭芷萱 Agent Quickstart, 2026/08）payload 格式：
    {"device_id": "chair_01", "ts": 123, "raw": [11筆], "norm": [11筆]}

11 個元素為椅墊 8 點 + 椅背 3 點合併陣列（舊格式椅墊/椅背是分開的 8 點陣列
+ 具名 back 字典，兩者並存以維持向下相容）。

椅墊 0~7 索引對應關係已與組員確認（見 SEAT_INDEX 註解）。
椅背 8~9~10 索引對應 spine_upper/mid/lower 為本專案假設的接續順序，
尚未經組員書面確認 —— 實機測試時務必先用韌體文件裡的
`--mode listen` 印出原始陣列核對，如有出入只需調整 BACK_INDEX。
"""

# 椅墊 8 個感測器在 norm/raw 陣列中的索引（已與組員確認）
#     [左後 S8][中後 S4][右後 S1]
#     [左中 S7][中中 S5][右中 S2]
#     [左前 S6]         [右前 S3]
SEAT_INDEX = {
    'right_back':   0,  # S1
    'right_mid':    1,  # S2
    'right_front':  2,  # S3
    'center_back':  3,  # S4
    'center_front': 4,  # S5
    'left_front':   5,  # S6
    'left_mid':     6,  # S7
    'left_back':    7,  # S8
}

# 椅背 3 個感測器索引 —【假設】接續在椅墊之後，尚待與組員書面確認實際順序
BACK_INDEX = {
    'spine_upper': 8,
    'spine_mid':   9,
    'spine_lower': 10,
}


def parse_esp32_payload(payload: dict):
    """
    將韌體 payload 轉為後端內部使用的 (seat_pressure_data, back_pressure_data) 具名字典。

    依序嘗試三種格式，向下相容舊測試資料：
      1. norm/raw 陣列有 11 個元素 → 椅墊 0~7 + 椅背 8~10（真實硬體，2026/08 起）
      2. norm/raw 陣列只有 8 個元素 → 只有椅墊，椅背改讀 payload['back']（舊格式）
      3. 陣列不存在 → 直接讀 payload['seat'] / payload['back'] 具名字典（本機模擬器）
    """
    arr = payload.get('norm') or payload.get('raw') or []

    if len(arr) >= 11:
        seat_data = {k: arr[i] for k, i in SEAT_INDEX.items()}
        back_data = {k: arr[i] for k, i in BACK_INDEX.items()}
    elif len(arr) >= 8:
        seat_data = {k: arr[i] for k, i in SEAT_INDEX.items()}
        back_data = payload.get('back') or {}
    else:
        seat_data = payload.get('seat') or {}
        back_data = payload.get('back') or {}

    return seat_data, back_data


def total_pressure(payload: dict) -> float:
    """判斷是否有人就坐用的總壓力（norm/raw 陣列絕對值總和）。"""
    arr = payload.get('norm') or payload.get('raw') or []
    return sum(abs(v) for v in arr)
