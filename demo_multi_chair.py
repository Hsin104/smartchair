"""
多張椅子展示：兩位使用者各坐一張椅子，兩張椅子同時送感測資料，驗證資料、通知、馬達指令都不會混在一起。

只在本機執行（本機 Docker 的 API＋本機 mosquitto），不會碰到雲端 broker 與真實椅子：
    python demo_multi_chair.py            # 執行展示，資料保留（可接著開 App 或 admin 看）
    python demo_multi_chair.py --cleanup  # 刪除展示用的使用者與椅子

情境：
    demo_alice 坐 chair_A1B2C3，身體左傾
    demo_bob   坐 chair_D4E5F6，頭部前傾
兩張椅子都用新韌體格式（chair/{device_id}/pressure，demo/esp32_spec_v2.md），每 0.5 秒交錯送出。
"""

import argparse
import json
import sys
import threading
import time
from collections import Counter

import paho.mqtt.client as mqtt
import requests

BASE = 'http://localhost:8000/api'
BROKER = ('localhost', 1883)
PASSWORD = 'DemoChair#2026'

CHAIRS = [
    # (使用者, device_id, 模擬坐姿, ESP32 pose.label)
    ('demo_alice', 'chair_A1B2C3', 'left', 'left_lean'),
    ('demo_bob',   'chair_D4E5F6', 'forward', 'forward_lean'),
]

# 椅墊 8 點＋椅背 3 點（norm 0~100），順序同 demo/MQTT資料說明.md：S1~S8 椅墊、S9~S11 椅背
NORM = {
    'left':    [15, 14, 14, 39, 36, 65, 65, 70, 18, 21, 21],
    'forward': [11, 29, 65, 10, 63, 65, 29, 11, 5, 6, 6],
}
ROUNDS = 12   # 後端連續 10 筆相同才確認坐姿改變，送 12 輪確保觸發通知

results = []


def check(name, ok, detail=''):
    results.append(ok)
    print(f'  [{"PASS" if ok else "FAIL"}] {name}' + (f'  — {detail}' if detail else ''))


def login(username):
    requests.post(f'{BASE}/register', json={'username': username, 'password': PASSWORD}, timeout=10)
    r = requests.post(f'{BASE}/login', json={'username': username, 'password': PASSWORD}, timeout=10)
    r.raise_for_status()
    return {'Authorization': f'Token {r.json()["token"]}'}


def cleanup():
    print('刪除展示用的使用者與椅子（只動 demo_ 開頭的帳號與這兩張椅子）')
    import os
    import django
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smartchair_backend.settings')
    django.setup()
    from api.models import Chair, User
    print('  使用者：', User.objects.filter(username__in=[c[0] for c in CHAIRS]).delete())
    print('  椅子：', Chair.objects.filter(device_id__in=[c[1] for c in CHAIRS]).delete())


def main():
    print('=== 多張椅子展示 ===\n')
    if not requests.get(f'{BASE}/health', timeout=5).ok:
        sys.exit('本機後端沒有回應，請先啟動 docker compose')

    print('[1] 兩位使用者各自入座不同的椅子')
    headers = {}
    for user, device_id, _, _ in CHAIRS:
        headers[user] = login(user)
        r = requests.post(f'{BASE}/chair/checkin', headers=headers[user], json={'device_id': device_id}, timeout=10)
        print(f'  {user} → {r.json()}')

    before = {user: len(requests.get(f'{BASE}/notification/history', headers=headers[user], timeout=10)
                       .json()['notifications']) for user, *_ in CHAIRS}

    # 攔截本機 broker 上所有椅子的馬達指令，等一下確認只送到正確的椅子
    motor_cmds = []
    listener = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id='demo-listener')
    listener.on_message = lambda c, u, m: motor_cmds.append(m.topic)
    listener.connect(*BROKER)
    listener.subscribe('chair/+/vibration/cmd')
    listener.loop_start()

    print(f'\n[2] 兩張椅子同時送感測資料（新格式 chair/{{device_id}}/pressure，每 0.5 秒交錯，共 {ROUNDS} 輪）')
    pub = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id='demo-chairs')
    pub.connect(*BROKER)
    pub.loop_start()
    for seq in range(ROUNDS):
        for _, device_id, posture, label in CHAIRS:
            payload = {'device_id': device_id, 'ts': seq, 'seq': seq, 'type': 'change',
                       'norm': NORM[posture], 'pose': {'label': label}}
            pub.publish(f'chair/{device_id}/pressure', json.dumps(payload), qos=1)
        time.sleep(0.5)
    time.sleep(3)   # 等後端處理完
    pub.loop_stop()

    print('\n[3] GET /api/chairs：後端自動登記了兩張椅子，各自知道誰坐在上面')
    chairs = {c['device_id']: c for c in requests.get(f'{BASE}/chairs', timeout=10).json()['chairs']}
    for user, device_id, _, _ in CHAIRS:
        c = chairs.get(device_id, {})
        print(f'  {device_id}：使用者 {c.get("username")}，在線 {c.get("online")}')
        check(f'{device_id} 已自動登記且坐的是 {user}', c.get('username') == user)

    print('\n[4] 每位使用者的坐姿紀錄只來自自己的椅子')
    for user, device_id, posture, _ in CHAIRS:
        hist = requests.get(f'{BASE}/posture/history', params={'limit': ROUNDS}, headers=headers[user],
                            timeout=10).json()
        counts = Counter(h['posture'] for h in hist)
        print(f'  {user}：最近 {len(hist)} 筆 {dict(counts)}')
        check(f'{user} 收到 {ROUNDS} 筆紀錄', len(hist) == ROUNDS, f'{len(hist)} 筆')
        check(f'{user} 的紀錄都是 {posture}（沒有混到另一張椅子的資料）',
              counts.get(posture, 0) == len(hist), str(dict(counts)))

    print('\n[5] 坐姿提醒通知各自產生')
    for user, _, posture, _ in CHAIRS:
        notes = requests.get(f'{BASE}/notification/history', headers=headers[user], timeout=10).json()['notifications']
        new = len(notes) - before[user]
        print(f'  {user}：新增 {new} 則 {[n["message"] for n in notes[:new]]}')
        check(f'{user} 新增 1 則提醒', new == 1, f'{new} 則')

    print('\n[6] 手動觸發馬達（POST /api/motor/trigger）：指令只送到觸發者坐的那張椅子')
    motor_cmds.clear()
    r = requests.post(f'{BASE}/motor/trigger', headers=headers['demo_alice'], json={'posture': 'left'}, timeout=10).json()
    time.sleep(1)
    listener.loop_stop()
    print(f'  demo_alice 觸發 → 回應 device_id={r.get("device_id")} 馬達 {r.get("motors")}；broker 收到：{motor_cmds}')
    check('指令只送到 chair/chair_A1B2C3/vibration/cmd',
          motor_cmds == ['chair/chair_A1B2C3/vibration/cmd'], str(motor_cmds))

    print(f'\n=== 結果：{sum(results)}/{len(results)} 項通過 ===')
    print('資料已保留，可開 App 或 Django admin 查看；刪除請執行：python demo_multi_chair.py --cleanup')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    p = argparse.ArgumentParser()
    p.add_argument('--cleanup', action='store_true')
    if p.parse_args().cleanup:
        cleanup()
    else:
        main()
