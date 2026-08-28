"""
Physio Agent MCP Server — 獨立、長駐的 MCP 工具服務。

執行方式：
    python manage.py mcp_server

透過 Streamable HTTP 監聽 settings.MCP_SERVER_HOST:MCP_SERVER_PORT，
供 api/physio_agent.py（MCP Client + ReAct 迴圈）連線呼叫。

暴露 4 個工具：
    search_knowledge_base — RAG 知識庫查詢（FAISS + Gemini Embedding）
    get_posture_history   — 個人化背景查詢（身高體重/BMI、坐姿歷史、7天壞坐姿統計）
    trigger_vibration     — 觸發震動馬達（Notification + MotorLog + MQTT）
    web_search            — 網路搜尋補充查詢（Tavily API）
"""

import logging
from collections import Counter
from pathlib import Path

from django.conf import settings
from django.utils import timezone
from datetime import timedelta
from asgiref.sync import sync_to_async
from mcp.server.fastmcp import FastMCP

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
    'empty':     '無人就坐',
}

mcp = FastMCP(
    name='SmartChairPhysioTools',
    host='0.0.0.0',
    port=getattr(settings, 'MCP_SERVER_PORT', 8010),
)

_retriever = None


def _get_all_keys() -> list:
    keys = getattr(settings, 'GEMINI_API_KEYS', [])
    if not keys:
        raise ValueError('未設定任何 GEMINI_API_KEY，請確認 .env 檔案')
    return keys


def _build_retriever():
    """載入外部知識庫並建立 FAISS 向量庫（首次建立後持久化至磁碟）。"""
    global _retriever
    if _retriever is not None:
        return _retriever

    from langchain_community.document_loaders import DirectoryLoader, TextLoader
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    from langchain_community.vectorstores import FAISS
    from langchain_google_genai import GoogleGenerativeAIEmbeddings

    api_key = _get_all_keys()[0]
    embeddings = GoogleGenerativeAIEmbeddings(
        model='models/gemini-embedding-001',
        google_api_key=api_key,
    )

    if (FAISS_DIR / 'index.faiss').exists():
        logger.info('[MCP] 從磁碟載入 FAISS 向量庫...')
        vs = FAISS.load_local(
            str(FAISS_DIR), embeddings,
            allow_dangerous_deserialization=True,
        )
    else:
        logger.info('[MCP] 讀取外部知識庫並建立 FAISS...')
        loader = DirectoryLoader(
            str(KB_DIR), glob='*.txt',
            loader_cls=TextLoader,
            loader_kwargs={'encoding': 'utf-8'},
        )
        docs = loader.load()
        # 排除純參考文獻清單（只有作者/期刊/URL，無實際建議內容，會稀釋檢索品質）
        docs = [d for d in docs if not Path(d.metadata.get('source', '')).stem == '參考資料']
        # chunk_size 拉大到可涵蓋知識庫文件的完整小節（原 400 常把「立即改善動作」清單從中切斷）
        splitter = RecursiveCharacterTextSplitter(chunk_size=700, chunk_overlap=100)
        split_docs = splitter.split_documents(docs)
        vs = FAISS.from_documents(split_docs, embeddings)
        FAISS_DIR.mkdir(parents=True, exist_ok=True)
        vs.save_local(str(FAISS_DIR))
        logger.info(f'[MCP] FAISS 已儲存至磁碟：{FAISS_DIR}')

    _retriever = vs.as_retriever(search_type='mmr', search_kwargs={'k': 4, 'fetch_k': 10})
    return _retriever


# ── MCP Tools ─────────────────────────────────────────────────────────────────

@mcp.tool()
def search_knowledge_base(query: str) -> str:
    """從外部醫學文獻知識庫搜尋坐姿、物理治療相關資訊。回答任何建議前必須先呼叫此工具。"""
    retriever = _build_retriever()
    docs = retriever.invoke(query)
    if not docs:
        return (
            '【知識庫查詢結果：無相關文獻】\n'
            '若問題仍屬「辦公室人體工學／坐姿」範疇，可嘗試呼叫 web_search 補充查詢；\n'
            '否則請直接回覆：「根據目前知識庫，我無法回答此問題，建議諮詢專業醫師或物理治療師。」'
        )
    parts = []
    for i, d in enumerate(docs, 1):
        filename = Path(d.metadata.get('source', '')).stem
        parts.append(f'[文獻{i}｜來源：{filename}.txt]\n{d.page_content}')
    return (
        '【知識庫查詢結果｜請嚴格依此內容回答，不可補充知識庫以外的資訊】\n\n'
        + '\n\n---\n\n'.join(parts)
    )


@mcp.tool()
async def get_posture_history(user_id: int) -> str:
    """
    查詢指定使用者的個人化背景資料，用於提供更貼合個人的建議：
    - 身高體重（BMI）：體型差異會影響人體工學建議的施力與角度
    - 最近 5 筆坐姿紀錄：用於判斷是否持續不良或已有改善
    - 近 7 天壞坐姿統計：用於判斷哪種坐姿問題最頻繁，建議應優先處理
    """
    return await sync_to_async(_get_posture_history_sync)(user_id)


