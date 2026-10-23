"""
後端壓力測試腳本 — 量化正式 WSGI server 部署前後的併發承載能力（QPS／延遲）。

用法：
    # 量測並存成 JSON（部署前後各跑一次，label 分別取名）
    python load_test.py --label runserver --out loadtest_runserver.json
    python load_test.py --label gunicorn  --out loadtest_gunicorn.json

    # 對照兩次結果
    python load_test.py --compare loadtest_runserver.json loadtest_gunicorn.json

    # 延遲測試：每個端點循序（單一連線）打固定 100 次，量單次請求的延遲分布
    python load_test.py --fixed 100 --label latency --out loadtest_latency.json

測試端點（刻意不測 /api/agent：每次呼叫都會花 OpenAI 費用，且瓶頸在外部 LLM，不在 server）：
    health   GET  /api/health           — 最輕量，只驗證 DB 連線，量 server 本身的上限
    history  GET  /api/posture/history  — Token 驗證＋DB 查詢＋序列化，代表前端一般查詢
    posture  POST /api/posture          — schema 驗證＋TensorFlow 推論＋DB 寫入，最重的真實請求

每個「端點 × 併發數」組合是封閉迴圈測試：N 個 thread 在 duration 秒內不斷送請求，
一個回來才送下一個。統計值：請求次數、成功 QPS、延遲平均／標準差／最小／最大／p50／p95／p99、
錯誤率（依 HTTP 狀態碼／連線例外分類）、請求與回應封包大小（HTTP body 位元組數）。

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


def run_case(send, concurrency, duration=None, count=None):
    """duration：封閉迴圈跑滿這麼多秒；count：每個 thread 剛好送這麼多次（延遲測試用）。"""
    latencies, errors = [], Counter()
    req_bytes, resp_bytes = [], []
    lock = threading.Lock()
    deadline = time.perf_counter() + duration if duration else None

    def worker():
        s = requests.Session()
        local_lat, local_err, local_req, local_resp = [], Counter(), [], []
        sent = 0
        while (deadline and time.perf_counter() < deadline) or (count and sent < count):
            sent += 1
            t0 = time.perf_counter()
            try:
                r = send(s)
                err = f'HTTP {r.status_code}' if r.status_code >= 400 else None
            except requests.RequestException as e:
                err = type(e).__name__
            if err:
                local_err[err] += 1
            else:
                local_lat.append(time.perf_counter() - t0)
                local_req.append(len(r.request.body or b''))
                local_resp.append(len(r.content))
        with lock:
            latencies.extend(local_lat)
            errors.update(local_err)
            req_bytes.extend(local_req)
            resp_bytes.extend(local_resp)

    threads = [threading.Thread(target=worker) for _ in range(concurrency)]
    t_start = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.perf_counter() - t_start

    n_err = sum(errors.values())
    total = len(latencies) + n_err
    nan = float('nan')
    if len(latencies) >= 2:
        q = statistics.quantiles(latencies, n=100)
        p50, p95, p99 = q[49], q[94], q[98]
        mean, std = statistics.mean(latencies), statistics.stdev(latencies)
        lo, hi = min(latencies), max(latencies)
    else:
        p50 = p95 = p99 = mean = std = lo = hi = nan

    def ms(v):
        return round(v * 1000, 1)

    return {
        'concurrency':    concurrency,
        'requests':       total,
        'ok':             len(latencies),
        'qps':            round(len(latencies) / elapsed, 1),
        'mean_ms':        ms(mean),
        'std_ms':         ms(std),
        'min_ms':         ms(lo),
        'max_ms':         ms(hi),
        'p50_ms':         ms(p50),
        'p95_ms':         ms(p95),
        'p99_ms':         ms(p99),
        'req_bytes_avg':  round(statistics.mean(req_bytes)) if req_bytes else 0,
        'resp_bytes_avg': round(statistics.mean(resp_bytes)) if resp_bytes else 0,
        'error_rate':     round(n_err / total * 100, 2) if total else 0.0,
        'errors':         dict(errors),
    }


def print_table(label, results):
    print(f'\n=== {label} ===')
    print(f'{"endpoint":<9}{"conc":>5}{"n":>7}{"QPS":>8}{"mean":>8}{"std":>8}{"min":>8}{"max":>8}'
          f'{"p95":>8}{"req B":>7}{"resp B":>8}{"err%":>7}   （延遲單位 ms，封包單位 bytes）')
    for ep, rows in results.items():
        for r in rows:
            print(f'{ep:<9}{r["concurrency"]:>5}{r["requests"]:>7}{r["qps"]:>8}{r["mean_ms"]:>8}'
                  f'{r["std_ms"]:>8}{r["min_ms"]:>8}{r["max_ms"]:>8}{r["p95_ms"]:>8}'
                  f'{r["req_bytes_avg"]:>7}{r["resp_bytes_avg"]:>8}{r["error_rate"]:>7}')


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
    p.add_argument('--endpoints', default='health,posture,history',
                   help='依序測試；posture 排在 history 前面，history 才有資料可查')
    p.add_argument('--concurrency', default='1,10,30,50')
    p.add_argument('--duration', type=float, default=15, help='每個組合的測試秒數')
    p.add_argument('--fixed', type=int, metavar='N',
                   help='延遲測試：單一連線、每個端點循序送剛好 N 次（忽略 --concurrency／--duration）')
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
    levels = [1] if args.fixed else [int(c) for c in args.concurrency.split(',')]
    results = {}
    for ep in args.endpoints.split(','):
        send = build_request(ep, base, token)
        send(requests.Session())  # 暖機（第一次請求可能觸發 lazy import／模型載入）
        results[ep] = []
        for c in levels:
            r = run_case(send, c, count=args.fixed) if args.fixed else run_case(send, c, duration=args.duration)
            results[ep].append(r)
            print(f'  {ep} c={c} n={r["requests"]}: {r["qps"]} QPS, mean {r["mean_ms"]}±{r["std_ms"]} ms, '
                  f'p95 {r["p95_ms"]} ms, err {r["error_rate"]}%'
                  + (f' {r["errors"]}' if r['errors'] else ''), flush=True)

    print_table(args.label, results)
    if args.out:
        with open(args.out, 'w', encoding='utf-8') as f:
            json.dump({'label': args.label, 'base_url': base,
                       'mode': f'fixed {args.fixed}' if args.fixed else f'duration {args.duration}s',
                       'results': results}, f, ensure_ascii=False, indent=2)
        print(f'\n結果已存到 {args.out}')

    print('\n清除壓測資料（loadtest_bot 帳號及其坐姿／通知紀錄）：')
    print('  docker compose exec django python manage.py shell -c '
          f'"from api.models import User; User.objects.filter(username=\'{LOADTEST_USER}\').delete()"')


if __name__ == '__main__':
    main()
