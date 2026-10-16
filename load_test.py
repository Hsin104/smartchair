"""
後端壓力測試腳本 — 量化正式 WSGI server 部署前後的併發承載能力（QPS／延遲）。

用法：
    # 量測並存成 JSON（部署前後各跑一次，label 分別取名）
    python load_test.py --label runserver --out loadtest_runserver.json
    python load_test.py --label gunicorn  --out loadtest_gunicorn.json

    # 對照兩次結果
    python load_test.py --compare loadtest_runserver.json loadtest_gunicorn.json

測試端點（刻意不測 /api/agent：每次呼叫都會花 OpenAI 費用，且瓶頸在外部 LLM，不在 server）：
    health   GET  /api/health           — 最輕量，只驗證 DB 連線，量 server 本身的上限
    history  GET  /api/posture/history  — Token 驗證＋DB 查詢＋序列化，代表前端一般查詢
    posture  POST /api/posture          — schema 驗證＋TensorFlow 推論＋DB 寫入，最重的真實請求

每個「端點 × 併發數」組合是封閉迴圈測試：N 個 thread 在 duration 秒內不斷送請求，
一個回來才送下一個，統計成功 QPS、延遲 p50/p95/p99、錯誤率。

注意：posture 會把紀錄寫進「目前 active ChairSession 的使用者」名下（見 views.posture_create），
所以有人正在使用椅子時腳本會直接中止，避免壓測資料污染真實使用者紀錄。
壓測資料都在 loadtest_bot 帳號底下，結束後可用腳本最後印出的指令一鍵刪除。
"""

import argparse
import json
import random
import statistics
import sys
import threading
import time
from collections import Counter

import requests

LOADTEST_USER = 'loadtest_bot'
LOADTEST_PASS = 'LoadTest#2026'

SEAT_KEYS = [
    'left_back', 'left_mid', 'left_front',
    'center_back', 'center_front',
    'right_back', 'right_mid', 'right_front',
]


def _random_seat():
    return {k: random.randint(200, 800) for k in SEAT_KEYS}


def get_token(base):
    requests.post(f'{base}/api/register', json={
        'username': LOADTEST_USER, 'password': LOADTEST_PASS,
        'email': 'loadtest_bot@example.com',
    }, timeout=10)  # 已存在會回 400，不影響
    r = requests.post(f'{base}/api/login', json={
        'username': LOADTEST_USER, 'password': LOADTEST_PASS,
    }, timeout=10)
    r.raise_for_status()
    return r.json()['token']


def build_request(endpoint, base, token):
    auth = {'Authorization': f'Token {token}'}
    if endpoint == 'health':
        return lambda s: s.get(f'{base}/api/health', timeout=30)
    if endpoint == 'history':
        return lambda s: s.get(f'{base}/api/posture/history?limit=20', headers=auth, timeout=30)
    if endpoint == 'posture':
        return lambda s: s.post(f'{base}/api/posture', headers=auth,
                                json={'seat_pressure_data': _random_seat()}, timeout=30)
    raise ValueError(endpoint)


def run_case(send, concurrency, duration):
    latencies, errors = [], Counter()
    lock = threading.Lock()
    deadline = time.perf_counter() + duration

    def worker():
        s = requests.Session()
        local_lat, local_err = [], Counter()
        while time.perf_counter() < deadline:
            t0 = time.perf_counter()
            try:
                code = send(s).status_code
                err = f'HTTP {code}' if code >= 400 else None
            except requests.RequestException as e:
                err = type(e).__name__
            if err:
                local_err[err] += 1
            else:
                local_lat.append(time.perf_counter() - t0)
        with lock:
            latencies.extend(local_lat)
            errors.update(local_err)

    threads = [threading.Thread(target=worker) for _ in range(concurrency)]
    t_start = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.perf_counter() - t_start

    n_err = sum(errors.values())
    total = len(latencies) + n_err
    if latencies:
        q = statistics.quantiles(latencies, n=100)
        p50, p95, p99 = q[49], q[94], q[98]
    else:
        p50 = p95 = p99 = float('nan')
    return {
        'concurrency': concurrency,
        'requests':    total,
        'ok':          len(latencies),
        'qps':         round(len(latencies) / elapsed, 1),
        'p50_ms':      round(p50 * 1000, 1),
        'p95_ms':      round(p95 * 1000, 1),
        'p99_ms':      round(p99 * 1000, 1),
        'error_rate':  round(n_err / total * 100, 2) if total else 0.0,
        'errors':      dict(errors),
    }


