"""
Physio Agent — 物理治療師 AI 助手

架構：
  人體工學知識庫（6 種坐姿 + 通用知識）
      ↓ LangChain RecursiveCharacterTextSplitter 切分
      ↓ Google Embedding（models/gemini-embedding-001）向量化
      ↓ FAISS 本地向量庫儲存與檢索
      ↓ Gemini 2.0 Flash 生成個人化建議

知識來源：
  參考 Mayo Clinic、Cleveland Clinic、Physiopedia、NHS 等醫療機構資料，
  結合人體工學與物理治療學術文獻編寫。
"""

import logging
from functools import lru_cache

from django.conf import settings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
from langchain_community.vectorstores import FAISS
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain_core.documents import Document

logger = logging.getLogger(__name__)

# ── 坐姿顯示名稱 ───────────────────────────────────────────────────────────────

POSTURE_DISPLAY = {
    'normal':    '標準坐姿',
    'left':      '身體左傾',
    'right':     '身體右傾',
    'forward':   '頭部前傾（烏龜頸）',
    'recline':   '過度後仰',
    'sedentary': '久坐未動',
}

# ── 人體工學知識庫 ─────────────────────────────────────────────────────────────
# 參考 Mayo Clinic、Cleveland Clinic、Physiopedia、NHS 等醫療機構資料

