import os
import json
import secrets
from collections import Counter
from datetime import timedelta
from pathlib import Path
import numpy as np
import joblib
from django.contrib.auth import authenticate
from django.core.mail import send_mail
from django.conf import settings as django_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.authtoken.models import Token

from .models import (
    User, PostureRecord, AgentLog, Notification, ChairSession, MotorLog,
    PasswordResetCode,
)
from .serializers import (
    RegisterSerializer, UserSerializer, PostureRecordSerializer
)
from .schemas import (
    REGISTER_SCHEMA, LOGIN_SCHEMA, POSTURE_CREATE_SCHEMA, AGENT_SCHEMA,
    UPDATE_ME_SCHEMA, CHANGE_PASSWORD_SCHEMA,
    FORGOT_PASSWORD_REQUEST_SCHEMA, FORGOT_PASSWORD_VERIFY_SCHEMA,
    AVATAR_SCHEMA, MOTOR_TRIGGER_SCHEMA, validate_request,
)
from .physio_agent import get_advice, POSTURE_DISPLAY
from .mqtt_publisher import publish_motor_command
from .motor_constants import MOTOR_MAP

# ── 伸展計劃資料（lazy load） ──────────────────────────────────────────────────

_STRETCH_MAP = None

def _get_stretch_map():
    global _STRETCH_MAP
    if _STRETCH_MAP is None:
        map_path = Path(__file__).resolve().parent.parent / 'knowledge_base' / 'stretch_video_map.json'
        with open(map_path, encoding='utf-8') as f:
            _STRETCH_MAP = json.load(f)
    return _STRETCH_MAP

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

SEAT_KEYS = ['left_back', 'left_mid', 'left_front',
             'center_back', 'center_front',
             'right_back', 'right_mid', 'right_front']
BACK_KEYS = ['spine_upper', 'spine_mid', 'spine_lower']


def _rule_based_posture(seat_pressure_data, back_pressure_data=None):
    """
    絕對值快速判斷，用於極端姿勢（模型訓練資料可能未涵蓋的範圍）。
    回傳姿勢字串，或 None 表示交由 ML 模型決定。

    曾經在這裡加過單點壓力封頂，避免單一感測器讀值異常主導判斷；
    但實測發現封頂會誤傷真正用力前傾時的正常讀值，導致前傾判斷
    永遠碰不到門檻。單筆雜訊改交給 mqtt_subscriber.py 的防手震機制
    （STABLE_READINGS，需連續多筆讀值一致才觸發提醒/震動）過濾，
    這裡維持用原始值判斷。
    """
    seat = seat_pressure_data or {}
    lb = seat.get('left_back', 0)
    lm = seat.get('left_mid', 0)
    lf = seat.get('left_front', 0)
    cb = seat.get('center_back', 0)
    cf = seat.get('center_front', 0)
    rb = seat.get('right_back', 0)
    rm = seat.get('right_mid', 0)
    rf = seat.get('right_front', 0)

    left  = lb + lm + lf
    right = rb + rm + rf
    front = lf + cf + rf
    back  = lb + cb + rb

    total = left + right + 1e-6
    left_ratio  = left / total
    right_ratio = right / total
    front_ratio = front / (front + back + 1e-6)

    if left_ratio > 0.68:
        return 'left'
    if right_ratio > 0.68:
        return 'right'
    if front_ratio > 0.55:
        return 'forward'
    if front_ratio < 0.28:
        return 'recline'
    return None


def _spine_features(su, sm, sl, seat_total):
    """椅背 5 個衍生特徵，delta（可正可負）與絕對值兩種模式共用同一組公式。"""
    spine_total = su + sm + sl
    denom_spine = spine_total if abs(spine_total) > 1e-6 else 1e-6
    denom_all   = seat_total + spine_total
    denom_all   = denom_all if abs(denom_all) > 1e-6 else 1e-6

    spine_ratio             = spine_total / denom_all
    spine_upper_ratio       = su / denom_spine
    spine_lower_ratio       = sl / denom_spine
    spine_upper_lower_delta = su - sl

    return spine_total, spine_ratio, spine_upper_ratio, spine_lower_ratio, spine_upper_lower_delta


