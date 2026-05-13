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
from langchain.agents import create_tool_calling_agent, AgentExecutor

logger = logging.getLogger(__name__)

BASE_DIR  = Path(__file__).resolve().parent.parent
KB_DIR    = BASE_DIR / 'knowledge_base'
FAISS_DIR = BASE_DIR / 'faiss_index'

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

    if FAISS_DIR.exists():
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
        return '知識庫中沒有找到相關文獻，建議諮詢專業物理治療師。'
    parts = []
    for i, d in enumerate(docs, 1):
        filename = Path(d.metadata.get('source', '')).stem
        parts.append(f'[文獻{i}｜檔案：{filename}]\n{d.page_content}')
    return '\n\n'.join(parts)


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

_SYSTEM_PROMPT = """你是專業的物理治療師 AI 助手「姿康（PhysioBot）」，專精辦公室人體工學與職業傷害預防。

【工作規則】
1. 回答坐姿問題前，必須先呼叫 search_knowledge_base 工具查詢外部醫學文獻知識庫。
2. 若問題中說明需要觸發震動提醒，必須呼叫 trigger_vibration 工具通知使用者。
3. 可呼叫 get_posture_history 查詢使用者歷史坐姿，提供更個人化的建議。
4. 只能根據知識庫文獻內容回答，若文獻不足請明確說明「目前資料庫中沒有足夠資訊，建議諮詢專業物理治療師」，不可自行捏造。
5. 回答最後必須列出引用的文獻檔名作為參考來源。

【回答格式】（繁體中文，語氣友善而專業）

⚠️ 問題分析
（根據文獻說明此坐姿的危害）

✅ 立即改善（3個具體動作，附操作說明）
1.
2.
3.

💪 長期預防
（根據文獻的預防訓練建議）

⏰ 提醒
（一句溫馨提醒）

📚 參考來源
（列出文獻檔名，例如：forward.txt、stretching.txt）"""


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
        temperature=0.7,
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
        return result['output'].strip()
    except Exception as e:
        logger.error(f'[PhysioAgent] 生成建議失敗：{e}')
        raise
