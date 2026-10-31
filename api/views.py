import os
import json
import logging
import secrets
from collections import Counter
from datetime import timedelta
from pathlib import Path
import numpy as np
import joblib
from PIL import Image, ImageOps, UnidentifiedImageError
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
    PasswordResetCode, AgentJob,
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
from .chairs import active_session, chair_for_device, is_online, motor_topic, user_session
from .models import CalibrationRequest, Chair, UserCalibration
from .calibration import (
    CALIBRATION_DURATION_SECONDS, DEVICE_TIMEOUT_SECONDS, FAIL_MESSAGES,
    calibrate_from_recent, center_of_pressure, push_neutral, refresh_request, start_calibration,
    user_calibration,
)

# 伸展動作查表（不經過 LLM），實作在 api/stretch.py
from .stretch import exercises_by_id as _exercises_by_id, recommend_exercises as _recommend_exercises
from .daily_plan import get_daily_plan
from .models import WellnessCompletion

logger = logging.getLogger(__name__)

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


# softmax 最大機率低於此門檻時視為低信心，僅記錄警告，不影響判斷結果
# （拒答/二次確認屬於前端互動設計，後端先把信心分數透出讓前端決定怎麼呈現）
LOW_CONFIDENCE_THRESHOLD = 0.5


def predict_posture(seat_pressure_data, back_pressure_data=None,
                     baseline_seat=None, baseline_back=None):
    """
    深度學習模型預測坐姿類別（20 特徵：椅墊 12 個 + 椅背 8 個）。
    有基準值時使用校準模型（delta 特徵），否則使用原始模型。
    極端姿勢先由規則層攔截，避免模型對 out-of-distribution 輸入誤判。

    回傳 (posture, confidence)：
        posture    — 坐姿類別字串，或 None（模型未載入／推論失敗）
        confidence — 0~1 之間的 softmax 最大機率值；規則層覆蓋或模型不可用時為 None
                     （代表「這不是機率推論出來的結果」，而非信心剛好缺值）
    """
    rule = _rule_based_posture(seat_pressure_data, back_pressure_data)
    if rule:
        print(f'[規則層] 覆蓋模型 → {rule}')
        return rule, None

    model, encoder, scaler = (
        (_cal_model, _cal_encoder, _cal_scaler) if (baseline_seat and _cal_model)
        else (_dl_model, _dl_encoder, _dl_scaler)
    )
    if model is None:
        return None, None

    features = _build_features(seat_pressure_data, back_pressure_data,
                                baseline_seat if baseline_seat else None,
                                baseline_back if baseline_seat else None)
    try:
        features_norm = scaler.transform(features)
        probs         = model.predict(features_norm, verbose=0)
        idx           = np.argmax(probs, axis=1)
        posture       = encoder.inverse_transform(idx)[0]
        confidence    = float(probs[0][idx[0]])
        if confidence < LOW_CONFIDENCE_THRESHOLD:
            print(f'[模型] 低信心預測：{posture}（confidence={confidence:.2f} < {LOW_CONFIDENCE_THRESHOLD}）')
        return posture, confidence
    except Exception as e:
        # 模型/scaler 檔案版本與目前特徵數對不上時（例如尚未針對新增的椅背
        # 特徵重新訓練），不能整個拋出去讓 MQTT 訂閱服務跟著死掉，退回 None
        # 讓呼叫端的 fallback（payload 自帶的 posture 或 'normal'）接手。
        print(f'[模型] 推論失敗，退回規則/預設值：{e}')
        return None, None

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
def health(request):
    """
    GET /api/health — 健康檢查端點，供 Docker HEALTHCHECK／監控用，不需要登入。

    只驗證資料庫連線是否正常；MQTT／MCP Server 是獨立服務，各自有自己的健康檢查方式
    （mqtt-subscriber 用心跳檔案，mcp 用 HTTP 檢查，見 healthcheck.py）。
    """
    from django.db import connection
    try:
        connection.ensure_connection()
        db_ok = True
    except Exception:
        db_ok = False

    return Response(
        {'status': 'ok' if db_ok else 'degraded', 'db': db_ok},
        status=status.HTTP_200_OK if db_ok else status.HTTP_503_SERVICE_UNAVAILABLE,
    )


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


