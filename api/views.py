import os
from datetime import timedelta
import numpy as np
import joblib
from django.contrib.auth import authenticate
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.authtoken.models import Token

from .models import User, PostureRecord, AgentLog, Notification, ChairSession
from .serializers import (
    RegisterSerializer, UserSerializer, PostureRecordSerializer
)
from .schemas import (
    REGISTER_SCHEMA, LOGIN_SCHEMA, POSTURE_CREATE_SCHEMA, AGENT_SCHEMA,
    UPDATE_ME_SCHEMA, validate_request,
)
from .physio_agent import get_advice, POSTURE_DISPLAY

# ── 模型路徑 ──────────────────────────────────────────────────────────────────

_BASE           = os.path.dirname(os.path.dirname(__file__))
_DL_MODEL_PATH  = os.path.join(_BASE, 'posture_model_dl.keras')
_DL_LABEL_PATH  = os.path.join(_BASE, 'label_encoder_dl.pkl')
_DL_SCALER_PATH = os.path.join(_BASE, 'feature_scaler_dl.pkl')

# 校準模型（依 delta 特徵訓練，需先執行 python train_model_dl.py --calibrated）
_CAL_MODEL_PATH  = os.path.join(_BASE, 'posture_model_calibrated.keras')
_CAL_LABEL_PATH  = os.path.join(_BASE, 'label_encoder_calibrated.pkl')
_CAL_SCALER_PATH = os.path.join(_BASE, 'feature_scaler_calibrated.pkl')

# ── 啟動時載入模型 ────────────────────────────────────────────────────────────

try:
    import tensorflow as tf
    _dl_model   = tf.keras.models.load_model(_DL_MODEL_PATH)
    _dl_encoder = joblib.load(_DL_LABEL_PATH)
    _dl_scaler  = joblib.load(_DL_SCALER_PATH)
    print(f'[模型] 未校準模型載入成功：{_DL_MODEL_PATH}')
except Exception as _e:
    print(f'[模型] 未校準模型載入失敗：{_e}')
    _dl_model = _dl_encoder = _dl_scaler = None

try:
    import tensorflow as tf
    _cal_model   = tf.keras.models.load_model(_CAL_MODEL_PATH)
    _cal_encoder = joblib.load(_CAL_LABEL_PATH)
    _cal_scaler  = joblib.load(_CAL_SCALER_PATH)
    print(f'[模型] 校準模型載入成功：{_CAL_MODEL_PATH}')
except Exception as _e:
    print(f'[模型] 校準模型載入失敗：{_e}')
    _cal_model = _cal_encoder = _cal_scaler = None

# ── 推論 ──────────────────────────────────────────────────────────────────────

def _rule_based_posture(seat_pressure_data, back_pressure_data=None):
    """
    絕對值快速判斷，用於極端姿勢（模型訓練資料可能未涵蓋的範圍）。
    回傳姿勢字串，或 None 表示交由 ML 模型決定。
    """
    seat = seat_pressure_data or {}
    left  = seat.get('left_back', 0) + seat.get('left_mid', 0) + seat.get('left_front', 0)
    right = seat.get('right_back', 0) + seat.get('right_mid', 0) + seat.get('right_front', 0)
    front = seat.get('left_front', 0) + seat.get('center_front', 0) + seat.get('right_front', 0)
    back  = seat.get('left_back', 0) + seat.get('center_back', 0) + seat.get('right_back', 0)

    total = left + right + 1e-6
    left_ratio  = left / total
    right_ratio = right / total
    front_ratio = front / (front + back + 1e-6)

    if left_ratio > 0.68:
        return 'left'
    if right_ratio > 0.68:
        return 'right'
    if front_ratio > 0.65:
        return 'forward'
    if front_ratio < 0.22:
        return 'recline'
    return None


