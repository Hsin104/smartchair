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
]
