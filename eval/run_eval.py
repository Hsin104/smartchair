"""
Physio Agent 防幻覺自動評測（指標定義見 eval/README.md）

用法：
    python eval/run_eval.py                         # 全部 36 題 × 3 次，打本機 http://localhost:8000
    python eval/run_eval.py --ids P01,R01,T01 --repeat 1   # 只跑指定題目（試跑用）
    python eval/run_eval.py --base-url https://<ngrok網域> --workers 2  # 打正式環境（要降低同時請求數，見 README）
    python eval/run_eval.py --judge                 # 加做 LLM 複核，多算「無依據動作率」（見 README）

流程：每題送 POST /api/agent/jobs，輪詢 GET /api/agent/jobs/<id> 拿到回覆全文與 ReAct 步驟，
逐題判定後彙整指標。原始回覆全部存進 eval/results/，供人工複核。
會真的呼叫 OpenAI（gpt-4o-mini），36 題 × 3 次約 108 次回答。執行前會先印出預估花費，
超過 --budget（預設 0.5 美金）就不執行；跑完印出 Agent 記錄的實際 Token 用量與花費。
金鑰每月預算有限（見 README「花費控制」），只跑需要的題目，--judge 用 gpt-4o 尤其貴。
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
# Agent 自己的檢查步驟（範疇判斷、動作出處檢查）不是查到的內容，判定「有沒有出處」時要排除，
# 否則 grounding_check 記下的「無依據動作」原文會被當成出處
INTERNAL_STEPS = ('scope_check', 'grounding_check', 'token_usage', 'action_check')

# ── 花費控制 ──────────────────────────────────────────────────────────────────
# 教授的金鑰每月預算 100 美金，11/15 一天的評測（gpt-4o 複核＋反覆重跑）就把額度用完。
# 所以每次執行前先估算花費，超過 --budget 就不跑；跑完再用 Agent 記錄的實際 Token 用量算出真正花費。
PRICE_PER_M = {'gpt-4o-mini': (0.15, 0.60), 'gpt-4o': (2.50, 10.00)}   # 美金／百萬 tokens（輸入, 輸出）
# 估算用的每次用量：11/14～15 實測每次回答平均輸入 6,956、輸出 295 tokens（精簡前），這裡取偏高的值
EST_AGENT_TOKENS = (8000, 400)
EST_JUDGE_TOKENS = (4000, 300)    # 每個非拒答回答約 1～3 次複核呼叫，取 1.5 次
JUDGE_USAGE = {'input_tokens': 0, 'output_tokens': 0}


def cost(model, input_tokens, output_tokens):
    pin, pout = PRICE_PER_M.get(model, PRICE_PER_M['gpt-4o'])
    return input_tokens / 1e6 * pin + output_tokens / 1e6 * pout


def estimate(n_agent, n_judge, judge_model):
    agent = cost('gpt-4o-mini', *(x * n_agent for x in EST_AGENT_TOKENS))
    judge = cost(judge_model, *(x * n_judge * 1.5 for x in EST_JUDGE_TOKENS)) if judge_model else 0
    return agent, judge


def check_budget(n_agent, n_judge, judge_model, budget):
    agent, judge = estimate(n_agent, n_judge, judge_model)
    print(f'預估花費：Agent {n_agent} 次約 US${agent:.3f}'
          + (f'＋複核（{judge_model}）{n_judge} 次約 US${judge:.3f}' if judge_model else '')
          + f'，合計 US${agent + judge:.3f}（上限 --budget {budget}）', flush=True)
    if agent + judge > budget:
        sys.exit('預估花費超過上限，未執行。確定要跑請調高 --budget，或用 --ids 只跑需要的題目')


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
    context = q['user_message'] + '\n' + '\n'.join(
        str(s.get('observation', '')) for s in steps if s.get('action') not in INTERNAL_STEPS)
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
    # Agent 回覆前已用程式核對每個動作的出處（physio_agent._check_actions），這裡只讀結果，不花錢
    check = next((s for s in steps if s.get('action') == 'action_check'), None)
    if check:
        result['action_check'] = check.get('action_input', {})

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


# ── LLM 複核（--judge）────────────────────────────────────────────────────────
# 關鍵字與數字比對抓不到「沒有數字的捏造內容」（例如自己編了一個知識庫沒有的伸展動作），所以另外請 LLM
# 列出回覆中的每個動作，並從查到的內容「逐字引用」一句證據；引文再由程式確認真的出現在查到的內容裡，
# 找不到引文或引文對不上的動作就算無依據。數字仍由上面的程式比對負責。
# 第一版曾讓 gpt-4o-mini 直接判斷「哪些句子無依據」，結果把知識庫原文（椅背 95-110 度、20-20-20）也判成
# 無依據，誤判太多不能用，才改成「必須引用原文、程式驗證引文」。結果獨立列為「無依據動作率」，不併入幻覺率。

JUDGE_PROMPT = """你是查核員。下面有【查詢結果】（AI 助手這次查到的全部內容）與【回覆】。
請列出回覆中建議使用者做的每一個「伸展或運動動作」（例如頸部縮回、弓箭步伸展、深蹲、踮腳；
調整螢幕或椅子、設定鬧鐘、起身走動、休息看遠處這類不是運動動作，不要列）。