AVATAR_FORMATS = {'PNG': 'png', 'JPEG': 'jpg'}


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def upload_avatar(request):
    """
    POST /api/me/avatar/upload — 上傳頭像圖片（multipart/form-data，欄位 file）。

    以實際圖片內容判斷格式（不看副檔名），只收 PNG／JPEG；縮到最長邊 AVATAR_MAX_SIZE 後重新存檔，
    去掉 EXIF（手機照片可能含 GPS）與夾帶的非圖片內容。檔名隨機產生，換頭像時刪除舊檔。
    """
    def fail(message):
        return Response({'success': False, 'message': message}, status=status.HTTP_400_BAD_REQUEST)

    upload = request.FILES.get('file')
    if upload is None:
        return fail('請以 multipart/form-data 上傳，欄位名稱為 file')
    if upload.size > django_settings.AVATAR_MAX_BYTES:
        return fail('圖片大小不能超過 5MB')

    try:
        img = Image.open(upload)
        fmt = img.format
        if fmt not in AVATAR_FORMATS:
            return fail('只支援 PNG、JPG、JPEG 圖片')
        if img.width * img.height > 40_000_000:   # 擋解壓縮炸彈（檔案小但像素數極大）
            return fail('圖片尺寸過大')
        img = ImageOps.exif_transpose(img)       # 先依 EXIF 轉正，重新存檔後 EXIF 就不在了
        img.thumbnail((django_settings.AVATAR_MAX_SIZE, django_settings.AVATAR_MAX_SIZE))
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        return fail('只支援 PNG、JPG、JPEG 圖片')

    ext = AVATAR_FORMATS[fmt]
    avatar_dir = Path(django_settings.MEDIA_ROOT) / 'avatars'
    avatar_dir.mkdir(parents=True, exist_ok=True)
    filename = f'{secrets.token_hex(16)}.{ext}'
    if fmt == 'JPEG':
        img.convert('RGB').save(avatar_dir / filename, 'JPEG', quality=90)
    else:
        img.save(avatar_dir / filename, 'PNG', optimize=True)

    old = request.user.avatar_url or ''
    if '/media/avatars/' in old:
        (avatar_dir / Path(old.split('/media/avatars/')[-1]).name).unlink(missing_ok=True)

    url = request.build_absolute_uri(f'/{django_settings.MEDIA_URL.strip("/")}/avatars/{filename}')
    request.user.avatar_url = url
    request.user.save(update_fields=['avatar_url'])
    return Response({'success': True, 'avatar_url': url, 'user': UserSerializer(request.user).data})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def posture_create(request):
    """
    POST /api/posture — 儲存坐姿感測數據。

    帶 device_id 時存到「那張椅子」目前入座的使用者名下（避免上傳裝置的帳號與前端登入帳號不同，
    導致前端看不到資料）；沒帶 device_id 時用呼叫者自己目前坐的椅子；都沒有就存在呼叫者名下。
    （正式的感測資料走 MQTT，這支主要給測試工具用）
    """
    error = validate_request(request.data, POSTURE_CREATE_SCHEMA)
    if error:
        return Response({'schema_error': error}, status=status.HTTP_400_BAD_REQUEST)

    device_id = request.data.get('device_id')
    session = active_session(chair_for_device(device_id)) if device_id else user_session(request.user)
    target_user = session.user if session else request.user

    data = request.data.copy()
    data.pop('device_id', None)

    if not data.get('posture'):
        calibration = user_calibration(target_user)
        baseline_seat = calibration.baseline_seat if calibration else None
        baseline_back = calibration.baseline_back if calibration else None
        predicted, confidence = predict_posture(
            data.get('seat_pressure_data'),
            back_pressure_data=data.get('back_pressure_data'),
            baseline_seat=baseline_seat,
            baseline_back=baseline_back,
        )
        if predicted:
            final_posture = _check_sedentary(target_user, predicted)
            data['posture'] = final_posture
            # sedentary 是依坐著時長覆蓋的規則判斷，不是這次 softmax 機率對應的類別，信心分數不適用
            data['confidence'] = confidence if final_posture == predicted else None
        else:
            return Response(
                {'error': '模型尚未載入，請先執行 python train_model_dl.py'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

    serializer = PostureRecordSerializer(data=data)
    if serializer.is_valid():
        serializer.save(user=target_user, chair=session.chair if session else None)
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
    POST /api/agent — 查詢 Physio Agent 建議，posture 必填，user_message 選填。

    【舊版同步介面，保留給尚未改版的 App】整個請求要等 OpenAI 回應（6～25 秒）才結束，
    期間佔住一條網頁伺服器執行緒。新流程請改用非同步任務：POST /api/agent/jobs → GET /api/agent/jobs/<id>。

    payload: { "posture": "left", "user_message": "我肩膀很痠" }  ← user_message 可省略
    回傳:    { "posture": "left", "posture_display": "身體左傾", "advice": "...",
               "steps": [{ "step": 1, "thought": "...", "action": "search_knowledge_base",
                          "action_input": {...}, "observation": "..." }, ...],
               "recommended_exercises": [{ "id": 1, "name": "...", "youtube_url": "...", ... }] }
    steps 是完整 ReAct 逐步紀錄（Thought/Action/Observation），給前端展示 Agent
    決策過程用，不是黑盒子產出最終文字而已。

    recommended_exercises 是依 posture 直接查表（stretch_video_map.json）附加的
    伸展動作＋YouTube 連結，不經過 LLM——Agent 的文字建議本身不知道這份資料，
    也不會在回覆裡引用影片連結，避免 LLM 複述連結時打錯字，也不用多一輪
    LLM 呼叫拖慢回應速度。
    """
    error = validate_request(request.data, AGENT_SCHEMA)
    if error:
        return Response({'schema_error': error}, status=status.HTTP_400_BAD_REQUEST)

    posture      = request.data.get('posture', '')
    # 選填欄位：沒帶、空字串、null、只有空白都視同沒填，不把空白當成症狀描述交給 Agent
    user_message = (request.data.get('user_message') or '').strip()

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
        'posture':               posture,
        'posture_display':       POSTURE_DISPLAY.get(posture, posture),
        'advice':                advice,
        'steps':                 steps,
        'recommended_exercises': _recommend_exercises(posture),
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def agent_job_create(request):
    """
    POST /api/agent/jobs — 送出 Physio Agent 非同步任務，立刻回 202 與任務編號。

    payload 與 POST /api/agent 相同：{ "posture": "left", "user_message": "" }（user_message 選填）
    回傳:    { "job_id": "...", "status": "queued", "poll_url": "/api/agent/jobs/<job_id>" }

    這支 API 只把請求存成一筆任務，不等 OpenAI，所以回應時間是毫秒等級；
    實際由 agent_worker 以 async/await 同時處理多筆任務，App 之後用 poll_url 查詢結果。
    """
    error = validate_request(request.data, AGENT_SCHEMA)
    if error:
        return Response({'schema_error': error}, status=status.HTTP_400_BAD_REQUEST)

    job = AgentJob.objects.create(
        user=request.user,
        posture=request.data.get('posture', ''),
        user_message=(request.data.get('user_message') or '').strip(),
    )
    return Response({
        'job_id':   str(job.id),
        'status':   job.status,
        'poll_url': f'/api/agent/jobs/{job.id}',
    }, status=status.HTTP_202_ACCEPTED)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def agent_job_detail(request, job_id):
    """
    GET /api/agent/jobs/<job_id> — 查詢 Physio Agent 任務狀態與結果（只能查自己的任務）。

    status：queued（排隊中）／running（處理中）／done（完成）／failed（失敗）
    done   時另外帶 posture、posture_display、advice、steps、recommended_exercises（與 POST /api/agent 相同）
    failed 時另外帶 error（中文失敗原因，例如 OpenAI 逾時）
    """
    job = AgentJob.objects.filter(id=job_id, user=request.user).first()
    if job is None:
        return Response({'error': '找不到此任務'}, status=status.HTTP_404_NOT_FOUND)

    data = {
        'job_id':      str(job.id),
        'status':      job.status,
        'created_at':  job.created_at,
        'started_at':  job.started_at,
        'finished_at': job.finished_at,
    }
    if job.status == AgentJob.STATUS_DONE and job.result:
        data.update(job.result)
    elif job.status == AgentJob.STATUS_FAILED:
        data['error'] = job.error
    return Response(data)


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
    # 只回傳坐姿提醒：自動離座、週報不應觸發硬體震動
    pending = list(
        Notification.objects.filter(user=request.user, is_sent=False, kind=Notification.KIND_POSTURE)
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
            'kind': n.kind,          # posture／auto_checkout／weekly，前端依此決定顯示方式
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
    """
    POST /api/chair/checkin — 使用者坐上某張椅子，之後這張椅子的感測資料都算在他名下。

    payload: { "device_id": "chair_A1B2C3" }   ← 選填；不帶時為舊韌體的 chair_01（舊版 App 不用改）
    同一張椅子原本坐的人、以及這位使用者原本坐的其他椅子，都會自動結束（一張椅子一人、一人一張椅子）。
    中立點送給這張椅子：校正過送個人值，沒校正送預設值（demo/calibration_design.md）。
    回應的 calibrated=false 時，App 應提示使用者校正（每次入座都提示，直到完成）。
    """
    device_id = (request.data.get('device_id') or Chair.LEGACY_DEVICE_ID).strip()
    chair = chair_for_device(device_id)
    _end_sessions(ChairSession.objects.filter(is_active=True, user=request.user).exclude(chair=chair))
    ChairSession.objects.filter(is_active=True, chair=chair).update(is_active=False)
    ChairSession.objects.create(user=request.user, chair=chair)
    push_neutral(chair, request.user)
    return Response({
        'status':     'checked_in',
        'username':   request.user.username,
        'device_id':  chair.device_id,
        'calibrated': user_calibration(request.user) is not None,
    })


def _end_sessions(sessions):
    """結束入座，並讓那些椅子恢復預設中立點（下一位使用者不會沿用前一位的個人校正）。"""
    for session in sessions.select_related('chair'):
        ChairSession.objects.filter(pk=session.pk).update(is_active=False)
        if session.chair:
            push_neutral(session.chair)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def chair_checkout(request):
    """POST /api/chair/checkout — 使用者離開椅子，椅子恢復預設中立點。"""
    _end_sessions(ChairSession.objects.filter(user=request.user, is_active=True))
    return Response({'status': 'checked_out'})


def _calibration_data(calibration):
    return {
        'neutral_x':     calibration.neutral_x,
        'neutral_y':     calibration.neutral_y,
        'samples':       calibration.samples,
        'method':        calibration.method,
        'baseline_seat': calibration.baseline_seat,
        'calibrated_at': calibration.calibrated_at,
    }


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def chair_calibrate(request):
    """
    POST /api/chair/calibrate — 直接指定坐正時的感測值作為個人校正（測試工具用；App 請用 /chair/calibration）。

    payload: { "seat_pressure_data": {...}, "back_pressure_data": {...} }
    """
    seat = request.data.get('seat_pressure_data')
    back = request.data.get('back_pressure_data') or None
    center = center_of_pressure(seat or {})
    if center is None:
        return Response({'error': '請提供有壓力的 seat_pressure_data'}, status=status.HTTP_400_BAD_REQUEST)

    session = user_session(request.user)
    calibration, _ = UserCalibration.objects.update_or_create(
        user=request.user,
        defaults={'neutral_x': center[0], 'neutral_y': center[1], 'baseline_seat': seat, 'baseline_back': back,
                  'samples': 1, 'method': UserCalibration.METHOD_BACKEND,
                  'device_id': session.chair.device_id if session and session.chair else ''},
    )
    if session and session.chair:
        push_neutral(session.chair, request.user)
    return Response({'status': 'calibrated', 'calibrated': True, **_calibration_data(calibration)})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def chair_calibrate_auto(request):
    """
    POST /api/chair/calibrate/auto — 【舊流程，保留給尚未改版的 App】由後端立即計算校正並回傳結果。

    用最近 20 秒收到的感測資料平均；新流程請改用 POST／GET /api/chair/calibration（由椅子計算，較準確）。
    回傳: { "status": "calibrated", "calibrated": true, "samples": N, "baseline_seat": {...}, "neutral_x", "neutral_y", ... }
    """
    session = user_session(request.user)
    if not session or not session.chair:
        return Response({'error': FAIL_MESSAGES['not_seated']}, status=status.HTTP_400_BAD_REQUEST)

    calibration, reason = calibrate_from_recent(request.user, session.chair)
    if reason:
        return Response({'error': FAIL_MESSAGES.get(reason, reason), 'reason': reason},
                        status=status.HTTP_404_NOT_FOUND if reason == 'no_data' else status.HTTP_400_BAD_REQUEST)
    return Response({'status': 'calibrated', 'calibrated': True, **_calibration_data(calibration)})


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def chair_calibration(request):
    """
    個人坐姿校正（新流程，設計見 demo/calibration_design.md）。

    POST /api/chair/calibration — 開始校正：請椅子取樣 5 秒（使用者需坐正不動），立即回 202
        回傳: { "request_id": "...", "status": "running", "duration_s": 5, "timeout_s": 10 }
    GET  /api/chair/calibration — 查詢自己最近一次校正（App 每秒查一次）
        status: running（校正中）／done（完成，附 calibration）／failed（失敗，附 reason 與中文 message）
        method: device（椅子計算）／backend（椅子 10 秒內沒回應，改用後端資料計算）
    """
    if request.method == 'POST':
        session = user_session(request.user)
        if not session or not session.chair:
            return Response({'error': FAIL_MESSAGES['not_seated']}, status=status.HTTP_400_BAD_REQUEST)
        calibration_request = start_calibration(request.user, session.chair)
        return Response({
            'request_id': str(calibration_request.id),
            'status':     calibration_request.status,
            'duration_s': CALIBRATION_DURATION_SECONDS,
            'timeout_s':  DEVICE_TIMEOUT_SECONDS,
        }, status=status.HTTP_202_ACCEPTED)

    calibration_request = CalibrationRequest.objects.filter(user=request.user).first()
    if calibration_request is None:
        calibration = user_calibration(request.user)
        return Response({'status': 'none', 'calibrated': calibration is not None,
                         'calibration': _calibration_data(calibration) if calibration else None})

    calibration_request = refresh_request(calibration_request)
    data = {
        'request_id': str(calibration_request.id),
        'status':     calibration_request.status,
        'method':     calibration_request.method,
        'device_id':  calibration_request.chair.device_id,
        'started_at': calibration_request.created_at,
    }
    if calibration_request.status == CalibrationRequest.STATUS_DONE:
        data['calibration'] = _calibration_data(user_calibration(request.user))
    elif calibration_request.status == CalibrationRequest.STATUS_FAILED:
        data['reason'] = calibration_request.reason
        data['message'] = FAIL_MESSAGES.get(calibration_request.reason, '校正失敗，請再試一次')
    return Response(data)


@api_view(['GET'])
def chair_status(request):
    """
    GET /api/chair/status?device_id=chair_A1B2C3 — 查詢某張椅子目前是誰在使用（不需要登入）。

    不帶 device_id 時查舊韌體的 chair_01（舊版 App 不用改）。回傳欄位與舊版相同，另外多 device_id、online。
    calibrated：目前坐的人是否已有個人校正（記在使用者身上，換椅子也算）。
    """
    chair = Chair.objects.filter(device_id=request.query_params.get('device_id') or Chair.LEGACY_DEVICE_ID).first()
    session = active_session(chair) if chair else None
    base = {'device_id': chair.device_id if chair else None, 'online': bool(chair and is_online(chair))}
    if session:
        return Response({
            **base,
            'active':     True,
            'username':   session.user.username,
            'since':      session.started_at,
            'calibrated': user_calibration(session.user) is not None,
        })
    return Response({**base, 'active': False, 'username': None, 'calibrated': False})


@api_view(['GET'])
def chair_list(request):
    """
    GET /api/chairs — 列出所有已登記的椅子與目前狀態（不需要登入）。

    椅子在後端第一次收到它的 MQTT 資料時自動登記。online＝最近 15 秒內有收到資料。
    """
    chairs = []
    for chair in Chair.objects.all():
        session = active_session(chair)
        chairs.append({
            'device_id':  chair.device_id,
            'name':       chair.name,
            'online':     is_online(chair),
            'last_seen':  chair.last_seen,
            'active':     bool(session),
            'username':   session.user.username if session else None,
            'since':      session.started_at if session else None,
        })
    return Response({'count': len(chairs), 'chairs': chairs})


# ── 伸展計劃（健康花園每日任務）────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def stretch_plan(request):
    """
    GET /api/agent/stretch-plan — 健康花園每日任務＋近 7 天壞坐姿統計。

    新欄位（10/31，前端健康花園用）:
        success:      true；只有後端出錯時為 false（tasks 仍是空陣列）
        tasks:        今天的 3 個任務（規則見 api/daily_plan.py），同一天內 id 固定
        source:       ai（AI 挑選＋個人化說明）／rule（AI 失敗，查表）／general（資料不足，通用動作）
        generated_at: 今天任務產生的時間
    舊欄位保留（period_days、total_bad_posture_records、posture_stats、recommended_exercises）。
    """
    try:
        plan = get_daily_plan(request.user)
    except Exception:
        logger.exception('每日任務產生失敗')
        return Response({'success': False, 'message': '目前無法產生今日伸展計畫，請稍後再試', 'tasks': []},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    cutoff  = timezone.now() - timedelta(days=7)
    records = PostureRecord.objects.filter(
        user=request.user,
        timestamp__gte=cutoff,
    ).exclude(posture__in=['normal', 'empty'])
    posture_counts = Counter(records.values_list('posture', flat=True))
    total = sum(posture_counts.values())
    posture_stats = {
        p: {
            'count':   c,
            'ratio':   round(c / total, 3),
            'display': POSTURE_DISPLAY.get(p, p),
        }
        for p, c in posture_counts.most_common()
    }

    # 舊欄位：依壞坐姿頻率查表的動作清單（最多 10 個）
    recommended, seen_ids = [], set()
    for posture, _ in posture_counts.most_common():
        for ex in _recommend_exercises(posture, limit=99):
            if ex['id'] not in seen_ids:
                seen_ids.add(ex['id'])
                recommended.append({**ex, 'triggered_by': POSTURE_DISPLAY.get(posture, posture)})

    body = {
        'success':                   True,
        'tasks':                     plan.tasks,
        'source':                    plan.source,
        'generated_at':              timezone.localtime(plan.generated_at).isoformat(),
        'period_days':               7,
        'total_bad_posture_records': total,
        'posture_stats':             posture_stats,
        'recommended_exercises':     recommended[:10],
    }
    if total == 0:
        body['message'] = '近 7 天無不良坐姿紀錄，繼續保持良好坐姿！'
    return Response(body)


# ── 伸展完成紀錄 ───────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def wellness_complete(request):
    """
    POST /api/wellness/complete — 回報完成一個伸展動作（每日任務或 AI 建議）。

    payload: { "exercise_id": 4, "source": "daily" | "ai", "feedback": "選填，最多 200 字" }
    同一動作同一天重複回報：200 並附 already_completed=true，不重複記錄；第一次回報 201。
    """
    exercise_id = request.data.get('exercise_id')
    source      = request.data.get('source')
    feedback    = request.data.get('feedback') or ''
    if not isinstance(exercise_id, int) or isinstance(exercise_id, bool) or exercise_id not in _exercises_by_id():
        return Response({'error': 'exercise_id 必須是伸展動作的編號（tasks 或 recommended_exercises 的 id）'},
                        status=status.HTTP_400_BAD_REQUEST)
    if source not in ('daily', 'ai'):
        return Response({'error': 'source 必須是 daily 或 ai'}, status=status.HTTP_400_BAD_REQUEST)
    if not isinstance(feedback, str) or len(feedback) > 200:
        return Response({'error': 'feedback 必須是 200 字以內的文字'}, status=status.HTTP_400_BAD_REQUEST)

    record, created = WellnessCompletion.objects.get_or_create(
        user=request.user, exercise_id=exercise_id, date=timezone.localdate(),
        defaults={'source': source, 'feedback': feedback.strip()},
    )
    return Response({'success': True, 'already_completed': not created, 'completion': _completion_json(record)},
                    status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def wellness_history(request):
    """GET /api/wellness/history?days=30 — 自己的伸展完成紀錄（新到舊），days 1～365。"""
    try:
        days = min(max(int(request.query_params.get('days', 30)), 1), 365)
    except ValueError:
        return Response({'error': 'days 必須是整數'}, status=status.HTTP_400_BAD_REQUEST)
    since   = timezone.localdate() - timedelta(days=days - 1)
    records = WellnessCompletion.objects.filter(user=request.user, date__gte=since)
    return Response({'days': days, 'count': records.count(), 'completions': [_completion_json(r) for r in records]})


def _completion_json(record):
    ex = _exercises_by_id().get(record.exercise_id, {})
    return {
        'exercise_id':  record.exercise_id,
        'title':        ex.get('name'),
        'source':       record.source,
        'feedback':     record.feedback,
        'date':         record.date.isoformat(),
        'completed_at': timezone.localtime(record.completed_at).isoformat(),
    }


# ── 馬達觸發 ───────────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def motor_trigger(request):
    """
    POST /api/motor/trigger — 依坐姿觸發對應馬達震動並寫入 MotorLog。

    payload: { "posture": "left" }
    回傳:    { "posture": "left", "motors": ["M3","M4"], "triggered": true, "device_id": "..." }

    手動觸發／測試用（即時提醒由椅子自己震動）。對應依硬體實際位置（api/motor_constants.py）：
        左傾 → M3 M4 | 右傾 → M1 M2 | 前傾 → M1 M4 | 後仰 → M2 M3 | 久坐 → M1 M2 M3 M4
    指令只送到呼叫者目前坐的那張椅子；沒有入座時送到舊韌體的 chair_01。
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

    # 發布真實馬達指令到使用者坐的那張椅子；硬體未連線時安靜失敗，不影響本次回應
    session = user_session(request.user)
    device_id = session.chair.device_id if session and session.chair else Chair.LEGACY_DEVICE_ID
    published = publish_motor_command(motors, topic=motor_topic(device_id))

    return Response({
        'posture':         posture,
        'posture_display': posture_name,
        'motors':          motors,
        'triggered':       True,
        'message':         message,
        'mqtt_published':  published is not None,
        'device_id':       device_id,
    })
