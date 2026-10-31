"""
多張椅子＋個人校正展示（設計見 demo/calibration_design.md）

只在本機執行（本機 Docker 的 API＋本機 mosquitto），不會碰到雲端 broker 與真實椅子；
這支腳本同時扮演「新韌體的椅子」：送感測資料、收到校正指令時回報結果。
    python demo_multi_chair.py            # 執行展示，資料保留（可接著開 App 或 admin 看）
    python demo_multi_chair.py --record   # 錄影用：每一步停下來按 Enter 才繼續，校正時顯示每秒查詢結果
    python demo_multi_chair.py --cleanup  # 刪除展示用的使用者、椅子與保留的椅子設定

情境：
    demo_alice 坐 chair_A1B2C3：校正（椅子計算成功），之後身體左傾，最後換到 chair_G7H8I9 不用重新校正
    demo_bob   坐 chair_D4E5F6：第一次校正坐不穩（椅子回報失敗）、第二次椅子沒回應（改由後端計算），之後頭部前傾
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

ALICE, BOB = 'demo_alice', 'demo_bob'
CHAIR_A, CHAIR_B, CHAIR_C = 'chair_A1B2C3', 'chair_D4E5F6', 'chair_G7H8I9'

# 椅墊 8 點＋椅背 3 點（norm 0~100），順序同 demo/MQTT資料說明.md：S1~S8 椅墊、S9~S11 椅背
NORM = {
    'normal':  [52, 50, 44, 48, 42, 44, 50, 52, 25, 27, 27],
    'left':    [15, 14, 14, 39, 36, 65, 65, 70, 18, 21, 21],
    'forward': [11, 29, 65, 10, 63, 65, 29, 11, 5, 6, 6],
}
LABEL = {'normal': 'normal', 'left': 'left_lean', 'forward': 'forward_lean'}
ROUNDS = 12   # 後端連續 10 筆相同才確認坐姿改變，送 12 輪確保觸發通知

# 模擬椅子收到校正指令時怎麼回應：(device_id) → 依序使用的回應方式
CHAIR_BEHAVIOUR = {CHAIR_A: ['ok'], CHAIR_B: ['unstable', 'silent']}

RECORD = False
results = []
seen = {'cmd': [], 'config': {}, 'calibrate_cmds': []}


def check(name, ok, detail=''):
    results.append(ok)
    print(f'  [{"PASS" if ok else "FAIL"}] {name}' + (f'  — {detail}' if detail else ''))


def step(title):
    """每段展示的標題；錄影模式下先停住，講解完按 Enter 才繼續。"""
    if RECORD:
        input('\n（按 Enter 繼續）')
        print(f'\n{"═" * 60}\n{title}\n{"═" * 60}')
    else:
        print(f'\n{title}')


def login(username):
    requests.post(f'{BASE}/register', json={'username': username, 'password': PASSWORD}, timeout=10)
    r = requests.post(f'{BASE}/login', json={'username': username, 'password': PASSWORD}, timeout=10)
    r.raise_for_status()
    return {'Authorization': f'Token {r.json()["token"]}'}


def center(norm):
    """與 ESP32 相同的重心算法（S1~S8 座標加權）。"""
    pos = [(0.82, 0.18), (0.82, 0.42), (0.82, 0.72), (0.50, 0.18), (0.50, 0.72),
           (0.18, 0.72), (0.18, 0.42), (0.18, 0.18)]
    total = sum(norm[:8])
    return (round(sum(v * p[0] for v, p in zip(norm, pos)) / total, 4),
            round(sum(v * p[1] for v, p in zip(norm, pos)) / total, 4))


def make_chair_client():
    """模擬新韌體：送感測資料、收到 calibrate 指令後取樣 5 秒再回報。"""
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id='demo-chairs')

    def on_message(c, u, msg):
        if msg.topic.endswith('/vibration/cmd'):
            seen['cmd'].append(msg.topic)
        elif msg.topic.endswith('/config') and msg.payload:
            seen['config'][msg.topic.split('/')[1]] = json.loads(msg.payload)
        elif msg.topic.endswith('/calibration/cmd'):
            device_id = msg.topic.split('/')[1]
            cmd = json.loads(msg.payload)
            seen['calibrate_cmds'].append((device_id, cmd))
            queue = CHAIR_BEHAVIOUR.get(device_id) or []
            behaviour = queue.pop(0) if queue else 'silent'
            threading.Thread(target=reply_calibration, args=(c, device_id, cmd, behaviour), daemon=True).start()

    client.on_message = on_message
    client.connect(*BROKER)
    for topic in ('chair/+/vibration/cmd', 'chair/+/config', 'chair/+/calibration/cmd'):
        client.subscribe(topic)
    client.loop_start()
    return client


def reply_calibration(client, device_id, cmd, behaviour):
    if behaviour == 'silent':          # 舊韌體／離線：不回應，後端 10 秒後改用自己的資料計算
        return
    time.sleep(cmd['duration_s'])      # 椅子取樣 5 秒
    status_topic = f'chair/{device_id}/vibration/status'
    if behaviour == 'unstable':
        payload = {'event': 'calibration_failed', 'request_id': cmd['request_id'], 'reason': 'unstable'}
    else:
        nx, ny = center(NORM['normal'])
        payload = {'event': 'calibrated', 'request_id': cmd['request_id'], 'neutral_x': nx, 'neutral_y': ny,
                   'norm_avg': NORM['normal'], 'samples': 250}
    client.publish(status_topic, json.dumps(payload), qos=1)


def send(client, chairs_postures, rounds, interval=0.5):
    """chairs_postures：[(device_id, posture)]，每 interval 秒每張椅子各送一筆。"""
    for seq in range(rounds):
        for device_id, posture in chairs_postures:
            payload = {'device_id': device_id, 'ts': seq, 'seq': seq, 'type': 'change',
                       'norm': NORM[posture], 'pose': {'label': LABEL[posture]}}
            client.publish(f'chair/{device_id}/pressure', json.dumps(payload), qos=1)
        time.sleep(interval)


def wait_calibration(headers, timeout=20):
    start = time.time()
    while time.time() < start + timeout:
        d = requests.get(f'{BASE}/chair/calibration', headers=headers, timeout=10).json()
        if RECORD:
            print(f'  GET /chair/calibration（第 {time.time() - start:.0f} 秒）→ {d["status"]}')
        if d['status'] in ('done', 'failed'):
            return d
        time.sleep(1)
    return d


def cleanup():
    print('刪除展示用的使用者、椅子與保留的椅子設定')
    import os
    import django
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smartchair_backend.settings')
    django.setup()
    from api.models import Chair, User
    print('  使用者：', User.objects.filter(username__in=[ALICE, BOB]).delete())
    print('  椅子：', Chair.objects.filter(device_id__in=[CHAIR_A, CHAIR_B, CHAIR_C]).delete())
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id='demo-cleanup')
    c.connect(*BROKER)
    c.loop_start()
    for d in (CHAIR_A, CHAIR_B, CHAIR_C):   # 清掉 broker 保留的設定訊息（空 payload＋retain）
        c.publish(f'chair/{d}/config', b'', qos=1, retain=True)
    time.sleep(1)
    c.loop_stop()


def main():
    print('=== 多張椅子＋個人校正展示 ===\n')
    if not requests.get(f'{BASE}/health', timeout=5).ok:
        sys.exit('本機後端沒有回應，請先啟動 docker compose')
    chair = make_chair_client()
    headers = {ALICE: login(ALICE), BOB: login(BOB)}

    step('[1] 兩位使用者各自入座不同的椅子（還沒校正）')
    for user, device_id in ((ALICE, CHAIR_A), (BOB, CHAIR_B)):
        r = requests.post(f'{BASE}/chair/checkin', headers=headers[user], json={'device_id': device_id}, timeout=10).json()
        print(f'  {user} → {r}')
        check(f'{user} 入座回應 calibrated=false（App 應提示校正）', r.get('calibrated') is False)
    time.sleep(1)
    cfg = seen['config'].get(CHAIR_A, {})
    print(f'  {CHAIR_A} 收到設定：{cfg}')
    check('沒校正的人：椅子收到預設中立點，且設定不含帳號名稱',
          cfg.get('cmd') == 'reset_neutral' and 'user' not in cfg, f'來源 {cfg.get("source")}')

    step(f'[2] {ALICE} 校正：椅子取樣 5 秒後回報成功（正式流程）')
    send(chair, [(CHAIR_A, 'normal')], 2)
    r = requests.post(f'{BASE}/chair/calibration', headers=headers[ALICE], timeout=10)
    print(f'  POST /chair/calibration → HTTP {r.status_code} {r.json()}')
    d = wait_calibration(headers[ALICE])
    print(f'  結果：status={d["status"]} method={d.get("method")} 中立點=({d.get("calibration", {}).get("neutral_x")}, '
          f'{d.get("calibration", {}).get("neutral_y")})')
    check('由椅子計算完成（method=device）', d['status'] == 'done' and d.get('method') == 'device')
    time.sleep(1)
    cfg = seen['config'].get(CHAIR_A, {})
    check(f'{CHAIR_A} 收到 {ALICE} 的個人中立點（set_neutral，不含帳號名稱）',
          cfg.get('cmd') == 'set_neutral' and 'user' not in cfg
          and cfg.get('neutral_x') == d.get('calibration', {}).get('neutral_x'), str(cfg))

    step(f'[3] {BOB} 第一次校正：椅子回報坐不穩')
    r = requests.post(f'{BASE}/chair/calibration', headers=headers[BOB], timeout=10)
    print(f'  POST /chair/calibration → HTTP {r.status_code} {r.json()}')
    d = wait_calibration(headers[BOB])
    print(f'  結果：status={d["status"]} reason={d.get("reason")} 訊息：{d.get("message")}')
    check('校正失敗並顯示中文原因', d['status'] == 'failed' and d.get('reason') == 'unstable')

    step(f'[4] {BOB} 第二次校正：椅子沒回應（例如舊韌體），10 秒後改由後端計算')
    r = requests.post(f'{BASE}/chair/calibration', headers=headers[BOB], timeout=10)
    print(f'  POST /chair/calibration → HTTP {r.status_code} {r.json()}')
    for sec in range(1, 11):   # 期間椅子照常送資料，但不回應校正指令
        send(chair, [(CHAIR_B, 'normal')], 1, interval=1)
        if RECORD:
            d = requests.get(f'{BASE}/chair/calibration', headers=headers[BOB], timeout=10).json()
            print(f'  第 {sec} 秒：椅子沒回應校正，照常送感測資料 → {d["status"]}')
    d = wait_calibration(headers[BOB])
    print(f'  結果：status={d["status"]} method={d.get("method")}')
    check('改由後端計算完成（method=backend）', d['status'] == 'done' and d.get('method') == 'backend')

    before = {u: len(requests.get(f'{BASE}/notification/history', headers=headers[u], timeout=10)
                     .json()['notifications']) for u in (ALICE, BOB)}

    step(f'[5] 兩張椅子同時送感測資料（共 {ROUNDS} 輪）：{ALICE} 左傾、{BOB} 前傾')
    send(chair, [(CHAIR_A, 'left'), (CHAIR_B, 'forward')], ROUNDS)
    time.sleep(3)
    for user, posture in ((ALICE, 'left'), (BOB, 'forward')):
        hist = requests.get(f'{BASE}/posture/history', params={'limit': ROUNDS}, headers=headers[user], timeout=10).json()
        counts = Counter(h['posture'] for h in hist)
        print(f'  {user}：最近 {len(hist)} 筆 {dict(counts)}')
        check(f'{user} 的紀錄都是 {posture}（沒有混到另一張椅子）', counts.get(posture, 0) == ROUNDS, str(dict(counts)))
        notes = requests.get(f'{BASE}/notification/history', headers=headers[user], timeout=10).json()['notifications']
        new = notes[:len(notes) - before[user]]
        check(f'{user} 新增 1 則坐姿提醒（kind=posture）', len(new) == 1 and new[0]['kind'] == 'posture',
              str([(n['kind'], n['message']) for n in new]))

    step('[6] GET /api/chairs')
    chairs = {c['device_id']: c for c in requests.get(f'{BASE}/chairs', timeout=10).json()['chairs']}
    for user, device_id in ((ALICE, CHAIR_A), (BOB, CHAIR_B)):
        c = chairs.get(device_id, {})
        print(f'  {device_id}：使用者 {c.get("username")}，在線 {c.get("online")}')
        check(f'{device_id} 坐的是 {user}', c.get('username') == user)

    step('[7] 手動觸發馬達：指令只送到觸發者坐的那張椅子')
    seen['cmd'].clear()
    requests.post(f'{BASE}/motor/trigger', headers=headers[ALICE], json={'posture': 'left'}, timeout=10)
    time.sleep(1)
    check(f'指令只送到 chair/{CHAIR_A}/vibration/cmd', seen['cmd'] == [f'chair/{CHAIR_A}/vibration/cmd'], str(seen['cmd']))

    step(f'[8] 校正跟著人走：{ALICE} 換到 {CHAIR_C}，不重新校正')
    alice_cfg = seen['config'][CHAIR_A]
    r = requests.post(f'{BASE}/chair/checkin', headers=headers[ALICE], json={'device_id': CHAIR_C}, timeout=10).json()
    time.sleep(1)
    new_cfg, old_cfg = seen['config'].get(CHAIR_C, {}), seen['config'].get(CHAIR_A, {})
    print(f'  checkin → calibrated={r.get("calibrated")}')
    print(f'  {CHAIR_C} 收到：{new_cfg}')
    print(f'  {CHAIR_A} 收到：{old_cfg}')
    check('入座回應 calibrated=true（App 不再提示校正）', r.get('calibrated') is True)
    check(f'{CHAIR_C} 自動收到 {ALICE} 的中立點',
          new_cfg.get('cmd') == 'set_neutral' and (new_cfg.get('neutral_x'), new_cfg.get('neutral_y'))
          == (alice_cfg.get('neutral_x'), alice_cfg.get('neutral_y')))
    check(f'{CHAIR_A} 恢復預設中立點', old_cfg.get('cmd') == 'reset_neutral')

    chair.loop_stop()
    print(f'\n=== 結果：{sum(results)}/{len(results)} 項通過 ===')
    print('自動離座（10 分鐘）在 test_full_pipeline.py 以模擬時間驗證；刪除展示資料：python demo_multi_chair.py --cleanup')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    p = argparse.ArgumentParser()
    p.add_argument('--cleanup', action='store_true')
    p.add_argument('--record', action='store_true', help='錄影用：每一步暫停')
    args = p.parse_args()
    RECORD = args.record
    if args.cleanup:
        cleanup()
    else:
        main()
