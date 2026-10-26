"""
Physio Agent 防幻覺自動評測（指標定義見 eval/README.md）

用法：
    python eval/run_eval.py                         # 全部 36 題 × 3 次，打本機 http://localhost:8000
    python eval/run_eval.py --ids P01,R01,T01 --repeat 1   # 只跑指定題目（試跑用）
    python eval/run_eval.py --base-url https://<ngrok網域>  # 打正式環境

流程：每題送 POST /api/agent/jobs，輪詢 GET /api/agent/jobs/<id> 拿到回覆全文與 ReAct 步驟，
逐題判定後彙整指標。原始回覆全部存進 eval/results/，供人工複核。
會真的呼叫 OpenAI（gpt-4o-mini），36 題 × 3 次約 108 次呼叫。
"""

import argparse
import json
import re
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
TESTSET = HERE / 'hallucination_testset.json'
RESULTS_DIR = HERE / 'results'

EVAL_USER = 'eval_bot'
EVAL_PASS = 'EvalBot#2026'
JOB_TIMEOUT = 120
POLL_INTERVAL = 2

SOURCE_RE = re.compile(r'來源：([\w\-]+\.txt)')
NUMBER_RE = re.compile(r'\d+(?:\.\d+)?')
# 條列編號（行首的「1.」「2、」「(3)」）不算回覆內容裡的數字
LIST_NUMBER_RE = re.compile(r'^\s*[\(（]?\d+[\.\)、）]', re.MULTILINE)
# 拒答判定：規則要求的固定句是「根據目前知識庫，我無法回答此問題，…」，但模型常會改幾個字
# （例如「根據目前的知識庫，我無法回答有關保健食品的問題」），以「知識庫…無法回答」判定
REFUSAL_RE = re.compile(r'知識庫[^。\n]{0,12}無法回答')


# ── 呼叫 Agent ────────────────────────────────────────────────────────────────

def login(base, headers):
    requests.post(f'{base}/api/register', headers=headers,
                  json={'username': EVAL_USER, 'password': EVAL_PASS, 'height': 170, 'weight': 65}, timeout=15)
    r = requests.post(f'{base}/api/login', headers=headers,
                      json={'username': EVAL_USER, 'password': EVAL_PASS}, timeout=15)
    r.raise_for_status()
    return {**headers, 'Authorization': f'Token {r.json()["token"]}'}


def ask_agent(base, headers, q):
    t0 = time.time()
    r = requests.post(f'{base}/api/agent/jobs', headers=headers,
                      json={'posture': q['posture'], 'user_message': q['user_message']}, timeout=30)
    if r.status_code != 202:
        return {'status': 'error', 'error': f'送出失敗 HTTP {r.status_code}: {r.text[:200]}', 'seconds': 0}
    url = base + r.json()['poll_url']
    while time.time() - t0 < JOB_TIMEOUT:
        time.sleep(POLL_INTERVAL)
        d = requests.get(url, headers=headers, timeout=30).json()
        if d['status'] in ('done', 'failed'):
            return {'status': d['status'], 'advice': d.get('advice', ''), 'steps': d.get('steps', []),
                    'error': d.get('error', ''), 'seconds': round(time.time() - t0, 1)}
    return {'status': 'timeout', 'error': f'{JOB_TIMEOUT} 秒內未完成', 'seconds': JOB_TIMEOUT}


# ── 判定 ──────────────────────────────────────────────────────────────────────

def unsupported_numbers(advice, context):
    """回覆中的數字若在這次查到的內容、使用者問題中都找不到，視為無出處。"""
    body = LIST_NUMBER_RE.sub('', advice)
    context_numbers = set(NUMBER_RE.findall(context))
    return sorted({n for n in NUMBER_RE.findall(body) if n not in context_numbers})


def judge(q, run, refusal_sentence):
    advice = run.get('advice') or ''
    steps = run.get('steps') or []
    searched = any(s.get('action') == 'search_knowledge_base' for s in steps)
    retrieved = sorted({src for s in steps if s.get('action') == 'search_knowledge_base'
                        for src in SOURCE_RE.findall(str(s.get('observation', '')))})
    context = q['user_message'] + '\n' + '\n'.join(str(s.get('observation', '')) for s in steps)
    refused = refusal_sentence in advice or bool(REFUSAL_RE.search(advice))

    result = {
        'completed': run['status'] == 'done',
        'searched': searched,
        'retrieved_sources': retrieved,
        'refused': refused,
        'must_not_hits': [w for w in q['must_not_include'] if w in advice],
        'include_hits': [any(p in advice for p in group) for group in q['must_include_any']],
        'unsupported_numbers': [] if refused else unsupported_numbers(advice, context),
    }
    if q['category'] != 'refusal' and q['expected_sources']:
        result['citation_ok'] = any(src in retrieved for src in q['expected_sources'])

    # 幻覺只算「捏造內容」；應拒答卻沒拒答是違反規則，另由拒答正確率計算（若因此說出藥名等，仍會命中禁止詞）
    signals = []
    if result['must_not_hits']:
        signals.append('出現禁止詞')
    if result['unsupported_numbers']:
        signals.append('數字無出處')
    if q['category'] != 'refusal' and not refused and not searched:
        signals.append('未查詢知識庫')
    result['hallucination_signals'] = signals
    result['hallucinated'] = bool(signals)
    return result


# ── 彙整 ──────────────────────────────────────────────────────────────────────

