import os
from datetime import timedelta
import numpy as np
import joblib
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.authtoken.models import Token

from .models import PostureRecord, AgentLog, Notification
from .serializers import (
    RegisterSerializer, LoginSerializer, UserSerializer, PostureRecordSerializer
)
from .schemas import (
    REGISTER_SCHEMA, LOGIN_SCHEMA, POSTURE_CREATE_SCHEMA, AGENT_SCHEMA, validate_request
)
from .physio_agent import get_advice, POSTURE_DISPLAY

# ── 模型路徑 ──────────────────────────────────────────────────────────────────

_BASE           = os.path.dirname(os.path.dirname(__file__))
_DL_MODEL_PATH  = os.path.join(_BASE, 'posture_model_dl.keras')
_DL_LABEL_PATH  = os.path.join(_BASE, 'label_encoder_dl.pkl')
_DL_SCALER_PATH = os.path.join(_BASE, 'feature_scaler_dl.pkl')

# ── 啟動時載入模型 ────────────────────────────────────────────────────────────

try:
    import tensorflow as tf
    _dl_model   = tf.keras.models.load_model(_DL_MODEL_PATH)
    _dl_encoder = joblib.load(_DL_LABEL_PATH)
    _dl_scaler  = joblib.load(_DL_SCALER_PATH)
except Exception:
    _dl_model = _dl_encoder = _dl_scaler = None

# ── 推論 ──────────────────────────────────────────────────────────────────────

def _build_features(seat_pressure_data, back_pressure_data):
    seat = seat_pressure_data or {}
    back = back_pressure_data or {}

    left_back    = seat.get('left_back',    0)
    left_mid     = seat.get('left_mid',     0)
    left_front   = seat.get('left_front',   0)
    center_back  = seat.get('center_back',  0)
    center_front = seat.get('center_front', 0)
    right_back   = seat.get('right_back',   0)
    right_mid    = seat.get('right_mid',    0)
    right_front  = seat.get('right_front',  0)

    spine_upper  = back.get('spine_upper', 0)
    spine_mid    = back.get('spine_mid',   0)
    spine_lower  = back.get('spine_lower', 0)

    seat_total   = left_back + left_mid + left_front + center_back + center_front + right_back + right_mid + right_front + 1e-6
    spine_total  = spine_upper + spine_mid + spine_lower
    left_ratio   = (left_back + left_mid + left_front) / seat_total
    front_ratio  = (left_front + center_front + right_front) / seat_total
    spine_ratio  = spine_total / (seat_total + spine_total)

    return np.array([[
        left_back, left_mid, left_front,
        center_back, center_front,
        right_back, right_mid, right_front,
        spine_upper, spine_mid, spine_lower,
        seat_total, left_ratio, front_ratio, spine_total, spine_ratio,
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


def predict_posture(seat_pressure_data, back_pressure_data):
    """深度學習模型預測坐姿類別。"""
    if _dl_model is None:
        return None

    features      = _build_features(seat_pressure_data, back_pressure_data)
    features_norm = _dl_scaler.transform(features)
    probs         = _dl_model.predict(features_norm, verbose=0)
    idx           = np.argmax(probs, axis=1)
    return _dl_encoder.inverse_transform(idx)[0]

# ── 端點 ──────────────────────────────────────────────────────────────────────

@api_view(['POST'])
def register(request):
    """POST /api/register — 新使用者註冊。"""
    error = validate_request(request.data, REGISTER_SCHEMA)
    if error:
        return Response({'schema_error': error}, status=status.HTTP_400_BAD_REQUEST)

    serializer = RegisterSerializer(data=request.data)
    if serializer.is_valid():
        user  = serializer.save()
        token, _ = Token.objects.get_or_create(user=user)
        return Response({
            'token': token.key,
            'user':  UserSerializer(user).data,
        }, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
def login(request):
    """POST /api/login — 登入並取得 Token。"""
    error = validate_request(request.data, LOGIN_SCHEMA)
    if error:
        return Response({'schema_error': error}, status=status.HTTP_400_BAD_REQUEST)

    serializer = LoginSerializer(data=request.data)
    if serializer.is_valid():
        user  = serializer.validated_data['user']
        token, _ = Token.objects.get_or_create(user=user)
        return Response({
            'token': token.key,
            'user':  UserSerializer(user).data,
        })
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def me(request):
    """GET /api/me — 取得目前登入使用者的資料。"""
    return Response(UserSerializer(request.user).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def posture_create(request):
    """
    POST /api/posture — 儲存坐姿感測數據。

    payload 包含 seat_pressure_data / back_pressure_data 時，模型自動預測坐姿後寫入；
    payload 直接帶 posture 欄位時，略過模型直接儲存（適合標記真實樣本）。
    """
    error = validate_request(request.data, POSTURE_CREATE_SCHEMA)
    if error:
        return Response({'schema_error': error}, status=status.HTTP_400_BAD_REQUEST)

    data = request.data.copy()

    if not data.get('posture'):
        predicted = predict_posture(
            data.get('seat_pressure_data'),
            data.get('back_pressure_data'),
        )
        if predicted:
            predicted = _check_sedentary(request.user, predicted)
            data['posture'] = predicted
        else:
            return Response(
                {'error': '模型尚未載入，請先執行 python train_model_dl.py'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

    serializer = PostureRecordSerializer(data=data)
    if serializer.is_valid():
        serializer.save(user=request.user)
        response_data = dict(serializer.data)

        detected_posture = data['posture']
        if detected_posture != 'normal':
            # 建立震動提醒通知（供 ESP32 輪詢）
            Notification.objects.create(
                user=request.user,
                message=f'坐姿不良：{detected_posture}',
            )

            # 自動觸發 Physio Agent 建議
            try:
                advice = get_advice(detected_posture)
                AgentLog.objects.create(
                    user=request.user,
                    posture=detected_posture,
                    agent_reply=advice,
                )
                response_data['physio_advice'] = advice
            except Exception:
                pass

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
        advice = get_advice(posture, user_message)
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