def _get_posture_history_sync(user_id: int) -> str:
    """MCP Server 跑在 async event loop 裡，Django ORM 是 async-unsafe，需透過 sync_to_async 呼叫此函式。"""
    from .models import PostureRecord, User

    parts = []

    # ── 身高體重 ──
    try:
        user = User.objects.get(id=user_id)
        if user.height and user.weight:
            bmi = round(user.weight / ((user.height / 100) ** 2), 1)
            parts.append(f'使用者身高 {user.height:.0f}cm、體重 {user.weight:.0f}kg（BMI {bmi}）。')
        else:
            parts.append('使用者尚未填寫身高體重。')
    except User.DoesNotExist:
        parts.append('查無此使用者。')

    # ── 最近 5 筆坐姿紀錄（趨勢判斷）──
    recent = PostureRecord.objects.filter(user_id=user_id).order_by('-timestamp')[:5]
    if recent.exists():
        lines = [f'- {r.timestamp.strftime("%H:%M")} → {r.posture}' for r in recent]
        parts.append('最近 5 筆坐姿紀錄：\n' + '\n'.join(lines))
    else:
        parts.append('沒有近期坐姿紀錄。')

    # ── 近 7 天壞坐姿統計（頻率判斷）──
    cutoff = timezone.now() - timedelta(days=7)
    week_records = PostureRecord.objects.filter(
        user_id=user_id, timestamp__gte=cutoff,
    ).exclude(posture__in=['normal', 'empty'])
    total = week_records.count()
    if total:
        counts = Counter(week_records.values_list('posture', flat=True))
        stat_lines = [
            f'- {POSTURE_DISPLAY.get(p, p)}：{c} 次（{round(c / total * 100)}%）'
            for p, c in counts.most_common()
        ]
        parts.append(f'近 7 天壞坐姿統計（共 {total} 筆）：\n' + '\n'.join(stat_lines))
    else:
        parts.append('近 7 天無不良坐姿紀錄。')

    return '\n\n'.join(parts)


@mcp.tool()
async def trigger_vibration(user_id: int, posture: str, reason: str) -> str:
    """觸發震動馬達提醒使用者調整坐姿，並回傳已啟動的馬達清單。
    posture: 當前坐姿類別（forward/recline/left/right/sedentary/normal）
    reason: 提醒原因說明（中文）
    回傳值包含啟動馬達清單，請在收到回覆後呼叫 get_posture_history 確認坐姿是否改善。
    """
    return await sync_to_async(_trigger_vibration_sync)(user_id, posture, reason)


def _trigger_vibration_sync(user_id: int, posture: str, reason: str) -> str:
    """MCP Server 跑在 async event loop 裡，Django ORM 是 async-unsafe，需透過 sync_to_async 呼叫此函式。"""
    from .models import Notification, MotorLog
    from .mqtt_publisher import publish_motor_command
    from .motor_constants import MOTOR_MAP

    motors = MOTOR_MAP.get(posture, [])
    Notification.objects.create(user_id=user_id, message=f'坐姿提醒：{reason}')
    if motors:
        MotorLog.objects.create(
            user_id=user_id,
            posture=posture,
            motors=motors,
            reason=reason,
        )
        publish_motor_command(motors)
    logger.info(f'[MCP] 震動提醒已建立 user_id={user_id} motors={motors} reason={reason}')
    if motors:
        return (
            f'【震動馬達已觸發】啟動馬達：{", ".join(motors)} | 原因：{reason}\n'
            f'→ 請呼叫 get_posture_history(user_id={user_id}) 觀察坐姿是否在最新紀錄中出現改善。'
        )
    return f'【提醒已送出（{posture} 無需震動）】原因：{reason}'


@mcp.tool()
def web_search(query: str) -> str:
    """
    網路搜尋補充查詢，僅在 search_knowledge_base 查無相關文獻、
    但問題仍屬「辦公室人體工學／坐姿」範疇時才可呼叫。
    嚴禁用於藥物、手術、疾病診斷等超出知識庫範疇的問題（該類問題應直接拒答，而非改用網路搜尋）。
    """
    api_key = getattr(settings, 'TAVILY_API_KEY', '')
    if not api_key:
        return '【網路搜尋暫時無法使用：未設定 TAVILY_API_KEY】請僅依知識庫內容回答，或告知使用者無法回答此問題。'

    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=api_key)
        result = client.search(query, max_results=3)
    except Exception as e:
        logger.warning(f'[MCP] Tavily 搜尋失敗：{e}')
        return f'【網路搜尋失敗：{e}】請僅依知識庫內容回答，或告知使用者無法回答此問題。'

    hits = result.get('results', [])
    if not hits:
        return '【網路搜尋結果：無相關資訊】'

    parts = [
        f'[網路來源{i}｜{h.get("title", "")}｜{h.get("url", "")}]\n{h.get("content", "")}'
        for i, h in enumerate(hits, 1)
    ]
    return (
        '【網路搜尋結果｜僅可作為知識庫的補充說明，仍須遵守防幻覺與知識邊界規則】\n\n'
        + '\n\n---\n\n'.join(parts)
    )
