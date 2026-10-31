"""
smartchair_backend 專案的 URL 設定。

urlpatterns 清單負責將 URL 路由到對應的 view，詳細說明請參閱：
    https://docs.djangoproject.com/en/6.0/topics/http/urls/

範例：
函式型 view：
    1. 匯入：from my_app import views
    2. 加入路由：path('', views.home, name='home')

類別型 view：
    1. 匯入：from other_app.views import Home
    2. 加入路由：path('', Home.as_view(), name='home')

引入其他 URLconf：
    1. 匯入 include 函式：from django.urls import include, path
    2. 加入路由：path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.contrib import admin
from django.urls import path, include, re_path
from django.views.static import serve

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('api.urls')),
    # 使用者上傳的頭像：WhiteNoise 只處理 collectstatic 收集的檔案，上傳檔由 Django 直接回應（流量小）
    re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
]