def _build_features(seat_pressure_data, back_pressure_data=None,
                     baseline_seat=None, baseline_back=None):
    seat = seat_pressure_data or {}
    back = back_pressure_data or {}

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

        # 本次沒有椅背讀數時（back 為空）視為無資料，delta 一律為 0，
        # 避免誤把「缺值」算成「相對基準大幅下降」而誤判為 forward。
        bb = baseline_back or {}
        if back:
            su = back.get('spine_upper', 0) - bb.get('spine_upper', 0)
            sm = back.get('spine_mid',   0) - bb.get('spine_mid',   0)
            sl = back.get('spine_lower', 0) - bb.get('spine_lower', 0)
        else:
            su = sm = sl = 0
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

        su = back.get('spine_upper', 0)
        sm = back.get('spine_mid',   0)
        sl = back.get('spine_lower', 0)

    seat_total_raw = lb + lm + lf + cb + cf + rb + rm + rf
    spine_total, spine_ratio, spine_upper_ratio, spine_lower_ratio, spine_ud_delta = (
        _spine_features(su, sm, sl, seat_total_raw)
    )

    return np.array([[
        lb, lm, lf, cb, cf, rb, rm, rf,
        left_delta, right_delta, front_delta, back_delta,
        su, sm, sl,
        spine_total, spine_ratio, spine_upper_ratio, spine_lower_ratio, spine_ud_delta,
    ]], dtype=np.float32)


_SEDENTARY_MINUTES = 5

def _check_sedentary(user, prediction):
    """以最後一次離座為起點，持續坐超過設定時間則判定為久坐未動。"""
    if prediction in ('empty', 'sedentary'):
        return prediction

    now = timezone.now()
    cutoff = now - timedelta(minutes=_SEDENTARY_MINUTES)

    # 最近 N 分鐘內有離座紀錄 → 剛坐下，不觸發
    if PostureRecord.objects.filter(user=user, posture='empty', timestamp__gte=cutoff).exists():
        return prediction

    # 找最後一次離座時間作為就坐起點
    last_empty = PostureRecord.objects.filter(
        user=user, posture='empty'
    ).order_by('-timestamp').first()

    if last_empty is None or last_empty.timestamp >= cutoff:
        return prediction

    # 從上次離座到 N 分鐘前，有坐姿紀錄 → 確認連續坐了 N 分鐘以上
    was_sitting = PostureRecord.objects.filter(
        user=user,
        timestamp__range=(last_empty.timestamp, cutoff),
    ).exclude(posture__in=['empty', 'sedentary']).exists()

    return 'sedentary' if was_sitting else prediction


