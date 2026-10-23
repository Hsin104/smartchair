"""
Physio Agent 同步 vs 非同步壓力測試：模擬 N 個使用者「同一瞬間」一起問 AI。

前提：django 與 agent-worker 都要設定 AGENT_FAKE_LATENCY_SECONDS（例如 10），
讓 Agent 不真的呼叫 OpenAI、改成固定等待這麼多秒，才能測上千人而不產生費用：
    docker compose -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.bench.yml up -d django agent-worker
（docker-compose.override.yml 只有開發機有；其他機器拿掉那個 -f 即可）

用法：
    python benchmark_agent.py --mode sync  --users 1000 --out agent_sync.json
    python benchmark_agent.py --mode async --users 1000 --out agent_async.json

sync ：每個使用者呼叫舊的 POST /api/agent，一直等到回應（App 的 timeout 是 90 秒）
async：每個使用者呼叫 POST /api/agent/jobs 拿到任務編號，之後每 2 秒查一次 GET /api/agent/jobs/<id>，
       直到 done／failed 或超過 90 秒

統計：送出回應時間（async 才有意義）、從送出到拿到 AI 結果的完成時間（平均／標準差／最小／最大／p95）、
     90 秒內完成的人數、失敗原因分類。
"""

import argparse
import json
import statistics
import threading
import time
from collections import Counter

import requests

BENCH_USER = 'agent_bench_bot'
BENCH_PASS = 'AgentBench#2026'
CLIENT_TIMEOUT = 90     # 與 App 的 AI 請求 timeout 相同
POLL_INTERVAL = 2


def get_token(base):
    requests.post(f'{base}/api/register', json={'username': BENCH_USER, 'password': BENCH_PASS}, timeout=10)
    r = requests.post(f'{base}/api/login', json={'username': BENCH_USER, 'password': BENCH_PASS}, timeout=10)
    r.raise_for_status()
    return r.json()['token']


def one_user_sync(base, headers, out):
    s = requests.Session()
    t0 = time.perf_counter()
    try:
        r = s.post(f'{base}/api/agent', headers=headers, json={'posture': 'forward'}, timeout=CLIENT_TIMEOUT)
        if r.status_code == 200:
            out.append(('ok', None, time.perf_counter() - t0))
        else:
            out.append(('fail', f'HTTP {r.status_code}', time.perf_counter() - t0))
    except requests.Timeout:
        out.append(('fail', f'超過 {CLIENT_TIMEOUT} 秒未回應', time.perf_counter() - t0))
    except requests.RequestException as e:
        out.append(('fail', type(e).__name__, time.perf_counter() - t0))


def one_user_async(base, headers, out):
    s = requests.Session()
    t0 = time.perf_counter()
    try:
        r = s.post(f'{base}/api/agent/jobs', headers=headers, json={'posture': 'forward'}, timeout=CLIENT_TIMEOUT)
        submit = time.perf_counter() - t0
        if r.status_code != 202:
            out.append(('fail', f'送出 HTTP {r.status_code}', submit, submit))
            return
        url = base + r.json()['poll_url']
        while time.perf_counter() - t0 < CLIENT_TIMEOUT:
            time.sleep(POLL_INTERVAL)
            d = s.get(url, headers=headers, timeout=30).json()
            if d['status'] == 'done':
                out.append(('ok', None, submit, time.perf_counter() - t0))
                return
            if d['status'] == 'failed':
                out.append(('fail', d.get('error', 'failed')[:40], submit, time.perf_counter() - t0))
                return
        out.append(('fail', f'超過 {CLIENT_TIMEOUT} 秒未完成', submit, time.perf_counter() - t0))
    except requests.RequestException as e:
        out.append(('fail', type(e).__name__, None, time.perf_counter() - t0))


def stats(values, unit='s'):
    """values 單位為秒；unit='ms' 時換算成毫秒後再統計，避免先四捨五入損失精度。"""
    if unit == 'ms':
        values = [v * 1000 for v in values]
    if len(values) < 2:
        return {'n': len(values)}
    q = statistics.quantiles(values, n=100)
    return {
        'n':           len(values),
        f'mean_{unit}': round(statistics.mean(values), 2),
        f'std_{unit}':  round(statistics.stdev(values), 2),
        f'min_{unit}':  round(min(values), 2),
        f'max_{unit}':  round(max(values), 2),
        f'p95_{unit}':  round(q[94], 2),
    }


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--base-url', default='http://localhost:8000')
    p.add_argument('--mode', choices=['sync', 'async'], required=True)
    p.add_argument('--users', type=int, default=1000)
    p.add_argument('--out')
    args = p.parse_args()

    base = args.base_url.rstrip('/')
    headers = {'Authorization': f'Token {get_token(base)}'}
    target = one_user_sync if args.mode == 'sync' else one_user_async

    out = []
    threads = [threading.Thread(target=target, args=(base, headers, out)) for _ in range(args.users)]
    t_start = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = time.perf_counter() - t_start

    ok = [r for r in out if r[0] == 'ok']
    fails = Counter(r[1] for r in out if r[0] == 'fail')
    result = {
        'mode':            args.mode,
        'users':           args.users,
        'completed_in_90s': len(ok),
        'success_rate':    round(len(ok) / args.users * 100, 1),
        'wall_time_s':     round(wall, 1),
        'failures':        dict(fails),
        'completion_time': stats([r[-1] for r in ok]),
    }
    if args.mode == 'async':
        result['submit_time'] = stats([r[2] for r in out if r[2] is not None], unit='ms')

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.out:
        with open(args.out, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

    print('\n清除測試資料：docker compose exec django python manage.py shell -c '
          f'"from api.models import User; User.objects.filter(username=\'{BENCH_USER}\').delete()"')


if __name__ == '__main__':
    main()