def _build_features(seat_pressure_data, baseline_seat=None):
    seat = seat_pressure_data or {}

    if baseline_seat:
        # ── 校準模式：用 delta（當前 - 基準）消除體重與個人差異 ──────────────
        bs = baseline_seat
        lb = seat.get('left_back',    0) - bs.get('left_back',    0)
        lm = seat.get('left_mid',     0) - bs.get('left_mid',     0)
        lf = seat.get('left_front',   0) - bs.get('left_front',   0)
        cb = seat.get('center_back',  0) - bs.get('center_back',  0)
        cf = seat.get('center_front', 0) - bs.get('center_front', 0)
        rb = seat.get('right_back',   0) - bs.get('right_back',   0)
        rm = seat.get('right_mid',    0) - bs.get('right_mid',    0)
        rf = seat.get('right_front',  0) - bs.get('right_front',  0)

        left_delta  = lb + lm + lf
        right_delta = rb + rm + rf
        front_delta = lf + cf + rf
        back_delta  = lb + cb + rb
    else:
        # ── 未校準模式：原始絕對值 ──────────────────────────────────────────
        lb = seat.get('left_back',    0)
        lm = seat.get('left_mid',     0)
        lf = seat.get('left_front',   0)
        cb = seat.get('center_back',  0)
        cf = seat.get('center_front', 0)
        rb = seat.get('right_back',   0)
        rm = seat.get('right_mid',    0)
        rf = seat.get('right_front',  0)

        seat_total  = lb+lm+lf+cb+cf+rb+rm+rf + 1e-6
        left_delta  = (lb + lm + lf) / seat_total
        right_delta = (rb + rm + rf) / seat_total
        front_delta = (lf + cf + rf) / seat_total
        back_delta  = (lb + cb + rb) / seat_total

    return np.array([[
        lb, lm, lf, cb, cf, rb, rm, rf,
        left_delta, right_delta, front_delta, back_delta,
    ]], dtype=np.float32)


_SEDENTARY_MINUTES = 30

def _check_sedentary(user, prediction):
    """若 DL 預測為 normal，但使用者 30 分鐘前已有坐姿紀錄，則判定為久坐未動。"""
    if prediction != 'normal':
        return prediction
    window_start = timezone.now() - timedelta(minutes=_SEDENTARY_MINUTES * 3)
    window_end   = timezone.now() - timedelta(minutes=_SEDENTARY_MINUTES)
    was_sitting  = PostureRecord.objects.filter(
        user=user,
        timestamp__range=(window_start, window_end),
    ).exists()
    return 'sedentary' if was_sitting else 'normal'


def predict_posture(seat_pressure_data, baseline_seat=None):
    """
    深度學習模型預測坐姿類別。
    有基準值時使用校準模型（delta 特徵），否則使用原始模型。
    極端姿勢先由規則層攔截，避免模型對 out-of-distribution 輸入誤判。
    """
    rule = _rule_based_posture(seat_pressure_data)
    if rule:
        print(f'[規則層] 覆蓋模型 → {rule}')
        return rule

    model, encoder, scaler = (
        (_cal_model, _cal_encoder, _cal_scaler) if (baseline_seat and _cal_model)
        else (_dl_model, _dl_encoder, _dl_scaler)
    )
    if model is None:
        return None

    features      = _build_features(seat_pressure_data,
                                    baseline_seat if baseline_seat else None)
    features_norm = scaler.transform(features)
    probs         = model.predict(features_norm, verbose=0)
    idx           = np.argmax(probs, axis=1)
    return encoder.inverse_transform(idx)[0]

# ── 端點 ──────────────────────────────────────────────────────────────────────