def predict_posture(seat_pressure_data, back_pressure_data=None,
                     baseline_seat=None, baseline_back=None):
    """
    深度學習模型預測坐姿類別（20 特徵：椅墊 12 個 + 椅背 8 個）。
    有基準值時使用校準模型（delta 特徵），否則使用原始模型。
    極端姿勢先由規則層攔截，避免模型對 out-of-distribution 輸入誤判。
    """
    rule = _rule_based_posture(seat_pressure_data, back_pressure_data)
    if rule:
        print(f'[規則層] 覆蓋模型 → {rule}')
        return rule

    model, encoder, scaler = (
        (_cal_model, _cal_encoder, _cal_scaler) if (baseline_seat and _cal_model)
        else (_dl_model, _dl_encoder, _dl_scaler)
    )
    if model is None:
        return None

    features = _build_features(seat_pressure_data, back_pressure_data,
                                baseline_seat if baseline_seat else None,
                                baseline_back if baseline_seat else None)
    try:
        features_norm = scaler.transform(features)
        probs         = model.predict(features_norm, verbose=0)
        idx           = np.argmax(probs, axis=1)
        return encoder.inverse_transform(idx)[0]
    except Exception as e:
        # 模型/scaler 檔案版本與目前特徵數對不上時（例如尚未針對新增的椅背
        # 特徵重新訓練），不能整個拋出去讓 MQTT 訂閱服務跟著死掉，退回 None
        # 讓呼叫端的 fallback（payload 自帶的 posture 或 'normal'）接手。
        print(f'[模型] 推論失敗，退回規則/預設值：{e}')
        return None

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
    """PATCH /api/me/update — 更新個人資料（部分更新，不傳的欄位不覆寫）。"""
    error = validate_request(request.data, UPDATE_ME_SCHEMA)
    if error:
        return Response({'schema_error': error}, status=status.HTTP_400_BAD_REQUEST)

    user = request.user
    for field in ('height', 'weight', 'email', 'display_name', 'avatar_url'):
        if field in request.data:
            setattr(user, field, request.data[field])
    user.save()
    return Response(UserSerializer(user).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def change_password(request):
    """POST /api/auth/change-password — 已登入狀態下修改密碼。"""
    error = validate_request(request.data, CHANGE_PASSWORD_SCHEMA)
    if error:
        return Response({'schema_error': error}, status=status.HTTP_400_BAD_REQUEST)

    user = authenticate(
        username=request.user.username,
        password=request.data['current_password'],
    )
    if user is None:
        return Response({
            'success':    False,
            'error_code': 'INVALID_PASSWORD',
            'message':    '目前密碼錯誤',
        }, status=status.HTTP_401_UNAUTHORIZED)

    request.user.set_password(request.data['new_password'])
    request.user.save()
    return Response({'success': True, 'message': '密碼已更新'})


_RESET_CODE_TTL_MINUTES = 10
_RESET_CODE_RESEND_COOLDOWN_SECONDS = 60


def _generate_reset_code():
    return ''.join(secrets.choice('0123456789') for _ in range(6))


@api_view(['POST'])
def forgot_password_request(request):
    """
    POST /api/auth/forgot-password/request — 驗證帳號與 Email 相符後，
    寄送 6 碼驗證碼到使用者註冊時填寫的信箱（10 分鐘內有效）。
    """
    error = validate_request(request.data, FORGOT_PASSWORD_REQUEST_SCHEMA)
    if error:
        return Response({'schema_error': error}, status=status.HTTP_400_BAD_REQUEST)

    username = request.data['username']
    email    = request.data['email']

    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        return Response({
            'success':    False,
            'error_code': 'USER_NOT_FOUND',
            'message':    '帳號不存在',
        }, status=status.HTTP_404_NOT_FOUND)

    if not user.email or user.email.lower() != email.lower():
        return Response({
            'success':    False,
            'error_code': 'EMAIL_MISMATCH',
            'message':    'Email 與帳號不符',
        }, status=status.HTTP_400_BAD_REQUEST)

    cooldown_cutoff = timezone.now() - timedelta(seconds=_RESET_CODE_RESEND_COOLDOWN_SECONDS)
    already_sent_recently = PasswordResetCode.objects.filter(
        user=user, is_used=False, created_at__gte=cooldown_cutoff,
    ).exists()
    if already_sent_recently:
        return Response({'success': True, 'message': '驗證碼已寄出，請查收信箱（1 分鐘內請勿重複請求）'})

    code = _generate_reset_code()
    PasswordResetCode.objects.create(user=user, code=code)

    try:
        send_mail(
            subject='智慧座椅｜密碼重設驗證碼',
            message=(
                f'您的密碼重設驗證碼為：{code}\n'
                f'此驗證碼將於 {_RESET_CODE_TTL_MINUTES} 分鐘後失效，請勿提供給他人。'
            ),
            from_email=django_settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
    except Exception as e:
        return Response({
            'success':    False,
            'error_code': 'EMAIL_SEND_FAILED',
            'message':    f'驗證信寄送失敗，請稍後再試：{str(e)}',
        }, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    return Response({'success': True, 'message': '驗證碼已寄出，請查收信箱'})


@api_view(['POST'])
def forgot_password_verify(request):
    """
    POST /api/auth/forgot-password/verify — 驗證碼正確且未過期、未使用時，重設密碼。
    """
    error = validate_request(request.data, FORGOT_PASSWORD_VERIFY_SCHEMA)
    if error:
        return Response({'schema_error': error}, status=status.HTTP_400_BAD_REQUEST)

    username     = request.data['username']
    code         = request.data['code']
    new_password = request.data['new_password']

    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        return Response({
            'success':    False,
            'error_code': 'USER_NOT_FOUND',
            'message':    '帳號不存在',
        }, status=status.HTTP_404_NOT_FOUND)

    ttl_cutoff = timezone.now() - timedelta(minutes=_RESET_CODE_TTL_MINUTES)
    reset_code = PasswordResetCode.objects.filter(
        user=user, code=code, is_used=False, created_at__gte=ttl_cutoff,
    ).order_by('-created_at').first()

    if reset_code is None:
        return Response({
            'success':    False,
            'error_code': 'INVALID_CODE',
            'message':    '驗證碼錯誤或已過期，請重新請求驗證碼',
        }, status=status.HTTP_400_BAD_REQUEST)

    reset_code.is_used = True
    reset_code.save(update_fields=['is_used'])

    user.set_password(new_password)
    user.save()
    return Response({'success': True, 'message': '密碼已重設，請重新登入'})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def update_avatar(request):
    """POST /api/me/avatar — 更新頭像 URL。"""
    error = validate_request(request.data, AVATAR_SCHEMA)
    if error:
        return Response({'schema_error': error}, status=status.HTTP_400_BAD_REQUEST)

    request.user.avatar_url = request.data['avatar_url']
    request.user.save(update_fields=['avatar_url'])
    return Response(UserSerializer(request.user).data)


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
        baseline_back = session.baseline_back if session else None
        predicted = predict_posture(
            data.get('seat_pressure_data'),
            back_pressure_data=data.get('back_pressure_data'),
            baseline_seat=baseline_seat,
            baseline_back=baseline_back,
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
    POST /api/agent — 查詢 Physio Agent 建議，posture、user_message 至少擇一。

    payload: { "posture": "left", "user_message": "我肩膀很痠" }  ← 兩者皆可單獨給
    回傳:    { "posture": "left", "posture_display": "身體左傾", "advice": "...",
               "steps": [{ "step": 1, "thought": "...", "action": "search_knowledge_base",
                          "action_input": {...}, "observation": "..." }, ...] }
    steps 是完整 ReAct 逐步紀錄（Thought/Action/Observation），給前端展示 Agent
    決策過程用，不是黑盒子產出最終文字而已。
    """
    error = validate_request(request.data, AGENT_SCHEMA)
    if error:
        return Response({'schema_error': error}, status=status.HTTP_400_BAD_REQUEST)

    posture      = request.data.get('posture', '')
    user_message = request.data.get('user_message', '')

    try:
        advice, steps = get_advice(posture, request.user.id, user_message)
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
        steps=steps,
    )

    return Response({
        'posture':         posture,
        'posture_display': POSTURE_DISPLAY.get(posture, posture),
        'advice':          advice,
        'steps':           steps,
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


# ── 伸展計劃 ───────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def stretch_plan(request):
    """
    GET /api/agent/stretch-plan — 依近 7 天壞坐姿頻率推薦伸展動作清單。

    回傳:
        period_days:               查詢天數（固定 7）
        total_bad_posture_records: 不良坐姿總筆數
        posture_stats:             各坐姿頻率統計（count、ratio、display）
        recommended_exercises:     建議伸展動作清單（最多 10 個，含 YouTube URL）
    """
    cutoff  = timezone.now() - timedelta(days=7)
    records = PostureRecord.objects.filter(
        user=request.user,
        timestamp__gte=cutoff,
    ).exclude(posture__in=['normal', 'empty'])

    total = records.count()
    if total == 0:
        return Response({
            'period_days':               7,
            'total_bad_posture_records': 0,
            'posture_stats':             {},
            'recommended_exercises':     [],
            'message':                   '近 7 天無不良坐姿紀錄，繼續保持良好坐姿！',
        })

    posture_counts = Counter(records.values_list('posture', flat=True))
    posture_stats  = {
        p: {
            'count':   c,
            'ratio':   round(c / total, 3),
            'display': POSTURE_DISPLAY.get(p, p),
        }
        for p, c in posture_counts.most_common()
    }

    stretch_map     = _get_stretch_map()
    exercises_by_id = {ex['id']: ex for ex in stretch_map['exercises']}
    posture_ex_map  = stretch_map['posture_exercise_map']

    seen_ids    = set()
    recommended = []
    for posture, _ in posture_counts.most_common():
        for ex_id in posture_ex_map.get(posture, []):
            if ex_id not in seen_ids:
                seen_ids.add(ex_id)
                ex = exercises_by_id.get(ex_id)
                if ex:
                    recommended.append({
                        'id':             ex['id'],
                        'name':           ex['name'],
                        'target_muscles': ex['target_muscles'],
                        'reps':           ex['reps'],
                        'duration_sec':   ex['duration_sec'],
                        'youtube_url':    ex['youtube_url'],
                        'youtube_title':  ex['youtube_title'],
                        'description':    ex['description'],
                        'triggered_by':   POSTURE_DISPLAY.get(posture, posture),
                    })

    return Response({
        'period_days':               7,
        'total_bad_posture_records': total,
        'posture_stats':             posture_stats,
        'recommended_exercises':     recommended[:10],
    })


# ── 馬達觸發 ───────────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def motor_trigger(request):
    """
    POST /api/motor/trigger — 依坐姿觸發對應馬達震動並寫入 MotorLog。

    payload: { "posture": "left" }
    回傳:    { "posture": "left", "motors": ["M2","M4"], "triggered": true }

    觸發規則（同 PPT 第 11 頁）：
        前傾 → M1 M2 | 後仰 → M3 M4
        左傾 → M2 M4 | 右傾 → M1 M3 | 久坐 → M1 M2 M3 M4
    """
    error = validate_request(request.data, MOTOR_TRIGGER_SCHEMA)
    if error:
        return Response({'schema_error': error}, status=status.HTTP_400_BAD_REQUEST)

    posture = request.data['posture']
    motors  = MOTOR_MAP.get(posture, [])

    if not motors:
        return Response({
            'posture':         posture,
            'posture_display': POSTURE_DISPLAY.get(posture, posture),
            'motors':          [],
            'triggered':       False,
            'reason':          '標準坐姿或無人就坐，無需觸發馬達',
        })

    posture_name = POSTURE_DISPLAY.get(posture, posture)
    motor_str    = '、'.join(motors)
    message      = f'馬達觸發：{posture_name}（{motor_str}）'

    Notification.objects.create(user=request.user, message=message)
    MotorLog.objects.create(
        user=request.user,
        posture=posture,
        motors=motors,
        reason=posture_name,
    )

    # 發布真實馬達指令到硬體（chair/vibration/01/cmd）；硬體未連線時安靜失敗，不影響本次回應
    published = publish_motor_command(motors)

    return Response({
        'posture':         posture,
        'posture_display': posture_name,
        'motors':          motors,
        'triggered':       True,
        'message':         message,
        'mqtt_published':  published is not None,
    })
