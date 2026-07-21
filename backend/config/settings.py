import os
from pathlib import Path
from datetime import timedelta
import warnings
from urllib.parse import urlparse, parse_qs
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

# Security and debug
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY')
DEBUG = os.environ.get('DEBUG', 'False').lower() in ('true', '1', 'yes')

if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured('DJANGO_SECRET_KEY must be set in production')
    warnings.warn('DJANGO_SECRET_KEY is not set; running in DEBUG mode with an insecure key', RuntimeWarning)

ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.postgres',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'django_rq',
    'corsheaders',
    'imagekit',
    'drf_spectacular',
    'storages',
    'api.apps.ApiConfig',
    'dashboard.apps.DashboardConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

# DATABASE configuration: support DATABASE_URL (Neon) or legacy DB_* envs
DATABASE_URL = os.environ.get('DATABASE_URL')
CONN_MAX_AGE = int(os.environ.get('CONN_MAX_AGE', 60))
if DATABASE_URL:
    # DATABASE_URL like: postgres://user:pass@host:port/dbname?sslmode=require
    url = urlparse(DATABASE_URL)
    opts = {}
    if url.query:
        qs = parse_qs(url.query)
        for key in ('sslmode', 'channel_binding', 'connect_timeout', 'keepalives', 'keepalives_idle'):
            if key in qs:
                opts[key] = qs[key][0]
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': url.path[1:],
            'USER': url.username,
            'PASSWORD': url.password,
            'HOST': url.hostname,
            'PORT': url.port or '',
            'CONN_MAX_AGE': CONN_MAX_AGE,
            'OPTIONS': opts,
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.environ.get('DB_NAME', 'iptv_db'),
            'USER': os.environ.get('DB_USER', 'postgres'),
            'PASSWORD': os.environ.get('DB_PASSWORD', 'postgres'),
            'HOST': os.environ.get('DB_HOST', 'localhost'),
            'PORT': os.environ.get('DB_PORT', '5432'),
            'CONN_MAX_AGE': CONN_MAX_AGE,
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = os.environ.get('MEDIA_URL', '/media/')
MEDIA_ROOT = BASE_DIR / 'media'

STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
    },
}

USE_S3 = os.environ.get('USE_S3', 'False').lower() in ('true', '1', 'yes')
if USE_S3:
    STORAGES['default'] = {'BACKEND': 'storages.backends.s3boto3.S3Boto3Storage'}
    AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID', '')
    AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY', '')
    AWS_STORAGE_BUCKET_NAME = os.environ.get('AWS_STORAGE_BUCKET_NAME', '')
    AWS_S3_REGION_NAME = os.environ.get('AWS_S3_REGION_NAME', 'us-east-1')
    AWS_S3_ENDPOINT_URL = os.environ.get('AWS_S3_ENDPOINT_URL', '')
    AWS_S3_CUSTOM_DOMAIN = os.environ.get('AWS_S3_CUSTOM_DOMAIN', '')
    AWS_DEFAULT_ACL = os.environ.get('AWS_DEFAULT_ACL', 'private')
    AWS_QUERYSTRING_AUTH = os.environ.get('AWS_QUERYSTRING_AUTH', 'True').lower() in ('true', '1', 'yes')
    AWS_S3_FILE_OVERWRITE = False
    AWS_S3_OBJECT_PARAMETERS = {'CacheControl': 'max-age=86400'}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
AUTH_USER_MODEL = 'api.CustomUser'

# REST framework
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': os.environ.get('THROTTLE_ANON_RATE', '30/hour'),
        'user': os.environ.get('THROTTLE_USER_RATE', '100/minute'),
    },
}

SPECTACULAR_SETTINGS = {
    'TITLE': 'Reseller Control Center API',
    'DESCRIPTION': 'IPTV reseller management system',
    'VERSION': '1.0.0',
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=int(os.environ.get('JWT_ACCESS_TOKEN_LIFETIME', 60))),
    'REFRESH_TOKEN_LIFETIME': timedelta(minutes=int(os.environ.get('JWT_REFRESH_TOKEN_LIFETIME', 1440))),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'AUTH_HEADER_TYPES': ('Bearer',),
}

CORS_ALLOWED_ORIGINS = os.environ.get('CORS_ALLOWED_ORIGINS', 'http://localhost:5173,http://localhost:80').split(',')
CORS_ALLOW_CREDENTIALS = True

# Redis/Cache configuration: prefer REDIS_URL if provided (Upstash-friendly)
REDIS_URL = os.environ.get('REDIS_URL')
if REDIS_URL:
    # Use the provided redis URL directly for django-redis
    CACHES = {
        'default': {
            'BACKEND': 'django_redis.cache.RedisCache',
            'LOCATION': REDIS_URL,
            'OPTIONS': {
                'CLIENT_CLASS': 'django_redis.client.DefaultClient',
                'COMPRESSOR': 'django_redis.compressors.zlib.ZlibCompressor',
            }
        }
    }
    # RQ queue config using the same URL
    RQ_QUEUES = {
        'default': {
            'URL': REDIS_URL,
            'DEFAULT_TIMEOUT': int(os.environ.get('RQ_DEFAULT_TIMEOUT', 360)),
        }
    }
else:
    CACHES = {
        'default': {
            'BACKEND': 'django_redis.cache.RedisCache',
            'LOCATION': 'redis://{host}:{port}/1'.format(
                host=os.environ.get('REDIS_HOST', 'localhost'),
                port=os.environ.get('REDIS_PORT', 6379),
            ),
            'OPTIONS': {
                'CLIENT_CLASS': 'django_redis.client.DefaultClient',
                'COMPRESSOR': 'django_redis.compressors.zlib.ZlibCompressor',
            }
        }
    }
    RQ_QUEUES = {
        'default': {
            'HOST': os.environ.get('REDIS_HOST', 'localhost'),
            'PORT': int(os.environ.get('REDIS_PORT', 6379)),
            'DB': int(os.environ.get('REDIS_DB', 0)),
            'DEFAULT_TIMEOUT': int(os.environ.get('RQ_DEFAULT_TIMEOUT', 360)),
        }
    }

FERNET_KEY = os.environ.get('FERNET_KEY', '')
if not FERNET_KEY:
    warnings.warn(
        'FERNET_KEY is not set. Password encryption/decryption will fail in production.',
        RuntimeWarning,
        stacklevel=2,
    )

RATE_LIMIT_PURCHASE = int(os.environ.get('RATE_LIMIT_PURCHASE', 5))
ASYNC_THRESHOLD = int(os.environ.get('ASYNC_THRESHOLD', 10))

# Helpful deployment hints (not used programmatically):
# - In production set DEBUG=False, DJANGO_SECRET_KEY and FERNET_KEY.
# - Provide DATABASE_URL for Neon: postgres://user:pass@host:port/dbname
# - Provide REDIS_URL for Upstash: rediss://:<token>@<host>:<port>
# - Use CONN_MAX_AGE=0 for serverless Postgres or configure pooling as recommended by Neon