@api_view(['POST'])
def register(request):
    """POST /api/register — 新使用者註冊。"""
    error = validate_request(request.data, REGISTER_SCHEMA)
    if error:
        return Response({'schema_error': error}, status=status.HTTP_400_BAD_REQUEST)

    if User.objects.filter(username=request.data.get('username', '')).exists():
        return Response({
            'success':    False,
            'error_code': 'ACCOUNT_EXISTS',
            'message':    '此帳號已被註冊',
        }, status=status.HTTP_409_CONFLICT)

    serializer = RegisterSerializer(data=request.data)
    if serializer.is_valid():
        user  = serializer.save()
        token, _ = Token.objects.get_or_create(user=user)
        return Response({
            'success': True,
            'token':   token.key,
            'user':    UserSerializer(user).data,
        }, status=status.HTTP_201_CREATED)
    return Response({'success': False, 'errors': serializer.errors},
                    status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
def login(request):
    """POST /api/login — 登入並取得 Token，區分帳號不存在與密碼錯誤。"""
    error = validate_request(request.data, LOGIN_SCHEMA)
    if error:
        return Response({'schema_error': error}, status=status.HTTP_400_BAD_REQUEST)

    username = request.data.get('username', '')
    password = request.data.get('password', '')

    if not User.objects.filter(username=username).exists():
        return Response({
            'success':    False,
            'error_code': 'USER_NOT_FOUND',
            'message':    '無此帳戶，請去註冊',
        }, status=status.HTTP_404_NOT_FOUND)

    user = authenticate(username=username, password=password)
    if user is None:
        return Response({
            'success':    False,
            'error_code': 'INVALID_PASSWORD',
            'message':    '密碼錯誤',
        }, status=status.HTTP_401_UNAUTHORIZED)

    token, _ = Token.objects.get_or_create(user=user)
    return Response({
        'success': True,
        'token':   token.key,
        'user':    UserSerializer(user).data,
    })


@api_view(['GET'])
def user_exists(request):
    """GET /api/users/exists?username=xxx — 查詢帳號是否已存在。"""
    username = request.query_params.get('username', '')
    exists   = User.objects.filter(username=username).exists() if username else False
    return Response({'exists': exists})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def me(request):
    """GET /api/me — 取得目前登入使用者的資料。"""
    return Response(UserSerializer(request.user).data)


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def update_me(request):
    """PATCH /api/me/update — 更新身高、體重、Email。"""
    error = validate_request(request.data, UPDATE_ME_SCHEMA)
    if error:
        return Response({'schema_error': error}, status=status.HTTP_400_BAD_REQUEST)

    user = request.user
    for field in ('height', 'weight', 'email'):
        if field in request.data:
            setattr(user, field, request.data[field])
    user.save()
    return Response(UserSerializer(user).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def posture_create(request):
    """
    POST /api/posture — 儲存坐姿感測數據。

    優先存到目前 active ChairSession 的 user，
    避免 ESP32 帳號與前端登入帳號不同導致前端看不到資料。
    沒有 active session 時退回使用 request.user。
    """
    error = validate_request(request.data, POSTURE_CREATE_SCHEMA)
    if error:
        return Response({'schema_error': error}, status=status.HTTP_400_BAD_REQUEST)

    session = ChairSession.objects.filter(is_active=True).select_related('user').first()
    target_user = session.user if session else request.user

    data = request.data.copy()

    if not data.get('posture'):
        baseline_seat = session.baseline_seat if session else None
        predicted = predict_posture(
            data.get('seat_pressure_data'),
            baseline_seat=baseline_seat,
        )
        if predicted:
            predicted = _check_sedentary(target_user, predicted)
            data['posture'] = predicted
        else:
            return Response(
                {'error': '模型尚未載入，請先執行 python train_model_dl.py'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

    serializer = PostureRecordSerializer(data=data)
    if serializer.is_valid():
        serializer.save(user=target_user)
        response_data = dict(serializer.data)

        detected_posture = data['posture']
        if detected_posture != 'normal':
            posture_name = POSTURE_DISPLAY.get(detected_posture, detected_posture)
            Notification.objects.create(user=target_user, message=f'坐姿提醒：{posture_name}')

        return Response(response_data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def agent_advice(request):
    """
    POST /api/agent — 依坐姿查詢 Physio Agent 建議。

    payload: { "posture": "left", "user_message": "我肩膀很痠" }
    回傳:    { "posture": "left", "posture_display": "身體左傾", "advice": "..." }
    """
    error = validate_request(request.data, AGENT_SCHEMA)
    if error:
        return Response({'schema_error': error}, status=status.HTTP_400_BAD_REQUEST)

    posture      = request.data['posture']
    user_message = request.data.get('user_message', '')

    try:
        advice = get_advice(posture, request.user.id, user_message)
    except Exception as e:
        return Response(
            {'error': f'Agent 暫時無法使用：{str(e)}'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    AgentLog.objects.create(
        user=request.user,
        posture=posture,
        user_message=user_message,
        agent_reply=advice,
    )

    return Response({
        'posture':         posture,
        'posture_display': POSTURE_DISPLAY.get(posture, posture),
        'advice':          advice,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def posture_history(request):
    """GET /api/posture/history — 查詢目前使用者的坐姿歷史紀錄。"""
    limit   = int(request.query_params.get('limit', 50))
    records = PostureRecord.objects.filter(user=request.user)[:limit]
    return Response(PostureRecordSerializer(records, many=True).data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def notification_pending(request):
    """
    GET /api/notification/pending — ESP32 輪詢待處理的震動提醒。

    回傳尚未發送的通知清單，並同時標記為已發送（is_sent=True）。
    ESP32 收到後即可驅動馬達震動。
    """
    pending = list(
        Notification.objects.filter(user=request.user, is_sent=False)
        .values('id', 'message', 'timestamp')
    )
    if pending:
        ids = [n['id'] for n in pending]
        Notification.objects.filter(id__in=ids).update(is_sent=True)

    return Response({'count': len(pending), 'notifications': pending})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def notification_history(request):
    """GET /api/notification/history — 查詢通知歷史紀錄（前端通知頁用）。"""
    limit = int(request.query_params.get('limit', 50))
    notifications = Notification.objects.filter(
        user=request.user
    ).order_by('-timestamp')[:limit]
    data = [
        {
            'id': n.id,
            'message': n.message,
            'timestamp': n.timestamp,
            'is_sent': n.is_sent,
        }
        for n in notifications
    ]
    return Response({'count': len(data), 'notifications': data})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def notification_ack(request):
    """
    POST /api/notification/ack — ESP32 確認馬達已震動完畢。

    payload: { "ids": [1, 2, 3] }   ← 可選，不帶則略過
    回傳: { "acked": <筆數> }
    """
    ids = request.data.get('ids', [])
    if not isinstance(ids, list):
        return Response({'error': 'ids 須為陣列'}, status=status.HTTP_400_BAD_REQUEST)

    acked = 0
    if ids:
        acked = Notification.objects.filter(
            user=request.user, id__in=ids
        ).update(is_sent=True)

    return Response({'acked': acked})


# ── 座椅佔用管理 ───────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def chair_checkin(request):
    """POST /api/chair/checkin — 使用者坐上椅子，成為目前的感測對象。"""
    ChairSession.objects.filter(is_active=True).update(is_active=False)
    ChairSession.objects.create(user=request.user)
    return Response({'status': 'checked_in', 'username': request.user.username})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def chair_checkout(request):
    """POST /api/chair/checkout — 使用者離開椅子。"""
    ChairSession.objects.filter(user=request.user, is_active=True).update(is_active=False)
    return Response({'status': 'checked_out'})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def chair_calibrate(request):
    """
    POST /api/chair/calibrate — 記錄目前坐姿作為基準值（請保持標準坐姿再送出）。

    payload: { "seat_pressure_data": {...}, "back_pressure_data": {...} }
    回傳:    { "status": "calibrated", "calibrated": true }
    """
    session = ChairSession.objects.filter(is_active=True).select_related('user').first()
    if not session or session.user != request.user:
        return Response(
            {'error': '請先 check-in 坐上椅子再進行校準'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    seat = request.data.get('seat_pressure_data')
    back = request.data.get('back_pressure_data', {})
    if not seat:
        return Response(
            {'error': '請提供 seat_pressure_data 與 back_pressure_data'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    session.baseline_seat = seat
    session.baseline_back = back
    session.save(update_fields=['baseline_seat', 'baseline_back'])

    return Response({'status': 'calibrated', 'calibrated': True})


SEAT_KEYS = ['left_back', 'left_mid', 'left_front',
             'center_back', 'center_front',
             'right_back', 'right_mid', 'right_front']
BACK_KEYS = ['spine_upper', 'spine_mid', 'spine_lower']

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def chair_calibrate_auto(request):
    """
    POST /api/chair/calibrate/auto — 坐正後呼叫，自動用最近 15 秒資料平均作為基準。

    回傳: { "status": "calibrated", "baseline_seat": {...}, "samples": N }
    """
    session = ChairSession.objects.filter(is_active=True).select_related('user').first()
    if not session or session.user != request.user:
        return Response(
            {'error': '請先 check-in 坐上椅子再進行校準'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    cutoff = timezone.now() - timedelta(seconds=15)
    recent = list(
        PostureRecord.objects.filter(
            user=request.user,
            seat_pressure_data__isnull=False,
            timestamp__gte=cutoff,
        ).order_by('-timestamp')[:10]
    )

    if not recent:
        return Response(
            {'error': '最近 15 秒內沒有感測器資料，請坐好後稍候再試'},
            status=status.HTTP_404_NOT_FOUND,
        )

    # 多筆平均，避免單筆雜訊
    baseline_seat = {}
    for k in SEAT_KEYS:
        vals = [r.seat_pressure_data.get(k, 0) for r in recent if r.seat_pressure_data]
        baseline_seat[k] = round(sum(vals) / len(vals), 2) if vals else 0

    baseline_back = {}
    back_records = [r for r in recent if r.back_pressure_data]
    if back_records:
        for k in BACK_KEYS:
            vals = [r.back_pressure_data.get(k, 0) for r in back_records]
            baseline_back[k] = round(sum(vals) / len(vals), 2)

    session.baseline_seat = baseline_seat
    session.baseline_back = baseline_back
    session.save(update_fields=['baseline_seat', 'baseline_back'])

    return Response({
        'status':        'calibrated',
        'calibrated':    True,
        'samples':       len(recent),
        'baseline_seat': baseline_seat,
    })


@api_view(['GET'])
def chair_status(request):
    """GET /api/chair/status — 查詢目前是誰在使用椅子（不需要登入）。"""
    session = ChairSession.objects.filter(is_active=True).select_related('user').first()
    if session:
        return Response({
            'active':     True,
            'username':   session.user.username,
            'since':      session.started_at,
            'calibrated': bool(session.baseline_seat),
        })
    return Response({'active': False, 'username': None, 'calibrated': False})
