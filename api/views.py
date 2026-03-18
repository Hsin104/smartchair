from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.authtoken.models import Token

from .models import PostureRecord
from .serializers import (
    RegisterSerializer, LoginSerializer, UserSerializer, PostureRecordSerializer
)


@api_view(['POST'])
def register(request):
    """POST /api/register — 新使用者註冊。"""
    serializer = RegisterSerializer(data=request.data)
    if serializer.is_valid():
        user = serializer.save()
        token, _ = Token.objects.get_or_create(user=user)
        return Response({
            'token': token.key,
            'user': UserSerializer(user).data,
        }, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
def login(request):
    """POST /api/login — 登入並取得 Token。"""
    serializer = LoginSerializer(data=request.data)
    if serializer.is_valid():
        user = serializer.validated_data['user']
        token, _ = Token.objects.get_or_create(user=user)
        return Response({
            'token': token.key,
            'user': UserSerializer(user).data,
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
    """POST /api/posture — 儲存一筆坐姿感測數據（由 ESP32 或 MQTT 呼叫）。"""
    serializer = PostureRecordSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save(user=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def posture_history(request):
    """GET /api/posture/history — 查詢目前使用者的坐姿歷史紀錄。"""
    # 支援 ?limit=N 限制筆數，預設 50 筆
    limit = int(request.query_params.get('limit', 50))
    records = PostureRecord.objects.filter(user=request.user)[:limit]
    serializer = PostureRecordSerializer(records, many=True)
    return Response(serializer.data)