def print_table(label, results):
    print(f'\n=== {label} ===')
    print(f'{"endpoint":<9}{"conc":>6}{"QPS":>9}{"p50(ms)":>10}{"p95(ms)":>10}{"p99(ms)":>10}{"err%":>8}')
    for ep, rows in results.items():
        for r in rows:
            print(f'{ep:<9}{r["concurrency"]:>6}{r["qps"]:>9}{r["p50_ms"]:>10}'
                  f'{r["p95_ms"]:>10}{r["p99_ms"]:>10}{r["error_rate"]:>8}')


def compare(path_a, path_b):
    a, b = (json.load(open(p, encoding='utf-8')) for p in (path_a, path_b))
    print(f'\n=== {a["label"]}  →  {b["label"]} ===')
    print(f'{"endpoint":<9}{"conc":>6}{"QPS":>20}{"p95(ms)":>22}{"err%":>16}')
    for ep, rows_a in a['results'].items():
        rows_b = {r['concurrency']: r for r in b['results'].get(ep, [])}
        for ra in rows_a:
            rb = rows_b.get(ra['concurrency'])
            if not rb:
                continue
            print(f'{ep:<9}{ra["concurrency"]:>6}'
                  f'{ra["qps"]:>9} → {rb["qps"]:<8}'
                  f'{ra["p95_ms"]:>10} → {rb["p95_ms"]:<9}'
                  f'{ra["error_rate"]:>6} → {rb["error_rate"]:<6}')


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--base-url', default='http://localhost:8000')
    p.add_argument('--endpoints', default='health,history,posture')
    p.add_argument('--concurrency', default='1,10,30,50')
    p.add_argument('--duration', type=float, default=15, help='每個組合的測試秒數')
    p.add_argument('--label', default='run')
    p.add_argument('--out')
    p.add_argument('--compare', nargs=2, metavar=('BEFORE', 'AFTER'))
    args = p.parse_args()

    if args.compare:
        compare(*args.compare)
        return

    base = args.base_url.rstrip('/')
    status = requests.get(f'{base}/api/chair/status', timeout=10).json()
    if status.get('active'):
        sys.exit(f'中止：{status["username"]} 正在使用椅子，posture 壓測資料會寫進該使用者名下。'
                 f'請先 checkout 再測。')

    token = get_token(base)
    levels = [int(c) for c in args.concurrency.split(',')]
    results = {}
    for ep in args.endpoints.split(','):
        send = build_request(ep, base, token)
        send(requests.Session())  # 暖機（第一次請求可能觸發 lazy import／模型載入）
        results[ep] = []
        for c in levels:
            r = run_case(send, c, args.duration)
            results[ep].append(r)
            print(f'  {ep} c={c}: {r["qps"]} QPS, p95 {r["p95_ms"]} ms, err {r["error_rate"]}%'
                  + (f' {r["errors"]}' if r['errors'] else ''), flush=True)

    print_table(args.label, results)
    if args.out:
        with open(args.out, 'w', encoding='utf-8') as f:
            json.dump({'label': args.label, 'base_url': base, 'duration': args.duration,
                       'results': results}, f, ensure_ascii=False, indent=2)
        print(f'\n結果已存到 {args.out}')

    print('\n清除壓測資料（loadtest_bot 帳號及其坐姿／通知紀錄）：')
    print('  docker compose exec django python manage.py shell -c '
          f'"from api.models import User; User.objects.filter(username=\'{LOADTEST_USER}\').delete()"')


if __name__ == '__main__':
    main()
