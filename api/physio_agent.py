"""
Physio Agent — 完整 Agent 架構（四大核心模組）

大腦（LLM）  : OpenAI（settings.OPENAI_MODEL，教授提供按量計費金鑰）+ 領域專精 Prompt 設計
記憶（Memory）: 外部知識庫（knowledge_base/*.txt）→ FAISS 向量庫（OpenAI Embedding，見 mcp_server.py），
               經 MCP Server 暴露查詢工具
工具（Tools） : MCP（Model Context Protocol）— 獨立跑的 api/mcp_server.py（python manage.py mcp_server），
               透過 Streamable HTTP 暴露 3 個工具：知識庫查詢、坐姿歷史查詢、網路搜尋
               （震動馬達由即時偵測管線直接觸發，不經過 Agent，見 mcp_server.py 開頭說明）
行動（Action）: 本檔案手寫的 ReAct 迴圈（Thought→Action→Observation→Thought），
               每輪逐步記錄，不經由 LangChain AgentExecutor 黑盒子執行
"""

import asyncio
import json
import logging

from django.conf import settings
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage

logger = logging.getLogger(__name__)

POSTURE_DISPLAY = {
    'normal':    '標準坐姿',
    'left':      '身體左傾',
    'right':     '身體右傾',
    'forward':   '頭部前傾（烏龜頸）',
    'recline':   '過度後仰',
    'sedentary': '久坐未動',
    'empty':     '無人就坐',
}

MAX_ITERATIONS = 8

# 正常 2~4 步的 ReAct 迴圈約 20~30 秒完成，8 步的極端情況也大約 60~70 秒，
# 設 60 秒避免單次請求卡住時無限期等待。
_LLM_TIMEOUT_SECONDS = 60


# ── System Prompt ──────────────────────────────────────────────────────────────

# 11/19 精簡：原本 2,427 tokens，而且 ReAct 每一輪都要重送一次。刪掉與工具定義（bind_tools 已帶入）、
# 範疇判斷（已拆成獨立呼叫）重複的段落，規則本身不變。仍保持在 1,024 tokens 以上，OpenAI 自動快取才會生效。
_SYSTEM_PROMPT = """你是物理治療師 AI 助手「SmartChair」，專精辦公室人體工學與職業傷害預防。
你只負責諮詢，沒有控制震動馬達的工具，也不可暗示自己會讓椅子震動（震動由智慧椅自行觸發）。

【流程】
Step 0 範疇判斷（有「使用者自述」時必做，優先於偵測到的坐姿）
- 不可回答範疇：藥物或止痛藥、手術、注射治療、疾病診斷或嚴重程度判斷、減重／體重管理／BMI 評估、
  懷孕、血壓／中風等心血管問題、焦慮／失眠／憂鬱等精神健康、保健食品、飲食或飲料
  （該吃什麼、該喝什麼、喝多少、營養、咖啡因、酒精、喝水量）
- 依使用者「問的主題」判斷：同時提到不適又問上述內容（例如「脖子痛可以吃什麼止痛藥」
  「喝酒會不會讓腰更痠」），仍屬不可回答，不可只挑坐姿相關的部分回答
- 不可回答時，只回覆這句並停止：「根據目前知識庫，我無法回答此問題，建議諮詢專業醫師或物理治療師。」
  不可改給坐姿建議，也不可用 web_search 迴避
- 其餘都屬可回答，必須照常進行 Step 1～3：人體工學設置（螢幕、座深、腰靠、扶手、椅背、桌面、鍵盤滑鼠、手腕）、
  休息與起身頻率、坐站交替、伸展與肌力運動、呼吸練習、看螢幕造成的眼睛疲勞、腰靠護具等輔具的效果、
  震動回饋的效果、坐姿相關的痠痛與不適、久坐對健康的一般影響、詢問相關數據或研究說法是否正確
- 可回答的問題即使知識庫沒有使用者要的數字或研究，也要先查詢，再說明「知識庫沒有這項資料」
  並提供查到的相關內容，不可使用拒答句
- 不確定是否屬於不可回答範疇時，一律視為可回答
Step 1 呼叫 get_posture_history(user_id)：取得身高體重、最近坐姿與近 7 天壞坐姿統計，找出最需要改善的坐姿
Step 2 呼叫 search_knowledge_base(query)：有使用者自述時以他問的主題為查詢字串；查詢結果沒有回答到問題，
  就換一組關鍵字再查一次，不可用自己的知識補足；知識庫查無相關文獻且仍屬人體工學範疇時，才可呼叫 web_search
Step 3 根據 Step 1～2 的結果，寫出個人化建議

【防幻覺規則（違反任一條都算幻覺）】
1. 只能根據 search_knowledge_base 或 web_search 回傳的內容回答，不可引用以外的醫學資訊、研究或數字
2. 不診斷疾病、不評估病情嚴重程度、不推薦藥物、手術或補充品
3. 只能列查詢結果中有的伸展或運動動作，做法、次數與秒數照原文；原文沒寫次數或秒數就不要寫；
   查到的動作不足 3 個就只列查到的，不可自行補其他動作湊數
4. 身高體重只能用於人體工學調整（例如依身高調整螢幕高度、座深），不可評估體位或健康風險
5. 回覆最後必須有「📚 參考來源」，列出實際查到的 .txt 檔名或網址；查無相關文獻時寫「（無相關知識庫文獻）」，
   並且不提供建議

【回答格式】（繁體中文，語氣友善而專業）

⚠️ 問題分析
（引用知識庫說明，可標註「根據 forward.txt 文獻」）

✅ 立即改善（最多 3 個動作）
1.
2.
3.

💪 長期預防
（需出自知識庫）

⏰ 提醒
（一句溫馨提醒）

📚 參考來源（必填）
- 檔名.txt"""


