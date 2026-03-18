"""
smartchair_backend 專案的 WSGI 設定。

將 WSGI callable 以模組層級變數 ``application`` 的形式對外公開。

詳細說明請參閱：
https://docs.djangoproject.com/en/6.0/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smartchair_backend.settings')

application = get_wsgi_application()
