"""
坐姿 → 震動馬達對應表（M1=左手軸, M2=右手軸, M3=左腰, M4=右腰）。

供 views.py（POST /api/motor/trigger，前端直接觸發）與
mcp_server.py（trigger_vibration MCP 工具，Agent 決策觸發）共用，
避免同一份對應表在兩處各自維護。
"""

MOTOR_MAP = {
    'forward':   ['M1', 'M2'],              # 前傾：左右手軸提醒抬頭
    'recline':   ['M3', 'M4'],              # 後仰：左右腰部提醒坐直
    'left':      ['M1', 'M3'],              # 左傾：左手軸+左腰（同側提醒）
    'right':     ['M2', 'M4'],              # 右傾：右手軸+右腰（同側提醒）
    'sedentary': ['M1', 'M2', 'M3', 'M4'], # 久坐：全部馬達提醒起身
    'normal':    [],
    'empty':     [],
}
