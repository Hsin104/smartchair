"""
Physio Agent — 完整 Agent 架構（四大核心模組）

大腦（LLM）  : Gemini 2.5 Flash + 領域專精 Prompt 設計
記憶（Memory）: 外部知識庫（knowledge_base/*.txt）→ FAISS 向量庫（持久化至磁碟）
工具（Tools） : Function Calling — 知識庫搜尋、歷史查詢、震動觸發
行動（Action）: Agent 自主決定是否觸發震動馬達通知
"""

import logging
from pathlib import Path

from django.conf import settings
from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain_core.tools import tool
from langchain_core.prompts import ChatPromptTemplate
from langchain_classic.agents import create_tool_calling_agent, AgentExecutor

logger = logging.getLogger(__name__)

BASE_DIR  = Path(__file__).resolve().parent.parent
KB_DIR    = BASE_DIR / 'knowledge_base'
FAISS_DIR = Path.home() / 'smartchair_faiss'  # 避免路徑含中文導致 FAISS C++ 函式庫失敗

POSTURE_DISPLAY = {
    'normal':    '標準坐姿',
    'left':      '身體左傾',
    'right':     '身體右傾',
    'forward':   '頭部前傾（烏龜頸）',
    'recline':   '過度後仰',
    'sedentary': '久坐未動',
}

_retriever     = None
_agent_executor = None


def _get_api_key():
    api_key = settings.GEMINI_API_KEY
    if not api_key:
        raise ValueError('GEMINI_API_KEY 未設定，請確認 .env 檔案')
    return api_key


def _build_retriever():
    """載入外部知識庫並建立 FAISS 向量庫（首次建立後持久化至磁碟）。"""
    global _retriever
    if _retriever is not None:
        return _retriever

    api_key = _get_api_key()
    embeddings = GoogleGenerativeAIEmbeddings(
        model='models/gemini-embedding-001',
        google_api_key=api_key,
    )

    if (FAISS_DIR / 'index.faiss').exists():
        logger.info('[PhysioAgent] 從磁碟載入 FAISS 向量庫...')
        vs = FAISS.load_local(
            str(FAISS_DIR), embeddings,
            allow_dangerous_deserialization=True,
        )
    else:
        logger.info('[PhysioAgent] 讀取外部知識庫並建立 FAISS...')
        loader = DirectoryLoader(
            str(KB_DIR), glob='*.txt',
            loader_cls=TextLoader,
            loader_kwargs={'encoding': 'utf-8'},
        )
        docs = loader.load()
        splitter = RecursiveCharacterTextSplitter(chunk_size=400, chunk_overlap=50)
        split_docs = splitter.split_documents(docs)
        vs = FAISS.from_documents(split_docs, embeddings)
        FAISS_DIR.mkdir(parents=True, exist_ok=True)
        vs.save_local(str(FAISS_DIR))
        logger.info(f'[PhysioAgent] FAISS 已儲存至磁碟：{FAISS_DIR}')

    _retriever = vs.as_retriever(search_kwargs={'k': 3})
    return _retriever


# ── Tools（Function Calling）─────────────────────────────────────────────────

@tool
def search_knowledge_base(query: str) -> str:
    """從外部醫學文獻知識庫搜尋坐姿、物理治療相關資訊。回答任何建議前必須先呼叫此工具。"""
    retriever = _build_retriever()
    docs = retriever.invoke(query)
    if not docs:
        return (
            '【知識庫查詢結果：無相關文獻】\n'
            '此問題超出本系統知識庫範疇，請直接回覆：\n'
            '「根據目前知識庫，我無法回答此問題，建議諮詢專業醫師或物理治療師。」'
        )
    parts = []
    for i, d in enumerate(docs, 1):
        filename = Path(d.metadata.get('source', '')).stem
        parts.append(f'[文獻{i}｜來源：{filename}.txt]\n{d.page_content}')
    return (
        '【知識庫查詢結果｜請嚴格依此內容回答，不可補充知識庫以外的資訊】\n\n'
        + '\n\n---\n\n'.join(parts)
    )


@tool
def get_posture_history(user_id: int) -> str:
    """查詢指定使用者最近 5 筆坐姿紀錄，用於判斷是否持續不良或已有改善。"""
    from .models import PostureRecord
    records = PostureRecord.objects.filter(user_id=user_id).order_by('-timestamp')[:5]
    if not records.exists():
        return '沒有歷史坐姿紀錄。'
    lines = [f'- {r.timestamp.strftime("%H:%M")} → {r.posture}' for r in records]
    return '最近 5 筆坐姿紀錄：\n' + '\n'.join(lines)


@tool
def trigger_vibration(user_id: int, reason: str) -> str:
    """觸發震動馬達提醒使用者調整坐姿。reason 為提醒原因（如：身體左傾）。"""
    from .models import Notification
    Notification.objects.create(user_id=user_id, message=f'坐姿提醒：{reason}')
    logger.info(f'[PhysioAgent] 震動提醒已建立 user_id={user_id} reason={reason}')
    return f'已建立震動提醒通知：{reason}'


# ── System Prompt ──────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """你是專業的物理治療師 AI 助手「SC）」，專精辦公室人體工學與職業傷害預防。

