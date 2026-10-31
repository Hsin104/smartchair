from django.urls import path
from . import views

urlpatterns = [
    # 健康檢查（Docker HEALTHCHECK／監控用）
    path('health', views.health, name='health'),

    # 使用者認證
    path('register',               views.register,         name='register'),
    path('login',                  views.login,             name='login'),
    path('me',                     views.me,                name='me'),
    path('me/update',              views.update_me,         name='me-update'),
    path('me/avatar',              views.update_avatar,     name='me-avatar'),
    path('me/avatar/upload',       views.upload_avatar,     name='me-avatar-upload'),
    path('auth/change-password',   views.change_password,   name='change-password'),
    path('auth/forgot-password/request', views.forgot_password_request, name='forgot-password-request'),
    path('auth/forgot-password/verify',  views.forgot_password_verify,  name='forgot-password-verify'),
    path('users/exists',           views.user_exists,       name='user-exists'),

    # 坐姿數據
    path('posture',         views.posture_create,   name='posture-create'),
    path('posture/history', views.posture_history,  name='posture-history'),

    # Physio Agent
    path('agent',                views.agent_advice, name='agent-advice'),
    path('agent/jobs',           views.agent_job_create, name='agent-job-create'),
    path('agent/jobs/<uuid:job_id>', views.agent_job_detail, name='agent-job-detail'),
    path('agent/stretch-plan',   views.stretch_plan, name='stretch-plan'),

    # 馬達觸發
    path('motor/trigger',        views.motor_trigger, name='motor-trigger'),

    # 座椅佔用管理
    path('chair/checkin',   views.chair_checkin,   name='chair-checkin'),
    path('chair/checkout',  views.chair_checkout,  name='chair-checkout'),
    path('chair/calibrate',      views.chair_calibrate,      name='chair-calibrate'),
    path('chair/calibrate/auto', views.chair_calibrate_auto, name='chair-calibrate-auto'),
    path('chair/calibration',    views.chair_calibration,    name='chair-calibration'),
    path('chair/status',    views.chair_status,    name='chair-status'),
    path('chairs',          views.chair_list,      name='chair-list'),

    # 震動馬達通知（ESP32 輪詢用）
    path('notification/history', views.notification_history, name='notification-history'),
    path('notification/pending', views.notification_pending, name='notification-pending'),
    path('notification/ack',     views.notification_ack,     name='notification-ack'),
]
