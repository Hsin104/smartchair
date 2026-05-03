from django.contrib.auth import authenticate
from rest_framework import serializers
from .models import User, PostureRecord


class RegisterSerializer(serializers.ModelSerializer):
    """使用者註冊序列化器。"""
    password = serializers.CharField(write_only=True, min_length=6)

    class Meta:
        model = User
        fields = ['username', 'password', 'email', 'height', 'weight']

    def create(self, validated_data):
        # 用 create_user 確保密碼被正確雜湊
        user = User.objects.create_user(
            username=validated_data['username'],
            password=validated_data['password'],
            email=validated_data.get('email', ''),
            height=validated_data.get('height'),
            weight=validated_data.get('weight'),
        )
        return user


class LoginSerializer(serializers.Serializer):
    """使用者登入序列化器。"""
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        user = authenticate(username=data['username'], password=data['password'])
        if not user:
            raise serializers.ValidationError('帳號或密碼錯誤')
        data['user'] = user
        return data


class UserSerializer(serializers.ModelSerializer):
    """回傳使用者基本資料（不含密碼）。"""
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'height', 'weight']


class PostureRecordSerializer(serializers.ModelSerializer):
    """坐姿紀錄序列化器。"""
    class Meta:
        model = PostureRecord
        fields = ['id', 'timestamp', 'posture', 'seat_pressure_data', 'back_pressure_data']
        read_only_fields = ['id', 'timestamp']
