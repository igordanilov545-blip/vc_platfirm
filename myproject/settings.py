"""
Django settings for myproject project.
"""

from pathlib import Path
import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
)
environ.Env.read_env(BASE_DIR / '.env')

SECRET_KEY = env('SECRET_KEY')
DEBUG = env('DEBUG')
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=[])

# ---------------------------------------------------------------------------
# Продакшн-настройки за обратным прокси (Beget / Passenger).
#
# На хостинге HTTPS терминируется фронтендом Beget, а до Django запрос доходит
# по HTTP с заголовком X-Forwarded-Proto. Без этих настроек Django считает
# соединение небезопасным и ломает secure-cookie, CSRF и редиректы.
#
# CSRF_TRUSTED_ORIGINS обязателен на Django 4+: для POST-форм и AJAX с HTTPS-домена
# нужно явно перечислить схему+хост, иначе получаем 403 CSRF. Берётся из .env
# (список полных origin'ов, напр. https://vc.iedanimk.beget.tech).
# ---------------------------------------------------------------------------
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
CSRF_TRUSTED_ORIGINS = env.list('CSRF_TRUSTED_ORIGINS', default=[])
USE_X_FORWARDED_HOST = True

# Secure-cookie управляются через .env, а не привязаны к DEBUG: пока на проде нет
# HTTPS (SSL ещё не выпущен), их нужно держать выключенными — иначе браузер не
# сохранит secure CSRF/session-cookie по http и вход в аккаунт падает с 403 CSRF.
# После выпуска SSL достаточно выставить COOKIE_SECURE=True в .env (без правки кода).
#
# По умолчанию в проде (DEBUG=False) — True: безопасно для целевого HTTPS. Локально
# (DEBUG=True) — всегда False, чтобы работал http://127.0.0.1.
_secure_cookies_default = not DEBUG
SESSION_COOKIE_SECURE = env.bool('COOKIE_SECURE', default=_secure_cookies_default)
CSRF_COOKIE_SECURE = env.bool('COOKIE_SECURE', default=_secure_cookies_default)
SECURE_SSL_REDIRECT = env.bool('SECURE_SSL_REDIRECT', default=False)

TG_BOT_TOKEN = env('TG_BOT_TOKEN', default='')
# Username бота без ведущего @ — нужен для Telegram Login Widget и deep-link
# «войти через бота» (t.me/<username>?start=weblogin) на странице входа.
TG_BOT_USERNAME = env('TG_BOT_USERNAME', default='')
# Публичный HTTPS-адрес сайта — нужен для кнопки запуска Mini App из бота
# (Telegram требует HTTPS; для локальной разработки — туннель вроде ngrok/cloudflared).
WEBAPP_URL = env('WEBAPP_URL', default='')

# Секрет для webhook-эндпоинта Telegram (см. tg_bot/webhook.py). Входит в непубличный
# путь `/tg/webhook/<secret>/` и в заголовок X-Telegram-Bot-Api-Secret-Token.
# На shared-хостинге Beget бот работает через webhook, а не long polling.
TG_WEBHOOK_SECRET = env('TG_WEBHOOK_SECRET', default='')

# Optional explicit LibreOffice executable (Windows paths may contain spaces).
SOFFICE_BIN = env('SOFFICE_BIN', default='')

# Закрытый список telegram_id, кому доступен технический дашборд аналитики (/analytics/)
# — не бизнес-роль (менеджер/ТЛ), а конкретные люди, которым доверена техническая
# диагностика нагрузки и внутренние логи. Пример в .env: ANALYTICS_ADMIN_TG_IDS=123456,789012
ANALYTICS_ADMIN_TG_IDS = set(env.list('ANALYTICS_ADMIN_TG_IDS', default=[]))


INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'blog',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'blog.middleware.TelegramWebAppFrameMiddleware',
    'blog.middleware.ActivityTrackingMiddleware',
]

ROOT_URLCONF = 'myproject.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'blog' / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'blog.context_processors.role_flags',
            ],
        },
    },
]

WSGI_APPLICATION = 'myproject.wsgi.application'


# Database
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases

if env('DB_ENGINE', default='sqlite') == 'postgres':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': env('DB_NAME'),
            'USER': env('DB_USER'),
            'PASSWORD': env('DB_PASSWORD'),
            'HOST': env('DB_HOST'),
            'PORT': env('DB_PORT'),
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
            # Сканер и бот пишут одновременно с аналитикой: резервируем запись до
            # чтений внутри atomic, чтобы не срывать повышение read-lock → write-lock.
            'OPTIONS': {'timeout': 20, 'transaction_mode': 'IMMEDIATE'},
        }
    }


