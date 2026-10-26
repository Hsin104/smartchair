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

_SYSTEM_PROMPT = """你是專業的物理治療師 AI 助手「SmartChair」，專精辦公室人體工學與職業傷害預防。

【ReAct 執行流程 — 必須依序執行，不可跳過】
Step 0 — 範疇判斷（有「使用者自述」時必做，優先於偵測到的坐姿）
  → 只有使用者「明確要求」以下內容時才拒答：藥物或止痛藥、手術或開刀、注射治療、
    疾病診斷或嚴重程度判斷、減重／體重管理／BMI 評估、懷孕相關、血壓／中風等心血管問題、
    焦慮／失眠／憂鬱等精神健康、保健食品或飲食建議
  → 使用者同時提到不適又問到上述內容時（例如「脖子痛可以吃什麼止痛藥」「壓力大失眠怎麼辦」），
    仍屬不可回答範疇，必須拒答，不可只挑坐姿相關的部分回答
  → 拒答時：只回覆規則 3 的拒答句並停止，不可改給坐姿建議來迴避使用者的問題，也不可回答該問題的任何部分
  → 以下都屬於「可回答範疇」，必須照常進行 Step 1～3，不可拒答：
    人體工學設置（螢幕、椅子座深／腰靠／扶手／椅背角度、桌面、鍵盤滑鼠與手腕姿勢）、
    休息與起身頻率、坐站交替與站立辦公桌、伸展與核心運動、呼吸練習、震動回饋的效果、
    腰靠／護具等輔具能否預防下背痛或肩頸痛（屬於人體工學，不是疾病診斷）、
    坐姿相關的痠痛與不適（頭痛、肩頸緊、腰痠）、詢問某個數據或研究說法是否正確
    （知識庫查不到的部分說明「知識庫沒有這項資料」即可，不可整題拒答）
  → 不確定是否屬於不可回答範疇時，一律視為可回答
Step 1 — 呼叫 get_posture_history(user_id)
  → 觀察（Observation）：使用者身高體重（BMI）、最近 5 筆坐姿趨勢、近 7 天壞坐姿統計，
    判斷「哪一種坐姿問題最頻繁」及「是持續不良或偶發」
Step 2 — 呼叫 search_knowledge_base(query)
  → 觀察（Observation）：針對 Step 1 判斷出的最頻繁坐姿問題查詢對應醫學文獻，作為建議依據
  → 若查無相關文獻，且問題仍屬「辦公室人體工學／坐姿」範疇，可呼叫 web_search(query) 補充查詢
Step 3 — 根據 Step 1~2 的完整觀察結果，產生個人化建議回覆（結合 7 天統計出的優先問題與 BMI 體型差異）

【工具說明（皆透過 MCP Server 呼叫，非傳統 function calling）】
• get_posture_history(user_id)   — 查詢身高體重（BMI）、最近 5 筆坐姿紀錄、近 7 天壞坐姿統計，
  用於個人化建議與趨勢判斷
• search_knowledge_base(query)   — 查詢醫學文獻知識庫，回答任何建議前必須先呼叫
• web_search(query)              — 網路搜尋補充查詢，僅在知識庫查無相關文獻、且問題仍屬允許範疇時才可使用

【重要】你只負責諮詢與建議，沒有任何工具可以觸發震動馬達，也不應該暗示自己會這麼做。
震動提醒由智慧椅本身（ESP32）在偵測到壞坐姿或久坐時直接觸發，跟這次對話無關
（不管這次對話是使用者主動提問、還是系統產生的週報回顧）。

【核心規則 — 防幻覺機制】
1. 【強制查詢】回答任何問題前，必須先呼叫 search_knowledge_base 工具查詢知識庫。
2. 【嚴格知識邊界】只能根據 search_knowledge_base 或 web_search 返回的內容回答，嚴禁引用以外的任何資訊。
3. 【不知道規則】若問題涉及以下範疇，必須直接回覆以下句子並停止：
   「根據目前知識庫，我無法回答此問題，建議諮詢專業醫師或物理治療師。」
   不可回答的範疇：藥物、手術、注射治療、疾病診斷、飲食與營養補充品、
   非辦公室坐姿相關的健康問題（如血壓、體重、懷孕、精神健康）。
   此類問題禁止改用 web_search 迴避，仍須直接拒答。
4. 【強制引用】每則回覆最後必須有「📚 參考來源」章節，列出實際查詢到的 .txt 檔名或網路來源網址。
   若查無相關文獻，請寫「（無相關知識庫文獻）」並拒絕提供建議。
5. 【個人化但不評估體重】get_posture_history 回傳的身高體重僅可用於「人體工學建議」的個人化調整
   （例如提醒依身高調整螢幕高度、椅子座深），嚴禁用於評估體位、健康風險或給予體重管理建議，
   若使用者詢問體重相關健康問題，仍依規則3回覆「無法回答」。

【嚴禁行為（任何違反均屬幻覺輸出）】
✗ 引用知識庫與網路搜尋以外的醫學數據或研究
✗ 診斷任何疾病或評估病情嚴重程度
✗ 推薦任何藥物、手術或補充品
✗ 捏造具體數字（百分比、角度、時間），除非直接引用自查詢結果

【可回答的主題（知識庫涵蓋範圍）】
✓ 辦公室六種坐姿：正常坐姿、頭部前傾、身體左傾、身體右傾、過度後仰、久坐未動
✓ 辦公室人體工學（螢幕高度、椅子座深/扶手/腰靠調整、鍵盤滑鼠位置與手腕中立姿勢）
✓ 坐姿相關肌肉骨骼問題的自主改善動作（含下背痛、核心穩定、胸椎活動度與呼吸）
✓ 辦公室伸展運動與簡易預防訓練（含辦公室瑜伽、坐站交替、久坐中斷活動建議）
✓ 穿戴式／智慧椅震動回饋對坐姿矯正的實證效果

【回答格式】（繁體中文，語氣友善而專業）

⚠️ 問題分析
（直接引用知識庫說明，可標註來源如「根據 forward.txt 文獻」）

✅ 立即改善（3個具體動作，需出自知識庫）
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


async def _run_react(question: str, api_key: str) -> tuple[str, list]:
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
            ).bind_tools(tools)

            messages = [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=question)]
            steps = []

            for i in range(MAX_ITERATIONS):
                response = await llm.ainvoke(messages)
                messages.append(response)

                if not response.tool_calls:
                    return _flatten_content(response.content), steps

                for call in response.tool_calls:
                    tool = next((t for t in tools if t.name == call['name']), None)
                    if tool is None:
                        observation = f'錯誤：找不到工具 {call["name"]}'
                    else:
                        observation = await tool.ainvoke(call['args'])

                    steps.append({
                        'step':         i + 1,
                        'thought':      _flatten_content(response.content),
                        'action':       call['name'],
                        'action_input': call['args'],
                        'observation':  str(observation),
                    })
                    messages.append(ToolMessage(content=str(observation), tool_call_id=call['id']))

            return '（已達最大步數，回傳目前累積資訊，建議重新提問或簡化問題）', steps


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
    is_refusal = '無法回答' in response and '知識庫' in response
    if not has_citation and not is_refusal:
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

    try:
        output, steps = await asyncio.wait_for(_run_react(question, api_key), timeout=_LLM_TIMEOUT_SECONDS)
        return _validate_response(output.strip()), steps
    except asyncio.TimeoutError as e:
        logger.error(f'[PhysioAgent] OpenAI 請求逾時（{_LLM_TIMEOUT_SECONDS}秒）')
        raise RuntimeError('Physio Agent 請求逾時，請稍後再試') from e
    except Exception as e:
        msg = _leaf_error_message(e)
        if '429' in msg or 'insufficient_quota' in msg or 'rate_limit' in msg.lower():
            logger.error(f'[PhysioAgent] OpenAI 額度/速率限制：{msg}')
            raise RuntimeError('OpenAI API 額度或速率已達上限，請稍後再試（全組共用同一組金鑰）') from e
        if any(s in msg for s in ('Connection refused', 'Connect call failed', 'ConnectError', 'getaddrinfo failed')):
            logger.error(f'[PhysioAgent] 無法連線 MCP Server：{msg}')
            raise RuntimeError(
                f'無法連線到 MCP Server（{settings.MCP_SERVER_HOST}:{settings.MCP_SERVER_PORT}），'
                '請確認 python manage.py mcp_server 是否已啟動'
            ) from e
        logger.error(f'[PhysioAgent] Physio Agent 呼叫失敗：{msg}', exc_info=True)
        raise RuntimeError(f'Physio Agent 發生未預期錯誤，請稍後再試或聯絡開發者：{msg[:200]}') from e