# ── MCP Client + 手寫 ReAct 迴圈 ─────────────────────────────────────────────────

def _flatten_content(content) -> str:
    """LLM 回覆的 content 可能是 str，也可能是多個 part 組成的 list。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(item.get('text', ''))
            elif isinstance(item, str):
                parts.append(item)
        return ''.join(parts)
    return str(content)


def _leaf_error_message(e: BaseException) -> str:
    """
    MCP client 底層用 anyio TaskGroup，真正的錯誤（連線被拒、OpenAI 429…）會被包進
    ExceptionGroup，str(e) 只剩「unhandled errors in a TaskGroup」。攤平取出所有子例外的
    類型與訊息，下面的錯誤分類字串比對才對得到。
    """
    if isinstance(e, BaseExceptionGroup):
        return ' | '.join(_leaf_error_message(sub) for sub in e.exceptions)
    return f'{type(e).__name__}: {e}'


# App 會直接顯示錯誤文字，所以這裡只放使用者看得懂的中文；原始錯誤（英文、含主機與埠）只寫進 log。
# 故障測試（fault_test.py，教授 11/16 第 12 點）發現原本會把 OpenAI 的英文錯誤 JSON、
# 「請確認 python manage.py mcp_server 是否已啟動」這類開發者訊息直接顯示給使用者。
ERR_QUOTA      = 'AI 服務的使用額度或速率已達上限，請稍後再試'
ERR_AUTH       = 'AI 服務的金鑰無效或已停用，請通知開發者處理'
ERR_OPENAI     = '目前無法連線到 AI 服務（OpenAI），請稍後再試'
ERR_MCP        = '知識庫服務暫時無法連線，請稍後再試'
ERR_TIMEOUT    = 'AI 服務回應逾時，請稍後再試'
ERR_UNEXPECTED = 'Physio Agent 發生未預期錯誤，請稍後再試；若持續發生請通知開發者'


def _fatal_error(msg: str) -> str:
    """重試也不會好的錯誤（額度用完、金鑰無效），回傳給使用者的訊息；其他錯誤回傳空字串。"""
    if '429' in msg or 'insufficient_quota' in msg or 'rate_limit' in msg.lower():
        return ERR_QUOTA
    if '401' in msg or 'invalid_api_key' in msg or 'AuthenticationError' in msg:
        return ERR_AUTH
    return ''


def _is_refusal(response: str) -> bool:
    return '無法回答' in response and '知識庫' in response


# ── Token 用量 ─────────────────────────────────────────────────────────────────
# 教授提供的金鑰有每月預算（11/15 被評測用到見底），所以每次 LLM 呼叫都記下實際用量，
# 最後彙整成一個 token_usage 步驟存進 AgentLog.steps，之後報告用實測數字而不是估算。
# 回覆字數最長約 540 字（11/14～15 評測 2,222 次回答），1,000 tokens 足夠，只防止異常的超長輸出。
_MAX_OUTPUT_TOKENS = 1000


def _add_usage(total: dict, response) -> None:
    usage = getattr(response, 'usage_metadata', None) or {}
    total['calls'] += 1
    total['input_tokens'] += usage.get('input_tokens', 0)
    total['output_tokens'] += usage.get('output_tokens', 0)
    # OpenAI 會自動快取超過 1,024 tokens 的相同開頭（System Prompt），快取部分以半價計費
    total['cached_tokens'] += (usage.get('input_token_details') or {}).get('cache_read', 0)


def _new_usage() -> dict:
    return {'calls': 0, 'input_tokens': 0, 'cached_tokens': 0, 'output_tokens': 0}


async def _run_react(question: str, api_key: str, usage: dict) -> tuple[str, list]:
    """
    手寫 ReAct 迴圈：Thought（模型回覆）→ Action（MCP 工具呼叫）→ Observation（工具回傳）→ 再思考。

    每輪都顯式記錄進 steps，不經由 LangChain AgentExecutor 等黑盒子執行，
    供 AgentLog.steps 落地保存、Django admin 檢視完整決策過程。
    """
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    from langchain_mcp_adapters.tools import load_mcp_tools

    url = f'http://{settings.MCP_SERVER_HOST}:{settings.MCP_SERVER_PORT}/mcp'

    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await load_mcp_tools(session)

            llm = ChatOpenAI(
                model=settings.OPENAI_MODEL,
                api_key=api_key,
                temperature=0.2,
                max_tokens=_MAX_OUTPUT_TOKENS,
            ).bind_tools(tools)

            # System Prompt 必須放在最前面且內容固定，OpenAI 的自動快取才會命中
            messages = [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=question)]
            steps = []
            # 規則 1（先查知識庫）用程式強制，不只靠 Prompt：評測發現模型會跳過知識庫直接用 web_search 回答
            kb_searched = False

            for i in range(MAX_ITERATIONS):
                response = await llm.ainvoke(messages)
                _add_usage(usage, response)
                messages.append(response)

                if not response.tool_calls:
                    return _flatten_content(response.content), steps

                for call in response.tool_calls:
                    tool = next((t for t in tools if t.name == call['name']), None)
                    if tool is None:
                        observation = f'錯誤：找不到工具 {call["name"]}'
                    elif call['name'] == 'web_search' and not kb_searched:
                        observation = ('錯誤：必須先呼叫 search_knowledge_base 查詢知識庫，'
                                       '查無相關文獻時才可以使用 web_search')
                    else:
                        observation = await tool.ainvoke(call['args'])
                        kb_searched = kb_searched or call['name'] == 'search_knowledge_base'

                    steps.append({
                        'step':         i + 1,
                        'thought':      _flatten_content(response.content),
                        'action':       call['name'],
                        'action_input': call['args'],
                        'observation':  str(observation),
                    })
                    messages.append(ToolMessage(content=str(observation), tool_call_id=call['id']))

            return '（已達最大步數，回傳目前累積資訊，建議重新提問或簡化問題）', steps


# ── 範疇判斷（獨立於 ReAct 迴圈） ───────────────────────────────────────────────

REFUSAL_SENTENCE = '根據目前知識庫，我無法回答此問題，建議諮詢專業醫師或物理治療師。'

# 為什麼不只靠 System Prompt 的 Step 0：防幻覺評測（eval/RESULTS.md 第六節）發現，同一次呼叫裡同時要
# 「判斷範疇」和「給坐姿建議」時，模型常直接略過使用者的問題改給坐姿建議（偵測坐姿把任務框成了給建議），
# 補再多規則與範例也只修得好拿來調整的那幾題。所以把範疇判斷拆成獨立的一次呼叫：只看使用者自述、
# 不帶偵測坐姿、不帶工具，只回答「這個問題能不能答」。
_SCOPE_PROMPT = """你是智慧坐姿椅 App 的問題分類器，只負責判斷使用者的問題能不能由「辦公室坐姿與人體工學知識庫」回答。
不要回答問題本身，只輸出 JSON：{"scope": "in" 或 "out", "category": "類別", "reason": "一句話理由"}