AUTH_USER_MODEL = 'blog.User'

AUTHENTICATION_BACKENDS = [
    'blog.auth_backends.WebLoginBackend',
    'blog.auth_backends.TelegramWebAppBackend',
]

# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

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

LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'dashboard'
LOGOUT_REDIRECT_URL = 'login'


# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = 'ru'

TIME_ZONE = 'Europe/Moscow'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'blog' / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
STORAGES = {
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
    },
}

# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# ---------------------------------------------------------------------------
# Логирование (см. documentation/logging.md)
#
# Три независимых канала логов, каждый в свой файл в logs/ с ротацией:
#   - logs/web.log  — веб-приложение (вьюхи, сервисы, аутентификация Web/Mini App)
#   - logs/bot.log  — Telegram-бот (хендлеры aiogram, диспетчер уведомлений)
#   - logs/db.log   — прямой слой доступа к данным (data_base/data_controller.py)
#
# Каналы разведены по именам логгеров: логгер, чьё имя начинается на `vc.web`
# (или Django-логгеры), пишет в web.log; `vc.bot.*` — в bot.log; `vc.db.*` — в db.log.
# Код получает нужный логгер через blog.logging_utils.get_logger(...) или напрямую
# logging.getLogger('vc.web'/'vc.bot'/'vc.db').
# ---------------------------------------------------------------------------

LOG_DIR = env('LOG_DIR', default=str(BASE_DIR / 'logs'))
Path(LOG_DIR).mkdir(parents=True, exist_ok=True)

# Уровень логирования по каналам можно поднять/опустить через .env без правки кода.
LOG_LEVEL = env('LOG_LEVEL', default='INFO')

# Максимальный размер одного файла лога до ротации и число хранимых бэкапов.
LOG_MAX_BYTES = env.int('LOG_MAX_BYTES', default=5 * 1024 * 1024)  # 5 МБ
LOG_BACKUP_COUNT = env.int('LOG_BACKUP_COUNT', default=5)


def _rotating_handler(filename):
    return {
        'class': 'logging.handlers.RotatingFileHandler',
        'filename': str(Path(LOG_DIR) / filename),
        'maxBytes': LOG_MAX_BYTES,
        'backupCount': LOG_BACKUP_COUNT,
        'encoding': 'utf-8',
        'formatter': 'verbose',
        'level': LOG_LEVEL,
    }


LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{asctime} {levelname} [{name}] {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} [{name}] {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
            'level': LOG_LEVEL,
        },
        'web_file': _rotating_handler('web.log'),
        'bot_file': _rotating_handler('bot.log'),
        'db_file': _rotating_handler('db.log'),
    },
    'loggers': {
        # Веб-приложение (наш код) — vc.web.*
        'vc.web': {
            'handlers': ['web_file'],
            'level': LOG_LEVEL,
            'propagate': False,
        },
        # Telegram-бот — vc.bot.*
        'vc.bot': {
            'handlers': ['bot_file'],
            'level': LOG_LEVEL,
            'propagate': False,
        },
        # Прямой доступ к БД — vc.db.*
        'vc.db': {
            'handlers': ['db_file'],
            'level': LOG_LEVEL,
            'propagate': False,
        },
        # Ошибки самого Django (запросы, сервер) — в web.log, это часть веб-канала.
        'django': {
            'handlers': ['web_file'],
            'level': 'INFO',
            'propagate': False,
        },
        'django.request': {
            'handlers': ['web_file'],
            'level': 'WARNING',
            'propagate': False,
        },
        # Логи самой библиотеки aiogram — в bot.log.
        'aiogram': {
            'handlers': ['bot_file'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}

# В режиме отладки дублируем всё в консоль — удобно при локальной разработке.
# В контейнерах (LOG_TO_STDOUT=1) — тоже: тогда `docker logs <service>` показывает
# логи приложения, а файловые обработчики остаются для совместимости/ротации.
if DEBUG or env.bool('LOG_TO_STDOUT', default=False):
    for _logger in ('vc.web', 'vc.bot', 'vc.db', 'django', 'aiogram'):
        handlers = LOGGING['loggers'][_logger]['handlers']
        if 'console' not in handlers:
            handlers.append('console')