對每個動作，到【查詢結果】裡找出描述同一個動作的句子：
- 找得到：evidence 填查詢結果中的原句，必須一字不改地複製（可以只複製其中 8 到 40 個字）
- 找不到（查詢結果沒有這個動作，或只有名稱相似但做法不同的動作）：evidence 填空字串

只輸出 JSON：{"actions": [{"action": "動作名稱", "reply_text": "回覆中描述這個動作的原句", "evidence": "查詢結果原句或空字串"}]}
回覆中沒有任何運動動作時輸出 {"actions": []}"""

# 第一輪一次看整篇回覆，動作只出現在一串列舉裡（「棒式、橋式、四足跪姿」）時常漏找證據，
# 所以第一輪找不到證據的動作，再單獨問一次
RECHECK_PROMPT = """你是查核員。下面有【查詢結果】與 AI 助手回覆中的一句【動作描述】。
請判斷查詢結果裡有沒有「同一個動作」：
- 回覆只提到動作名稱、沒有寫做法：查詢結果中有相同名稱（或括號內的別名）就算有
- 回覆寫了做法：查詢結果中的做法必須相同或不矛盾才算有；名稱相近但做法不同不算
有的話，evidence 填查詢結果中包含這個動作的原句（一字不改地複製其中 8 到 40 個字）；沒有就填空字串。
只輸出 JSON：{"evidence": "查詢結果原句或空字串"}"""


def _squash(text):
    return re.sub(r'[\s*＊]+', '', text)


def load_openai_key():
    import os
    key = os.environ.get('OPENAI_API_KEY')
    env = HERE.parent / '.env'
    if not key and env.exists():
        for line in env.read_text(encoding='utf-8').splitlines():
            if line.startswith('OPENAI_API_KEY='):
                key = line.split('=', 1)[1].strip().strip('"\'')
    if not key:
        sys.exit('--judge 需要 OPENAI_API_KEY（環境變數或專案根目錄的 .env）')
    return key


def _ask_json(client, model, system, user):
    r = client.chat.completions.create(
        model=model, temperature=0, response_format={'type': 'json_object'},
        messages=[{'role': 'system', 'content': system}, {'role': 'user', 'content': user}])
    JUDGE_USAGE['input_tokens'] += r.usage.prompt_tokens
    JUDGE_USAGE['output_tokens'] += r.usage.completion_tokens
    return json.loads(r.choices[0].message.content)


def llm_judge(client, model, q, run):
    """回傳回覆中在查到的內容裡找不到依據的動作清單；拒答或未完成的回覆不複核（回傳 None）。"""
    advice = run.get('advice') or ''
    if run.get('status') != 'done' or REFUSAL_RE.search(advice):
        return None
    context = '\n\n'.join(str(s.get('observation', '')) for s in run.get('steps') or []
                          if s.get('action') not in INTERNAL_STEPS)
    flat = _squash(context)
    # 工具回傳值存成字串時，換行是字面的「\n」兩個字元，所以兩種換行都要切
    lines = [_squash(line) for line in re.split(r'\\n|\n', context)]

    def supported(evidence, reply_text):
        """引文要真的出現在查到的內容裡，而且回覆替這個動作寫的次數／秒數都要出現在引文所在的那一行。
        （只比對整體數字會漏：「維持 15 秒重複 3 次」的 15、3 常在別的動作那幾行出現過。）"""
        evidence = _squash(str(evidence or ''))
        if len(evidence) < 4 or evidence not in flat:
            return False
        line = next((line for line in lines if evidence in line), None)
        if line is None:  # 引文跨行，無法定位到單一行，只確認動作存在
            return True
        allowed = set(NUMBER_RE.findall(line))
        return all(n in allowed for n in NUMBER_RE.findall(LIST_NUMBER_RE.sub('', reply_text)))

    try:
        actions = _ask_json(client, model, JUDGE_PROMPT,
                            f'【查詢結果】\n{context}\n\n【回覆】\n{advice}').get('actions', [])
        unsupported = []
        for a in actions:
            text = a.get('reply_text') or a.get('action', '')
            if supported(a.get('evidence'), text):
                continue
            again = _ask_json(client, model, RECHECK_PROMPT,
                              f'【查詢結果】\n{context}\n\n【動作描述】\n{text}')
            if not supported(again.get('evidence'), text):
                unsupported.append({'action': a.get('action', ''), 'reply_text': text})
        return unsupported
    except Exception as e:
        return [{'action': '', 'reply_text': f'複核失敗：{str(e)[:200]}'}]


# ── 彙整 ──────────────────────────────────────────────────────────────────────

def ratio(items, key):
    vals = [bool(i[key]) for i in items if key in i]
    return sum(vals) / len(vals) * 100 if vals else None


def metrics_of(rows):
    """rows：同一次重複中所有題目的 (question, judgement)。"""
    answerable = [j for q, j in rows if q['category'] in ('posture', 'ergonomics')]
    refusal = [j for q, j in rows if q['category'] == 'refusal']
    groups = [hit for q, j in rows for hit in j['include_hits']]
    checked = sum(j.get('action_check', {}).get('checked', 0) for q, j in rows)
    failed = sum(j.get('action_check', {}).get('failed', 0) for q, j in rows)
    return {
        '引用正確率': ratio([j for q, j in rows if 'citation_ok' in j], 'citation_ok'),
        '關鍵內容命中率': sum(groups) / len(groups) * 100 if groups else None,
        '拒答正確率': ratio(refusal, 'refused'),
        '誤拒率': ratio(answerable, 'refused'),
        '幻覺率': ratio([j for q, j in rows], 'hallucinated'),
        '完成率': ratio([j for q, j in rows], 'completed'),
        # 只在 --judge 時有值；分母是有實際回答（非拒答）的題目
        '無依據動作率': ratio([j for q, j in rows if j.get('llm_unsupported') is not None], 'llm_unsupported'),
        # 程式核對（不呼叫 LLM）：分母是「立即改善」裡的動作數，不是題數
        '動作出處未通過率': failed / checked * 100 if checked else None,
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
    p.add_argument('--judge', action='store_true', help='加做 LLM 複核，檢查回覆中的動作是否都出自查到的內容，算出「無依據動作率」')
    p.add_argument('--judge-model', default='gpt-4o')
    p.add_argument('--budget', type=float, default=0.5, help='預估花費上限（美金），超過就不執行')
    args = p.parse_args()
    judge_model = args.judge_model if args.judge else None

    testset = json.loads(Path(args.testset).read_text(encoding='utf-8'))
    if args.rescore:
        old = json.loads(Path(args.rescore).read_text(encoding='utf-8'))
        qmap = {q['id']: q for q in testset['questions']}
        if judge_model:
            check_budget(0, len(old['records']), judge_model, args.budget)
        report([(r['repeat'], qmap[r['id']], r['run']) for r in old['records']],
               testset, old['repeat'], old['base_url'], time.time(), label=Path(args.rescore).stem + '_rescored',
               judge_model=judge_model)
        return
    questions = testset['questions']
    if args.ids:
        wanted = set(args.ids.split(','))
        questions = [q for q in questions if q['id'] in wanted]
    base = args.base_url.rstrip('/')
    headers = login(base, {'ngrok-skip-browser-warning': 'true'})

    tasks = [(rep, q) for rep in range(args.repeat) for q in questions]
    print(f'共 {len(tasks)} 次（{len(questions)} 題 × {args.repeat} 次），同時 {args.workers} 筆', flush=True)
    check_budget(len(tasks), len(tasks) if judge_model else 0, judge_model, args.budget)
    t_start = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        runs = list(pool.map(lambda t: ask_agent(base, headers, t[1]), tasks))

    report([(rep, q, run) for (rep, q), run in zip(tasks, runs)], testset, args.repeat, base, t_start,
           label=f'{args.label}_{datetime.now():%Y%m%d_%H%M}' if args.label else None, judge_model=judge_model)


def report(items, testset, repeat, base, t_start, label=None, judge_model=None):
    llm_results = [None] * len(items)
    if judge_model:
        from openai import OpenAI
        client = OpenAI(api_key=load_openai_key())
        with ThreadPoolExecutor(max_workers=8) as pool:
            llm_results = list(pool.map(lambda it: llm_judge(client, judge_model, it[1], it[2]), items))

    records = []
    for (rep, q, run), unsupported in zip(items, llm_results):
        j = judge(q, run, testset['refusal_sentence'])
        if unsupported is not None:
            j['llm_unsupported'] = unsupported
        records.append({'repeat': rep, 'id': q['id'], 'category': q['category'], 'question': q,
                        'run': run, 'judgement': j})
        flag = '⚠ ' + '、'.join(j['hallucination_signals']) if j['hallucinated'] else 'OK'
        if q['category'] == 'refusal' and not j['refused']:
            flag += '（未依規拒答）'
        print(f'  [{rep + 1}] {q["id"]} {run["status"]:7} {run["seconds"]:5}s  {flag}'
              + (f'  數字:{j["unsupported_numbers"]}' if j['unsupported_numbers'] else '')
              + (f'  無依據動作:{[u["action"][:12] for u in j["llm_unsupported"]]}' if j.get('llm_unsupported') else ''),
              flush=True)

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

    usage = [s['action_input'] for r in records for s in r['run'].get('steps') or []
             if s.get('action') == 'token_usage']
    spent = None
    if usage:
        tin = sum(u['input_tokens'] for u in usage)
        tout = sum(u['output_tokens'] for u in usage)
        cached = sum(u.get('cached_tokens', 0) for u in usage)
        # 快取命中的輸入以半價計費
        spent = cost('gpt-4o-mini', tin - cached / 2, tout)
        print(f'  實際 Token：{len(usage)} 次回答，輸入 {tin:,}（快取 {cached:,}）、輸出 {tout:,}；'
              f'每次平均 {tin / len(usage):,.0f}／{tout / len(usage):,.0f}；Agent 花費約 US${spent:.3f}')
    if JUDGE_USAGE['input_tokens']:
        jc = cost(judge_model, JUDGE_USAGE['input_tokens'], JUDGE_USAGE['output_tokens'])
        print(f'  複核 Token：輸入 {JUDGE_USAGE["input_tokens"]:,}、輸出 {JUDGE_USAGE["output_tokens"]:,}，約 US${jc:.3f}')

    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f'{label or f"eval_{datetime.now():%Y%m%d_%H%M}"}.json'
    out.write_text(json.dumps({
        'base_url': base, 'repeat': repeat, 'question_ids': sorted({r['id'] for r in records}),
        'summary': summary, 'per_repeat': per_repeat, 'hallucination_rate_by_category': by_cat,
        'agent_cost_usd': spent, 'judge_usage': dict(JUDGE_USAGE),
        'records': records,
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'\n完整結果（含每題回覆全文）：{out}')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
