"""
smartchair_backend 專案的 Django 設定檔。

由 'django-admin startproject' 使用 Django 6.0.3 自動產生。

詳細說明請參閱：
https://docs.djangoproject.com/en/6.0/topics/settings/

所有設定值的完整列表請參閱：
https://docs.djangoproject.com/en/6.0/ref/settings/
"""

from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()

# 專案根目錄路徑，用法：BASE_DIR / '子目錄'
BASE_DIR = Path(__file__).resolve().parent.parent


# 安全設定：DEBUG 與 SECRET_KEY 都從 .env 讀取，不寫死在程式碼裡（repo 是公開的）。
# DEBUG 預設關閉；開著的話任何錯誤頁都會對外顯示完整路由表、程式路徑與部分設定值。
# 本機開發要看詳細錯誤頁，在本機 .env 設 DJANGO_DEBUG=true。
DEBUG = os.getenv('DJANGO_DEBUG', 'false').lower() == 'true'

# 舊金鑰從初始提交起就寫死在公開 repo 裡，已作廢。產生新金鑰：
#   python -c "import secrets; print(secrets.token_urlsafe(50))"
# 本機開發（DEBUG=true）沒設定時用一把開發專用的假金鑰；正式環境沒設定直接報錯，不默默用弱金鑰啟動。
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', '')
if not SECRET_KEY:
    if not DEBUG:
        from django.core.exceptions import ImproperlyConfigured
        raise ImproperlyConfigured('未設定 DJANGO_SECRET_KEY，請在 .env 加上（產生方式見 settings.py 註解）')
    SECRET_KEY = 'django-insecure-local-dev-only'

ALLOWED_HOSTS = ['*']  # 開發階段允許所有 host，部署前需改為實際 IP 或域名

# ngrok 對外是 https、轉進 Django 時是 http，admin 登入表單的 Origin（https://…）與 Django 認定的
# 網址（http://…）對不上，CSRF 檢查會直接 403。列在這裡的來源才放行；App 走 Token 驗證不受影響。
# 多個來源用逗號分隔，ngrok 網域變更時改 .env 的 CSRF_TRUSTED_ORIGINS 即可。
CSRF_TRUSTED_ORIGINS = os.getenv(
    'CSRF_TRUSTED_ORIGINS', 'https://sandbar-badass-subfloor.ngrok-free.dev'
).split(',')


# 已安裝的應用程式

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'corsheaders',
    'rest_framework',
    'rest_framework.authtoken',
    'api',
]

# 使用自訂 User Model
AUTH_USER_MODEL = 'api.User'

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    # Gunicorn 不像 runserver 會自動提供靜態檔，改由 WhiteNoise 直接從 STATIC_ROOT 回應
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'smartchair_backend.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'smartchair_backend.wsgi.application'


# 資料庫設定
# https://docs.djangoproject.com/en/6.0/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv('DB_NAME', 'smartchair'),
        'USER': os.getenv('DB_USER', 'admin'),
        'PASSWORD': os.getenv('DB_PASSWORD', 'admin123'),
        'HOST': os.getenv('DB_HOST', 'localhost'),
        'PORT': os.getenv('DB_PORT', '5432'),
        # 持久連線：預設 0 代表每個請求都新開一條 DB 連線、用完即關。Gunicorn 壓測時每秒開關數百條連線，
        # 關掉的連線在 TIME_WAIT 佔住本機埠，最後埠耗盡出現 "Cannot assign requested address"（health 503、
        # history 500）。docker-compose 的 django 服務設成 60 秒重用連線；本機 runserver 每個請求一條新
        # thread，持久連線反而會殘留，維持預設 0。
        'CONN_MAX_AGE': int(os.getenv('DB_CONN_MAX_AGE', 0)),
        'CONN_HEALTH_CHECKS': True,  # 重用前先確認連線還活著（例如 DB 容器重啟過）
    }
}


# 密碼驗證設定
# https://docs.djangoproject.com/en/6.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# 國際化設定
# https://docs.djangoproject.com/en/6.0/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'Asia/Taipei'

USE_I18N = True

USE_TZ = True


# 靜態檔案設定（CSS、JavaScript、圖片）
# https://docs.djangoproject.com/en/6.0/howto/static-files/

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'  # Dockerfile build 時 collectstatic 收集到這裡

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Django REST Framework 設定
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.TokenAuthentication',
    ],
}

# CORS 設定（允許瀏覽器跨來源存取 API）
from corsheaders.defaults import default_headers

CORS_ALLOW_ALL_ORIGINS = True

CORS_ALLOW_HEADERS = list(default_headers) + [
    'ngrok-skip-browser-warning',
    'authorization',
    'content-type',
]

# OpenAI API — Physio Agent 對話/推理 LLM ＋ RAG 知識庫 embeddings（教授提供之按量計費金鑰，節省用量）。
# Gemini 已完全移除（原僅供 embeddings 使用，FAISS index 已改用 OpenAI embeddings 重建）。
# OPENAI_MODEL 預設選省錢的輕量款，之後要換更高階型號只需改 .env，不需改程式碼。
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')
OPENAI_MODEL   = os.getenv('OPENAI_MODEL', 'gpt-4o-mini')

# 僅供壓力測試：> 0 時 Physio Agent 不呼叫 OpenAI，改成等待這麼多秒後回傳固定文字，
# 用來量「上千人同時問 AI」時伺服器的承載能力而不產生 OpenAI 費用。正式環境務必不設定（預設 0）。
AGENT_FAKE_LATENCY_SECONDS = float(os.getenv('AGENT_FAKE_LATENCY_SECONDS', 0))

# MQTT Broker 設定
MQTT_HOST     = os.getenv('MQTT_HOST', 'localhost')
MQTT_PORT     = int(os.getenv('MQTT_PORT', 1883))
MQTT_USERNAME = os.getenv('MQTT_USERNAME', '')
MQTT_PASSWORD = os.getenv('MQTT_PASSWORD', '')
MQTT_USE_TLS  = os.getenv('MQTT_USE_TLS', 'false').lower() == 'true'

# Physio Agent MCP Server 設定（python manage.py mcp_server 啟動的獨立服務）
MCP_SERVER_HOST = os.getenv('MCP_SERVER_HOST', 'localhost')
MCP_SERVER_PORT = int(os.getenv('MCP_SERVER_PORT', 8010))

# Tavily 網路搜尋 API（web_search MCP 工具用，未設定時該工具會優雅降級）
TAVILY_API_KEY = os.getenv('TAVILY_API_KEY', '')

# Email 設定（忘記密碼驗證碼信，使用 Gmail SMTP）
# EMAIL_HOST_PASSWORD 需為 Gmail「應用程式密碼」，而非一般登入密碼
EMAIL_BACKEND       = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST          = 'smtp.gmail.com'
EMAIL_PORT          = 587
EMAIL_USE_TLS       = True
EMAIL_HOST_USER     = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL  = os.getenv('EMAIL_HOST_USER', '')