def ratio(items, key):
    vals = [bool(i[key]) for i in items if key in i]
    return sum(vals) / len(vals) * 100 if vals else None


def metrics_of(rows):
    """rows：同一次重複中所有題目的 (question, judgement)。"""
    answerable = [j for q, j in rows if q['category'] in ('posture', 'ergonomics')]
    refusal = [j for q, j in rows if q['category'] == 'refusal']
    groups = [hit for q, j in rows for hit in j['include_hits']]
    return {
        '引用正確率': ratio([j for q, j in rows if 'citation_ok' in j], 'citation_ok'),
        '關鍵內容命中率': sum(groups) / len(groups) * 100 if groups else None,
        '拒答正確率': ratio(refusal, 'refused'),
        '誤拒率': ratio(answerable, 'refused'),
        '幻覺率': ratio([j for q, j in rows], 'hallucinated'),
        '完成率': ratio([j for q, j in rows], 'completed'),
    }


def mean_std(values):
    values = [v for v in values if v is not None]
    if not values:
        return None, None
    return statistics.mean(values), (statistics.stdev(values) if len(values) > 1 else 0.0)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--base-url', default='http://localhost:8000')
    p.add_argument('--ids', help='只跑指定題號，逗號分隔')
    p.add_argument('--repeat', type=int, default=3)
    p.add_argument('--workers', type=int, default=12, help='同時送出的任務數')
    p.add_argument('--testset', default=str(TESTSET), help='題庫檔（預設 hallucination_testset.json）')
    p.add_argument('--label', help='結果檔名前綴')
    p.add_argument('--rescore', metavar='RESULT_JSON', help='不重新呼叫 Agent，用已存的回覆依目前的判定規則重新計分')
    args = p.parse_args()

    testset = json.loads(Path(args.testset).read_text(encoding='utf-8'))
    if args.rescore:
        old = json.loads(Path(args.rescore).read_text(encoding='utf-8'))
        qmap = {q['id']: q for q in testset['questions']}
        report([(r['repeat'], qmap[r['id']], r['run']) for r in old['records']],
               testset, old['repeat'], old['base_url'], time.time(), label=Path(args.rescore).stem + '_rescored')
        return
    questions = testset['questions']
    if args.ids:
        wanted = set(args.ids.split(','))
        questions = [q for q in questions if q['id'] in wanted]
    base = args.base_url.rstrip('/')
    headers = login(base, {'ngrok-skip-browser-warning': 'true'})

    tasks = [(rep, q) for rep in range(args.repeat) for q in questions]
    print(f'共 {len(tasks)} 次（{len(questions)} 題 × {args.repeat} 次），同時 {args.workers} 筆', flush=True)
    t_start = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        runs = list(pool.map(lambda t: ask_agent(base, headers, t[1]), tasks))

    report([(rep, q, run) for (rep, q), run in zip(tasks, runs)], testset, args.repeat, base, t_start,
           label=f'{args.label}_{datetime.now():%Y%m%d_%H%M}' if args.label else None)


def report(items, testset, repeat, base, t_start, label=None):
    records = []
    for rep, q, run in items:
        j = judge(q, run, testset['refusal_sentence'])
        records.append({'repeat': rep, 'id': q['id'], 'category': q['category'], 'question': q,
                        'run': run, 'judgement': j})
        flag = '⚠ ' + '、'.join(j['hallucination_signals']) if j['hallucinated'] else 'OK'
        if q['category'] == 'refusal' and not j['refused']:
            flag += '（未依規拒答）'
        print(f'  [{rep + 1}] {q["id"]} {run["status"]:7} {run["seconds"]:5}s  {flag}'
              + (f'  數字:{j["unsupported_numbers"]}' if j['unsupported_numbers'] else ''), flush=True)

    per_repeat = [metrics_of([(r['question'], r['judgement']) for r in records if r['repeat'] == rep])
                  for rep in range(repeat)]
    summary = {}
    print('\n=== 指標（平均 ± 標準差，單位 %）===')
    for k in per_repeat[0]:
        m, s = mean_std([pr[k] for pr in per_repeat])
        summary[k] = {'mean': None if m is None else round(m, 1), 'std': None if s is None else round(s, 1)}
        print(f'  {k:8}  ' + ('—' if m is None else f'{m:5.1f} ± {s:.1f}'))

    by_cat = {}
    for cat in ('posture', 'ergonomics', 'refusal', 'trap'):
        rs = [r for r in records if r['category'] == cat]
        if rs:
            by_cat[cat] = round(sum(r['judgement']['hallucinated'] for r in rs) / len(rs) * 100, 1)
    print('  各類別幻覺率：', by_cat)
    latencies = [r['run']['seconds'] for r in records if r['run']['status'] == 'done']
    if latencies:
        print(f'  回應時間：平均 {statistics.mean(latencies):.1f}s，最長 {max(latencies):.1f}s；'
              f'總耗時 {time.time() - t_start:.0f}s')

    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f'{label or f"eval_{datetime.now():%Y%m%d_%H%M}"}.json'
    out.write_text(json.dumps({
        'base_url': base, 'repeat': repeat, 'question_ids': sorted({r['id'] for r in records}),
        'summary': summary, 'per_repeat': per_repeat, 'hallucination_rate_by_category': by_cat,
        'records': records,
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'\n完整結果（含每題回覆全文）：{out}')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