【核心規則 — 防幻覺機制】
1. 【強制查詢】回答任何問題前，必須先呼叫 search_knowledge_base 工具查詢知識庫。
2. 【嚴格知識邊界】只能根據 search_knowledge_base 返回的文獻內容回答，嚴禁引用知識庫以外的任何資訊，即使聽起來合理也不可加入。
3. 【不知道規則】若問題涉及以下範疇，必須直接回覆以下句子並停止，不可嘗試回答：
   「根據目前知識庫，我無法回答此問題，建議諮詢專業醫師或物理治療師。」
   不可回答的範疇：藥物、手術、注射治療、疾病診斷或病情評估、飲食與營養補充品、
   非辦公室坐姿相關的健康問題（如血壓、體重、懷孕、精神健康）。
4. 【強制引用】每則回覆最後必須有「📚 參考來源」章節，列出實際查詢到的 .txt 檔名。
   若查無相關文獻，請寫「（無相關知識庫文獻）」並拒絕提供建議。
5. 【震動提醒】偵測到非正常坐姿時，必須呼叫 trigger_vibration 工具。
6. 【歷史查詢】可呼叫 get_posture_history 了解使用者過往坐姿，提供個人化建議。

【嚴禁行為（任何違反均屬幻覺輸出）】
✗ 引用知識庫文獻以外的醫學數據或研究
✗ 診斷任何疾病或評估病情嚴重程度
✗ 推薦任何藥物、手術或補充品
✗ 捏造具體數字（百分比、角度、時間），除非直接引用自文獻
✗ 在知識庫無依據下提供「聽起來合理」的建議

【可回答的主題（知識庫涵蓋範圍）】
✓ 辦公室六種坐姿：正常坐姿、頭部前傾、身體左傾、身體右傾、過度後仰、久坐未動
✓ 辦公室人體工學（螢幕高度、椅子設定、鍵盤滑鼠位置）
✓ 坐姿相關肌肉骨骼問題的自主改善動作
✓ 辦公室伸展運動與簡易預防訓練

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


# ── Agent 初始化 ───────────────────────────────────────────────────────────────

def _build_agent():
    global _agent_executor
    if _agent_executor is not None:
        return _agent_executor

    api_key = _get_api_key()
    _build_retriever()

    llm = ChatGoogleGenerativeAI(
        model='gemini-2.5-flash',
        google_api_key=api_key,
        temperature=0.2,  # 降低隨機性，減少幻覺產生機率
    )

    tools = [search_knowledge_base, get_posture_history, trigger_vibration]

    prompt = ChatPromptTemplate.from_messages([
        ('system', _SYSTEM_PROMPT),
        ('human', '{input}'),
        ('placeholder', '{agent_scratchpad}'),
    ])

    agent = create_tool_calling_agent(llm, tools, prompt)
    _agent_executor = AgentExecutor(
        agent=agent, tools=tools,
        verbose=True, max_iterations=5,
    )

    logger.info('[PhysioAgent] Agent 初始化完成')
    return _agent_executor


# ── 防幻覺驗證 ─────────────────────────────────────────────────────────────────

def _validate_response(response: str) -> str:
    """驗證回覆是否包含知識庫來源引用，驗證後移除引用章節再回傳。"""
    has_citation = '📚 參考來源' in response or '參考來源' in response

    # 移除參考來源章節（不對使用者顯示）
    for marker in ['📚 參考來源', '參考來源']:
        idx = response.find(marker)
        if idx != -1:
            response = response[:idx].strip()
            break

    if not has_citation:
        response += (
            '\n\n---\n⚠️ 系統提示：此回覆未包含知識庫來源引用，'
            '建議僅參考有附出處的資訊，或諮詢專業物理治療師。'
        )
    return response


# ── 對外介面 ───────────────────────────────────────────────────────────────────

def get_advice(posture: str, user_id: int, user_message: str = '', trigger_action: bool = False) -> str:
    """
    透過 Agent 查詢外部知識庫並生成坐姿改善建議。

    Args:
        posture        : 坐姿類別（normal / left / right / forward / recline / sedentary）
        user_id        : 使用者 ID（Agent 用於查詢歷史紀錄與觸發震動）
        user_message   : 使用者額外自述症狀（可選）
        trigger_action : True = 自動偵測模式（ESP32），Agent 會觸發震動提醒
    """
    posture_name = POSTURE_DISPLAY.get(posture, posture)

    vibration_note = (
        '\n請同時呼叫 trigger_vibration 工具觸發震動馬達提醒使用者。'
        if trigger_action and posture != 'normal'
        else ''
    )

    if user_message:
        question = (
            f'使用者 ID：{user_id}\n'
            f'偵測坐姿：「{posture_name}」\n'
            f'使用者自述：{user_message}\n'
            f'請查詢外部知識庫後提供改善建議。{vibration_note}'
        )
    else:
        question = (
            f'使用者 ID：{user_id}\n'
            f'偵測坐姿：「{posture_name}」\n'
            f'請查詢外部知識庫後分析坐姿問題並提供改善建議。{vibration_note}'
        )

    try:
        executor = _build_agent()
        result = executor.invoke({'input': question})
        output = result['output']
        if isinstance(output, list):
            parts = []
            for item in output:
                if isinstance(item, dict):
                    parts.append(item.get('text', ''))
                elif isinstance(item, str):
                    parts.append(item)
            output = ''.join(parts)
        return _validate_response(output.strip())
    except Exception as e:
        logger.error(f'[PhysioAgent] 生成建議失敗：{e}')
        raise
