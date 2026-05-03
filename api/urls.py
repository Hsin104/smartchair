from django.urls import path
from . import views

urlpatterns = [
    # 使用者認證
    path('register',        views.register,        name='register'),
    path('login',           views.login,            name='login'),
    path('me',              views.me,               name='me'),

    # 坐姿數據
    path('posture',         views.posture_create,   name='posture-create'),
    path('posture/history', views.posture_history,  name='posture-history'),

    # Physio Agent
    path('agent',           views.agent_advice,     name='agent-advice'),

    # 震動馬達通知（ESP32 輪詢用）
    path('notification/pending', views.notification_pending, name='notification-pending'),
    path('notification/ack',     views.notification_ack,     name='notification-ack'),
]
