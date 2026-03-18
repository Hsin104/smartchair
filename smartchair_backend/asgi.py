"""
smartchair_backend 專案的 ASGI 設定。

將 ASGI callable 以模組層級變數 ``application`` 的形式對外公開。

詳細說明請參閱：
https://docs.djangoproject.com/en/6.0/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smartchair_backend.settings')

application = get_asgi_application()
