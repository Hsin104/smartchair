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


# 快速開發設定（不適用於正式環境）
# 正式部署前請參閱：https://docs.djangoproject.com/en/6.0/howto/deployment/checklist/

# 安全警告：請勿將 SECRET_KEY 洩漏至版本控制或公開環境！
SECRET_KEY = 'django-insecure-w%*nn(%0v5!&b3r9*q_7s$g!*hznocoz9%in21lp66a%0u_)v)'

# 安全警告：正式環境請將 DEBUG 設為 False！
DEBUG = True

ALLOWED_HOSTS = []


# 已安裝的應用程式

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'rest_framework.authtoken',
    'api',
]

# 使用自訂 User Model
AUTH_USER_MODEL = 'api.User'

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
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

# Django REST Framework 設定
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.TokenAuthentication',
    ],
}

# Gemini API
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')

# MQTT Broker 設定
MQTT_HOST     = os.getenv('MQTT_HOST', 'localhost')
MQTT_PORT     = int(os.getenv('MQTT_PORT', 1883))
MQTT_USERNAME = os.getenv('MQTT_USERNAME', '')
MQTT_PASSWORD = os.getenv('MQTT_PASSWORD', '')
MQTT_USE_TLS  = os.getenv('MQTT_USE_TLS', 'false').lower() == 'true'
