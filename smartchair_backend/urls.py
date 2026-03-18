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
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('api.urls')),
]