KNOWLEDGE_DOCS = [
    Document(
        page_content="""標準坐姿（正確辦公坐姿要點）
來源參考：Mayo Clinic - Office ergonomics / Cleveland Clinic - Back Pain Prevention

正確坐姿的五大要素：
1. 脊椎對齊：保持腰椎自然前凸（S型曲線），使用腰枕支撐腰部，避免駝背或過度後仰。
2. 雙腳支撐：雙腳平放地面，膝關節彎曲約90度，必要時使用腳踏板。
3. 螢幕位置：螢幕頂端與眼睛等高，距離50-70公分，避免頸部長期彎曲。
4. 手臂位置：手肘彎曲90度，前臂與桌面平行，肩膀自然下垂不聳肩。
5. 動態坐姿：每坐30-45分鐘起身活動3-5分鐘，靜態姿勢是最大傷害來源。

維持良好坐姿的好處：
- 預防頸椎病、腰椎間盤突出、肩頸肌筋膜炎等職業病
- 減少背部疼痛，提高工作效率
- 改善血液循環，降低疲勞感
""",
        metadata={"posture": "normal", "source": "Mayo Clinic / Cleveland Clinic", "topic": "correct_posture"}
    ),
    Document(
        page_content="""身體左傾的健康風險與改善（身體側傾 Body Lateral Tilt）
來源參考：Physiopedia - Scoliosis / NHS - Back pain at work

健康風險：
- 脊椎不對稱受力，長期可能導致功能性脊椎側彎
- 左側腰方肌（Quadratus Lumborum）過度緊縮，右側過度拉伸，造成肌肉失衡
- 左側髖關節及薦髂關節（SI Joint）承受額外壓力
- 可能引發左肩、左頸部慢性疼痛，甚至單側頭痛

常見原因：
- 螢幕或文件偏向一側
- 習慣性交叉腿
- 椅子高度不對稱
- 身體疲勞時的補償姿勢

立即改善動作：
1. 坐正，將身體重量均勻分配到左右坐骨
2. 將螢幕及工作文件移至正前方
3. 雙腳平放地面，避免交叉腿
4. 側向伸展（Lateral Stretch）：頭頸向右輕傾，左手往下伸，維持15秒，重複3次

長期預防：
- 每週2-3次側向核心訓練（Side Plank）
- 定期按摩左側腰部及臀部緊繃肌肉
""",
        metadata={"posture": "left", "source": "Physiopedia / NHS", "topic": "lateral_tilt"}
    ),
    Document(
        page_content="""身體右傾的健康風險與改善
來源參考：Physiopedia - Postural Assessment / Cleveland Clinic - Neck Pain

健康風險：
- 右側頸肩慢性疼痛，常見於長時間用右手操作滑鼠者
- 右側腰方肌與豎脊肌過度緊張，左側拮抗肌弱化
- 脊椎右側椎間盤承受不均勻壓力
- 可能發展為右側坐骨神經痛

常見原因：
- 滑鼠放置過遠或偏右
- 習慣夾電話於右肩與耳朵之間
- 習慣性右腿翹腿

立即改善動作：
1. 將滑鼠移至靠近身體正前方
2. 使用無線耳機或耳麥取代夾電話
3. 側向伸展（向左側）：頭頸向左輕傾，右手往下伸，維持15秒，重複3次
4. 坐正，確認左右坐骨均等受力

長期預防：
- 加強左側核心肌群訓練平衡肌力
- 考慮改為左手使用滑鼠（輪流使用可預防重複性傷害）
- 設定站立辦公時段，讓肌肉有機會恢復平衡
""",
        metadata={"posture": "right", "source": "Physiopedia / Cleveland Clinic", "topic": "right_lateral_tilt"}
    ),
    Document(
        page_content="""頭部前傾（烏龜頸 / Forward Head Posture）
來源參考：Physiopedia - Forward Head Posture / Mayo Clinic - Neck Pain / PubMed - Cervical Spine

健康風險與機制：
- 頭部每前移2.5公分，頸椎負擔增加約4-5公斤（頭重約5-6公斤）
- 長期造成頸椎曲度逆轉（頸椎反弓）
- 上斜方肌、提肩胛肌過度緊張；深層頸屈肌（Deep Cervical Flexors）弱化
- 可能引發：頸因性頭痛（Cervicogenic Headache）、上肢麻木、肩夾擠症候群

常見原因：
- 螢幕位置過低或過遠
- 視力不足導致本能前傾
- 手機低頭使用（Text Neck）

立即改善動作：
1. 頸部縮回（Chin Tuck）：下巴水平向後縮，感覺後頸被拉長，維持5秒，每小時10次
2. 螢幕提高至眼睛等高，或後移至50-70cm
3. 肩胛骨夾緊（Scapular Retraction）：雙肩向後夾，維持5秒，重複10次
4. 胸大肌伸展：雙手扶門框，身體微前傾，維持30秒

長期預防：
- 每天訓練深層頸屈肌（頸部縮回配合輕阻力）
- 使用文件架將紙本文件提高，減少低頭
- 眼鏡度數定期更新，視力不足是主因之一
""",
        metadata={"posture": "forward", "source": "Physiopedia / Mayo Clinic / PubMed", "topic": "forward_head_posture"}
    ),
    Document(
        page_content="""過度後仰（Excessive Recline / Slouching）
來源參考：Cleveland Clinic - Back Pain / NHS - Sitting and lower back pain

健康風險：
- 腰椎承受剪力（Shear Force），增加L4-L5及L5-S1椎間盤壓力
- 腹部核心肌群（腹橫肌、多裂肌）無法有效啟動，長期弱化
- 後仰常伴隨頸部代償性前伸，形成複合性不良姿勢
- 髖屈肌（Iliopsoas）長期縮短，引發下背痛

常見原因：
- 椅背過於直立或不符合身體曲線
- 下午疲勞時的無意識放鬆
- 椅子高度過高，雙腳無法平放

立即改善動作：
1. 坐直，啟動核心：輕輕收緊腹部（約30%力道），感覺腰椎微微前凸
2. 使用腰枕（Lumbar Support）填補腰部與椅背的空隙
3. 調整椅背角度至95-110度（微後傾是正常的，但不超過110度）
4. 骨盆傾斜練習（Pelvic Tilt）：坐姿下輕輕前後搖動骨盆，喚醒腰椎感知

長期預防：
- 每天訓練核心穩定肌群（Bird-Dog、Dead Bug 等低衝擊動作）
- 選擇有良好腰部支撐的人體工學椅
- 下午設定鬧鐘提醒，疲勞是後仰的主要觸發點
""",
        metadata={"posture": "recline", "source": "Cleveland Clinic / NHS", "topic": "excessive_recline"}
    ),
    Document(
        page_content="""久坐未動（Prolonged Sitting / Physical Inactivity）
來源參考：WHO - Physical Activity Guidelines / Mayo Clinic - Sitting Risks / Physiopedia - Sedentary Behaviour

健康風險（世界衛生組織 WHO 研究）：
- 久坐被列為全球第四大致死風險因子
- 持續靜坐超過30分鐘，臀大肌、股四頭肌血流量下降，肌肉開始抑制（Muscle Inhibition）
- 每增加1小時靜坐，第二型糖尿病風險上升22%（PubMed Meta-Analysis）
- 下肢靜脈血液回流減慢，增加深層靜脈血栓（DVT）風險
- 與心血管疾病、代謝症候群、特定癌症（大腸癌、乳癌）風險上升相關

重要發現：
- 即使每天運動1小時，若其餘時間久坐超過8小時，健康效益仍大幅降低
- 「動態坐姿」（頻繁小幅度移動）比維持完美靜態坐姿更有益健康

立即改善動作：
1. 立刻站起來，做5-10次深蹲或踮腳運動，活化下肢肌群
2. 原地踏步或步行至飲水機、廁所等，增加步數
3. 站立工作5-10分鐘（若有升降桌）

長期預防：
- 每30分鐘設定鬧鐘提醒起身活動3分鐘（Pomodoro 技巧結合起身）
- 開立即時訊息時改為站立或走動
- 考慮使用升降桌，每天站立累積2-4小時
- 午休時間步行至少10分鐘
""",
        metadata={"posture": "sedentary", "source": "WHO / Mayo Clinic / Physiopedia", "topic": "sedentary_behaviour"}
    ),
    Document(
        page_content="""辦公室簡易伸展操（適用所有坐姿問題）
來源參考：NHS - Exercises for back pain / Cleveland Clinic - Stretching Basics

每小時建議的伸展動作（各10-15秒）：

頸部：
- 頸部縮回（Chin Tuck）：下巴後縮，感覺後頸拉長 × 10次
- 頸側伸展：頭向右傾，左手輕壓頭部，換邊 × 各15秒

肩膀：
- 肩膀繞環：雙肩向前/向後緩慢繞圈 × 各10次
- 胸口伸展：雙手十指交扣置於背後，挺胸 × 15秒

腰背：
- 貓牛式（椅上版）：坐姿下骨盆前傾（腰前凸）與後傾（腰後縮）交替 × 10次
- 側向伸展：坐姿下右手舉高，身體向左側彎，換邊 × 各15秒

下肢：
- 踮腳運動：雙腳踮起放下 × 20次（促進下肢血液循環）
- 膝蓋伸直：坐姿下輪流將膝蓋伸直維持5秒，活化股四頭肌

以上動作無需離開座位，每小時一輪，預防肌肉緊張與職業傷害。
""",
        metadata={"posture": "all", "source": "NHS / Cleveland Clinic", "topic": "office_stretching"}
    ),
]