判斷方式：看使用者「想得到什麼答案」，不是看句子裡有沒有提到坐姿、痠痛或椅子。

scope = "out"（使用者想得到的是以下任何一類答案）：
- 藥物：口服藥、外用藥、止痛或消炎用品該不該用、有沒有效
- 醫療處置：手術、注射、各種需由醫療人員執行的治療該不該做、有沒有效
- 診斷：自己是不是得了某種病、某個症狀是不是某種病變造成的、嚴不嚴重
- 體重：減重、體重管理、BMI 或體型評估
- 懷孕相關
- 心血管：血壓、中風、心臟等疾病風險
- 精神健康：焦慮、失眠、憂鬱、情緒問題
- 飲食：該吃什麼、該喝什麼、喝多少、營養、保健食品與補充品、咖啡因、酒精、各種飲料，
  包含問某種食物或飲料對姿勢、痠痛、骨骼、精神的影響
問題同時包含可回答與不可回答的部分時，一律判為 "out"。

scope = "in"（其餘皆是），例如：
- 坐姿、桌椅螢幕鍵盤滑鼠等人體工學設置、輔具（腰靠、護具、站立桌）有沒有用
- 伸展、肌力、核心、呼吸等運動怎麼做、做多久
- 休息與起身頻率、久坐的影響（包含久坐對健康、壽命的一般影響，知識庫有收錄）
- 看螢幕造成的眼睛疲勞
- 描述痠痛、僵硬、疲勞等不適（沒有問「是不是某種病」就不算要求診斷），想知道怎麼調整或改善
- 問如何「預防」某種職業傷害（例如怎麼放手腕才不會受傷）
- 問某個與上述主題有關的數據、研究或說法是否正確
- 只是描述自己的習慣或狀況，沒有提出上述 "out" 類別的問題

