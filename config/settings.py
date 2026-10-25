"""
Configuración de OptiRuta — Sistema de Optimización de Rutas de Distribución.

Los valores sensibles se leen del archivo .env (ver .env.example).
"""
import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(nombre, defecto=False):
    return os.getenv(nombre, str(defecto)).lower() in ("1", "true", "yes", "si")


SECRET_KEY = os.getenv("SECRET_KEY", "dev-inseguro-cambiar-en-produccion")
DEBUG = env_bool("DEBUG", True)
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1,0.0.0.0").split(",")

# Publicación en Render (https://<nombre>.onrender.com)
RENDER_HOST = os.getenv("RENDER_EXTERNAL_HOSTNAME")
if RENDER_HOST:
    ALLOWED_HOSTS.append(RENDER_HOST)
CSRF_TRUSTED_ORIGINS = [f"https://{h}" for h in ALLOWED_HOSTS if h and "." in h and not h[0].isdigit()]
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
if RENDER_HOST:  # en internet todo viaja cifrado (HTTPS)
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 3600

INSTALLED_APPS = [
    "daphne",  # servidor ASGI: runserver atiende HTTP y WebSockets
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Terceros
    "rest_framework",
    "rest_framework_simplejwt",
    "django_filters",
    "drf_spectacular",
    "channels",
    # Propias (separación por capas / dominios)
    "apps.cuentas",
    "apps.logistica",
    "apps.optimizacion",
    "apps.reportes",
    "apps.web",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Middleware propio: mide el tiempo de cada petición a la API (Tema 8.3)
    "apps.logistica.middleware.TiempoRespuestaMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ----------------------------------------------------------------------------
# Tiempo real (Django Channels): en desarrollo funciona en memoria, sin instalar nada.
# En producción con varios procesos se usa Redis (variable REDIS_URL).
# ----------------------------------------------------------------------------
REDIS_URL = os.getenv("REDIS_URL", "")
if REDIS_URL:
    CHANNEL_LAYERS = {"default": {"BACKEND": "channels_redis.core.RedisChannelLayer",
                                  "CONFIG": {"hosts": [REDIS_URL]}}}
else:
    CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}

# ----------------------------------------------------------------------------
# Base de datos: PostgreSQL 17 (pgAdmin 4). Para pruebas rápidas: DB_ENGINE=sqlite
# ----------------------------------------------------------------------------
if os.getenv("DATABASE_URL"):  # producción (Render, Railway…)
    import dj_database_url

    DATABASES = {"default": dj_database_url.parse(os.environ["DATABASE_URL"], conn_max_age=600)}
elif os.getenv("DB_ENGINE", "postgres") == "sqlite":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("DB_NAME", "optiruta"),
            "USER": os.getenv("DB_USER", "postgres"),
            "PASSWORD": os.getenv("DB_PASSWORD", "postgres"),
            "HOST": os.getenv("DB_HOST", "localhost"),
            "PORT": os.getenv("DB_PORT", "5432"),
        }
    }

AUTH_USER_MODEL = "cuentas.Usuario"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
]

LANGUAGE_CODE = "es-pe"
TIME_ZONE = "America/Lima"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "/login/"

# Los servidores de mapas exigen saber desde qué sitio se piden las imágenes (cabecera Referer)
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

# ----------------------------------------------------------------------------
# Django REST Framework + JWT
# ----------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ),
    "DEFAULT_PAGINATION_CLASS": "apps.logistica.paginacion.Paginacion",
    "PAGE_SIZE": 20,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    # Throttling (Tema 8.2): evita abuso del login y de la API
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ),
    "DEFAULT_THROTTLE_RATES": {"anon": "60/min", "user": "1000/min", "login": "10/min"},
    "EXCEPTION_HANDLER": "apps.logistica.excepciones.manejador_errores",
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=int(os.getenv("JWT_ACCESS_MIN", "60"))),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=1),
    "AUTH_HEADER_TYPES": ("Bearer",),
}

SPECTACULAR_SETTINGS = {
    "TITLE": "OptiRuta API",
    "DESCRIPTION": "API REST del Sistema de Optimización de Rutas de Distribución (USS - Proyecto 4).",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "ENUM_NAME_OVERRIDES": {
        "EstadoPedidoEnum": "apps.logistica.models.PedidoDespacho.Estado",
        "EstadoRutaEnum": "apps.logistica.models.Ruta.Estado",
        "EstadoParadaEnum": "apps.logistica.models.ParadaRuta.Estado",
    },
}

# ----------------------------------------------------------------------------
# Caché (Tema 8.2): los reportes se cachean unos segundos
# ----------------------------------------------------------------------------
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

# ----------------------------------------------------------------------------
# Correo (Tema 5.2): en desarrollo se imprime en la consola
# ----------------------------------------------------------------------------
EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "OptiRuta <no-responder@optiruta.pe>")

# ----------------------------------------------------------------------------
# Parámetros del negocio y del motor de optimización
# ----------------------------------------------------------------------------
OPTIRUTA = {
    # Centro de distribución (almacén) de la empresa ficticia, Chiclayo
    "DEPOSITO_LAT": float(os.getenv("DEPOSITO_LAT", "-6.778810")),
    "DEPOSITO_LNG": float(os.getenv("DEPOSITO_LNG", "-79.868766")),
    "DEPOSITO_NOMBRE": "Centro de Distribución OptiRuta",
    "VELOCIDAD_KMH": 25.0,          # velocidad urbana promedio
    "FACTOR_CIRCUITO": 1.3,         # la calle real es ~30% más larga que la línea recta
    "MINUTOS_SERVICIO": 8,          # tiempo de descarga por parada
    "HORA_INICIO": "08:00",         # salida del almacén
    "PRECIO_COMBUSTIBLE_LITRO": 4.30,  # S/ por litro (referencial)
    "MAX_PARADAS_RUTA": 20,         # límite operativo de entregas por ruta
    "JORNADA_MAX_MIN": 540,         # 9 horas de jornada del conductor
}

# ----------------------------------------------------------------------------
# Celery (Tema 8.4)
#   · Sin configurar nada: cola en carpetas (.celery/), funciona en Windows sin Redis.
#   · Con REDIS_URL o CELERY_BROKER_URL: usa Redis (Docker / producción).
#   · CELERY_TASK_ALWAYS_EAGER=True ejecuta las tareas al instante sin worker (modo simple).
# ----------------------------------------------------------------------------
from celery.schedules import crontab  # noqa: E402

CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL") or REDIS_URL or "filesystem://"
if CELERY_BROKER_URL == "filesystem://":
    _cola = BASE_DIR / ".celery" / "cola"
    _procesados = BASE_DIR / ".celery" / "procesados"
    for _carpeta in (_cola, _procesados):
        _carpeta.mkdir(parents=True, exist_ok=True)
    CELERY_BROKER_TRANSPORT_OPTIONS = {
        "data_folder_in": str(_cola), "data_folder_out": str(_cola),
        "processed_folder": str(_procesados), "store_processed": False,
    }
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", True)
CELERY_TASK_IGNORE_RESULT = True
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULE_FILENAME = str(BASE_DIR / ".celery" / "beat-schedule")
CELERY_BEAT_SCHEDULE = {
    # Todos los días a las 22:00 (hora de Lima): cierre operativo del día
    "cierre-diario": {"task": "apps.logistica.tasks.cierre_diario", "schedule": crontab(hour=22, minute=0)},
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"consola": {"class": "logging.StreamHandler"}},
    "loggers": {
        "optiruta": {"handlers": ["consola"], "level": "INFO"},
    },
}