# ── Prompt 模板 ────────────────────────────────────────────────────────────────

_PROMPT_TEMPLATE = """你是一位專業的物理治療師 AI 助手，名叫「姿康（PhysioBot）」。
你擅長辦公室人體工學與職業傷害預防，依據實證醫學（Mayo Clinic、Cleveland Clinic、Physiopedia 等）提供建議。

【相關醫學知識】
{context}

【問題】
{question}

請依以下格式回覆（使用繁體中文，語氣友善而專業）：

⚠️ 問題分析
（用2-3句說明此坐姿的危害）

✅ 立即改善（3個具體動作，附說明）
1.
2.
3.

💪 長期預防
（1-2句預防建議）

⏰ 提醒
（一句溫馨提醒）
"""

# ── RAG 初始化（Lazy，只在第一次呼叫時建立）────────────────────────────────────

_chain = None


def _build_chain():
    global _chain
    if _chain is not None:
        return _chain

    api_key = settings.GEMINI_API_KEY
    if not api_key:
        raise ValueError('GEMINI_API_KEY 未設定，請確認 .env 檔案')

    logger.info('[PhysioAgent] 初始化 FAISS 向量庫...')

    embeddings = GoogleGenerativeAIEmbeddings(
        model='models/gemini-embedding-001',
        google_api_key=api_key,
    )

    splitter = RecursiveCharacterTextSplitter(chunk_size=400, chunk_overlap=50)
    split_docs = splitter.split_documents(KNOWLEDGE_DOCS)

    vector_store = FAISS.from_documents(split_docs, embeddings)
    retriever = vector_store.as_retriever(search_kwargs={'k': 3})

    llm = ChatGoogleGenerativeAI(
        model='gemini-2.5-flash',
        google_api_key=api_key,
        temperature=0.7,
    )

    prompt = PromptTemplate(
        template=_PROMPT_TEMPLATE,
        input_variables=['context', 'question'],
    )

    def _format_docs(docs):
        return '\n\n'.join(d.page_content for d in docs)

    _chain = (
        {'context': retriever | _format_docs, 'question': RunnablePassthrough()}
        | prompt
        | llm
        | StrOutputParser()
    )

    logger.info('[PhysioAgent] 初始化完成')
    return _chain


# ── 對外介面 ───────────────────────────────────────────────────────────────────

def get_advice(posture: str, user_message: str = '') -> str:
    """
    依據偵測到的坐姿，從知識庫檢索相關資訊，並用 Gemini 生成建議。

    Args:
        posture: 坐姿類別（normal / left / right / forward / recline / sedentary）
        user_message: 使用者額外描述的症狀或問題（可選）

    Returns:
        建議文字（繁體中文）
    """
    posture_name = POSTURE_DISPLAY.get(posture, posture)

    if user_message:
        question = (
            f'我目前的坐姿是「{posture_name}」，'
            f'我的狀況是：{user_message}。'
            f'請給我針對這個坐姿問題的改善建議。'
        )
    else:
        question = (
            f'我目前的坐姿是「{posture_name}」，'
            f'請分析這個坐姿的問題，並給我具體的改善建議與預防方法。'
        )

    try:
        chain = _build_chain()
        return chain.invoke(question).strip()
    except Exception as e:
        logger.error(f'[PhysioAgent] 生成建議失敗：{e}')
        raise