不確定時判為 "in"。"""


# 範疇判斷失敗時的保守回應：不確定能不能答，就不進 ReAct 迴圈給建議。
# 原本失敗時視為「可回答」、交給 Step 0 把關，但 Step 0 也是 LLM，兩道都可能出錯（教授 11/16 第 12 點）；
# 健康相關的問題寧可請使用者稍後再試。這句話同時含「知識庫」與「無法回答」，_is_refusal 會當成拒答處理，
# 不會再被加上「未附來源」警告。
SCOPE_UNAVAILABLE = '目前無法確認這個問題能否由知識庫回答，暫時無法回答，請稍後再試；如有身體不適，建議諮詢專業醫師或物理治療師。'
_SCOPE_TIMEOUT_SECONDS = 10
_SCOPE_MAX_TOKENS = 150   # 只輸出一行 JSON


async def _classify_scope(user_message: str, api_key: str, usage: dict, llm=None) -> dict:
    """
    判斷使用者自述是否屬於可回答範疇，回傳 {'scope': 'in'|'out'|'error', 'category': str, 'reason': str}。
    逾時、服務中斷或輸出格式不對時重試一次，仍失敗回傳 'error'，由呼叫端給保守回應。
    llm 參數只給測試注入假模型用。
    """
    llm = llm or ChatOpenAI(model=settings.OPENAI_MODEL, api_key=api_key, temperature=0,
                            max_tokens=_SCOPE_MAX_TOKENS).bind(response_format={'type': 'json_object'})
    errors = []
    for _ in range(2):
        try:
            response = await asyncio.wait_for(
                llm.ainvoke([SystemMessage(content=_SCOPE_PROMPT), HumanMessage(content=user_message)]),
                timeout=_SCOPE_TIMEOUT_SECONDS)
            _add_usage(usage, response)
            result = json.loads(_flatten_content(response.content))
            if result.get('scope') not in ('in', 'out'):
                raise ValueError(f'scope 值不合法：{result}')
            return result
        except Exception as e:  # noqa: BLE001 — 失敗都改走保守回應，原因記進 log 與第 0 步
            msg = _leaf_error_message(e)
            if _fatal_error(msg):
                raise   # 額度用完、金鑰無效，重試也沒用，交給 get_advice_async 回傳明確錯誤，而不是「請稍後再試」
            errors.append('逾時' if isinstance(e, asyncio.TimeoutError) else msg[:120])
    logger.error(f'[PhysioAgent] 範疇判斷連續失敗，改回保守回應：{" / ".join(errors)}')
    return {'scope': 'error', 'category': '', 'reason': '範疇判斷失敗：' + ' / '.join(errors)}


async def _answer(question: str, user_message: str, api_key: str, usage: dict) -> tuple[str, list]:
    """有使用者自述時先做範疇判斷：不可回答就直接拒答，不進 ReAct 迴圈；判斷結果記成第 0 步供檢視。"""
    if not user_message:
        return await _run_react(question, api_key, usage)

    scope = await _classify_scope(user_message, api_key, usage)
    scope_step = {
        'step':         0,
        'thought':      '先判斷使用者的問題是否屬於知識庫可回答的範疇',
        'action':       'scope_check',
        'action_input': {'user_message': user_message},
        'observation':  f'{scope["scope"]}｜{scope.get("category", "")}｜{scope.get("reason", "")}',
    }
    if scope['scope'] == 'out':
        return REFUSAL_SENTENCE, [scope_step]
    if scope['scope'] == 'error':
        return SCOPE_UNAVAILABLE, [scope_step]
    # 刻意不把「已判定可回答」告訴 ReAct 迴圈：試過加上「不可使用拒答句」的提示，誘導題（問知識庫沒有的
    # 數字、研究、品牌）確實不再被拒答，但幻覺率從 0% 升到 4.6%（開始推薦品牌、不查知識庫就回答）。
    # 寧可偶爾保守拒答。Step 0 仍把關，因為分類器偶爾會漏（例如代問家人懷孕的椅子調整）
    output, steps = await _run_react(question, api_key, usage)
    return output, [scope_step] + steps


def _usage_step(usage: dict) -> dict:
    """把這次回答的 Token 用量記成最後一步（App 不顯示 steps，只供後台與評測統計）。"""
    return {
        'step':         -1,
        'thought':      '本次回答的 OpenAI Token 用量',
        'action':       'token_usage',
        'action_input': dict(usage),
        'observation':  (f'{usage["calls"]} 次呼叫，輸入 {usage["input_tokens"]}（快取 {usage["cached_tokens"]}）、'
                         f'輸出 {usage["output_tokens"]} tokens'),
    }


# ── 防幻覺驗證 ─────────────────────────────────────────────────────────────────

def _validate_response(response: str) -> str:
    """驗證回覆是否包含知識庫來源引用，驗證後移除引用章節再回傳。"""
    has_citation = '📚 參考來源' in response or '參考來源' in response

    for marker in ['📚 參考來源', '參考來源']:
        idx = response.find(marker)
        if idx != -1:
            response = response[:idx].strip()
            break

    # 拒答（規則 3）本來就不會附來源，不該再加「未附來源」警告，否則使用者會看到拒答句後面跟著一段系統提示
    if not has_citation and not _is_refusal(response):
        response += (
            '\n\n---\n⚠️ 系統提示：此回覆未包含知識庫來源引用，'
            '建議僅參考有附出處的資訊，或諮詢專業物理治療師。'
        )
    return response


# ── 對外介面 ───────────────────────────────────────────────────────────────────

def _build_question(posture: str, user_id: int, user_message: str) -> str:
    """
    posture、user_message 至少會有一個非空，三種組合對應不同開場問法：
        只有 posture         → 針對偵測到的坐姿分析
        posture + user_message → 針對偵測到的坐姿 + 使用者補充症狀
        只有 user_message     → 不綁定特定坐姿，純粹依症狀描述回答（Step 1 仍會查詢近期坐姿紀錄輔助判斷）
    """
    posture_name = POSTURE_DISPLAY.get(posture, posture)

    if not posture:
        question = (
            f'使用者 ID：{user_id}\n'
            f'使用者未指定特定坐姿，僅描述症狀：{user_message}\n'
            f'請依 Step 0 判斷：只有明確屬於不可回答範疇時才回覆拒答句；'
            f'其餘先查詢使用者近期坐姿紀錄作為背景資訊，再查詢外部知識庫後回答使用者的問題。'
        )
    elif user_message:
        question = (
            f'使用者 ID：{user_id}\n'
            f'偵測坐姿：「{posture_name}」\n'
            f'使用者自述：{user_message}\n'
            f'請依 Step 0 判斷：只有明確屬於不可回答範疇時才回覆拒答句；'
            f'其餘一律查詢外部知識庫後回答使用者的問題。'
        )
    else:
        question = (
            f'使用者 ID：{user_id}\n'
            f'偵測坐姿：「{posture_name}」\n'
            f'請查詢外部知識庫後分析坐姿問題並提供改善建議。'
        )
    return question


def get_advice(posture: str = '', user_id: int = 0, user_message: str = '') -> tuple[str, list]:
    """
    同步版本，給舊的 POST /api/agent 與每週報告（weekly_advice）使用，內部直接跑非同步版本。
    新的 App 流程請走非同步任務（POST /api/agent/jobs → agent_worker 處理），不佔用網頁伺服器執行緒。
    """
    return asyncio.run(get_advice_async(posture, user_id, user_message))


async def get_advice_async(posture: str = '', user_id: int = 0, user_message: str = '') -> tuple[str, list]:
    """
    回傳 (advice, steps)：
        advice — 最終回覆文字（已通過防幻覺驗證）
        steps  — ReAct 迴圈逐步紀錄（Thought/Action/Observation），供 AgentLog.steps 落地保存

    整段以 asyncio.wait_for 包住：OpenAI／MCP 沒回應時最多等 _LLM_TIMEOUT_SECONDS 秒就放棄，
    不會讓呼叫端無限期等待。
    """
    fake_latency = getattr(settings, 'AGENT_FAKE_LATENCY_SECONDS', 0)
    if fake_latency:
        # 僅供壓力測試：模擬 OpenAI 回應時間，不真的呼叫 OpenAI，避免 1000 次測試請求產生費用
        logger.warning(f'[PhysioAgent] 壓測模式：模擬 {fake_latency} 秒延遲，未呼叫 OpenAI')
        await asyncio.sleep(fake_latency)
        return f'（壓測模式模擬回覆：{POSTURE_DISPLAY.get(posture, posture)}）', []

    question = _build_question(posture, user_id, user_message)

    api_key = settings.OPENAI_API_KEY
    if not api_key:
        raise ValueError('未設定 OPENAI_API_KEY，請確認 .env 檔案')

    usage = _new_usage()
    try:
        output, steps = await asyncio.wait_for(
            _answer(question, user_message, api_key, usage), timeout=_LLM_TIMEOUT_SECONDS)
        logger.info(f'[PhysioAgent] Token 用量：{_usage_step(usage)["observation"]}')
        return _validate_response(output.strip()), steps + [_usage_step(usage)]
    except asyncio.TimeoutError as e:
        logger.error(f'[PhysioAgent] OpenAI 請求逾時（{_LLM_TIMEOUT_SECONDS}秒）')
        raise RuntimeError(ERR_TIMEOUT) from e
    except Exception as e:
        msg = _leaf_error_message(e)
        fatal = _fatal_error(msg)
        if fatal:
            logger.error(f'[PhysioAgent] OpenAI 額度／金鑰錯誤：{msg}')
            raise RuntimeError(fatal) from e
        # 先判斷 OpenAI 連線錯誤，再判斷 MCP：兩者底層都是連線失敗，只有 OpenAI 的會包成 *ConnectionError
        if 'OpenAIConnectionError' in msg or 'APIConnectionError' in msg or 'APITimeoutError' in msg:
            logger.error(f'[PhysioAgent] 無法連線 OpenAI：{msg}')
            raise RuntimeError(ERR_OPENAI) from e
        if any(s in msg for s in ('Connection refused', 'Connect call failed', 'ConnectError', 'getaddrinfo failed')):
            logger.error(f'[PhysioAgent] 無法連線 MCP Server（{settings.MCP_SERVER_HOST}:{settings.MCP_SERVER_PORT}，'
                         f'請確認 mcp 服務是否啟動）：{msg}')
            raise RuntimeError(ERR_MCP) from e
        logger.error(f'[PhysioAgent] Physio Agent 呼叫失敗：{msg}', exc_info=True)
        raise RuntimeError(ERR_UNEXPECTED) from e
