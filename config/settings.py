from pathlib import Path

import environ
from celery.schedules import crontab

BASE_DIR = Path(__file__).resolve().parent.parent
env = environ.Env(DEBUG=(bool, False))
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY", default="unsafe-local-development-key")
DEBUG = env("DEBUG", default=True)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1", "testserver"])
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
INSTALLED_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "channels",
    "trading",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
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
            ]
        },
    }
]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"
DATABASES = {"default": env.db("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}")}
if DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3":
    DATABASES["default"].setdefault("OPTIONS", {})["timeout"] = 30
AUTH_PASSWORD_VALIDATORS = []
LANGUAGE_CODE = "id-id"
TIME_ZONE = "Asia/Jakarta"
USE_I18N = True
USE_TZ = True
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REDIS_URL = env("REDIS_URL", default="")
CHANNEL_LAYERS = (
    {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {"hosts": [REDIS_URL]},
        }
    }
    if REDIS_URL
    else {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
)
if REDIS_URL:
    CELERY_BROKER_URL = REDIS_URL
    CELERY_RESULT_BACKEND = REDIS_URL
else:
    # Kombu's memory transport is process-local: embedded Beat can enqueue jobs
    # that the worker never sees. A filesystem queue keeps local PM2 scheduling
    # functional without Redis; production should set REDIS_URL.
    CELERY_QUEUE_DIR = BASE_DIR / ".runtime" / "celery-queue"
    CELERY_QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    CELERY_BROKER_URL = "filesystem://"
    CELERY_BROKER_TRANSPORT_OPTIONS = {
        "data_folder_in": str(CELERY_QUEUE_DIR),
        "data_folder_out": str(CELERY_QUEUE_DIR),
        "control_folder": str(CELERY_QUEUE_DIR),
        "store_processed": False,
    }
    CELERY_RESULT_BACKEND = "cache+memory://"
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULE = {
    "build-open-0930-plan": {
        "task": "trading.tasks.build_open_plan",
        "schedule": crontab(hour=9, minute=30, day_of_week="1-5"),
    },
    "build-midday-1130-plan": {
        "task": "trading.tasks.build_midday_plan",
        "schedule": crontab(hour=11, minute=30, day_of_week="1-5"),
    },
    "collect-intraday-candidates": {
        "task": "trading.tasks.collect_intraday_candidates",
        "schedule": crontab(minute="*/5", hour="9-15", day_of_week="1-5"),
    },
    "reconcile-paper-exits": {
        "task": "trading.tasks.auto_close_paper_positions",
        "schedule": crontab(minute="0,5,10,15,20,25,30", hour="16", day_of_week="1-5"),
    },
    "prepare-tomorrow-plan": {
        "task": "trading.tasks.build_daily_plan",
        "schedule": crontab(hour=16, minute=20, day_of_week="1-5"),
    },
    "validate-opening-setups": {
        "task": "trading.tasks.validate_live_setups",
        "schedule": crontab(hour=9, minute=5, day_of_week="1-5"),
    },
    "evaluate-yesterday-predictions": {
        "task": "trading.tasks.score_predictions",
        "schedule": crontab(hour=16, minute=30, day_of_week="1-5"),
    },
    # -----------------------------------------------------------------------
    # IDX-BEI Integration: Broker Flow, Fundamentals, Foreign Flow, Risk
    # -----------------------------------------------------------------------
    "sync-broker-flows-morning": {
        "task": "trading.tasks.sync_broker_flows_task",
        "schedule": crontab(hour=9, minute=35, day_of_week="1-5"),
    },
    "sync-broker-flows-midday": {
        "task": "trading.tasks.sync_broker_flows_task",
        "schedule": crontab(hour=12, minute=5, day_of_week="1-5"),
    },
    "sync-broker-flows-close": {
        "task": "trading.tasks.sync_broker_flows_task",
        "schedule": crontab(hour=16, minute=10, day_of_week="1-5"),
    },
    "sync-foreign-flows-daily": {
        "task": "trading.tasks.sync_foreign_flows_task",
        "schedule": crontab(hour=16, minute=35, day_of_week="1-5"),
    },
    "sync-risk-screens-daily": {
        "task": "trading.tasks.sync_risk_screens_task",
        "schedule": crontab(hour=17, minute=0, day_of_week="1-5"),
    },
    "sync-fundamentals-weekly": {
        "task": "trading.tasks.sync_fundamentals_task",
        "schedule": crontab(hour=6, minute=0, day_of_week="0"),  # Sunday 06:00 WIB
    },
}
QUANT_LIMITS = {
    "max_risk_per_trade": env.float("MAX_RISK_PER_TRADE", default=0.01),
    "max_daily_loss": env.float("MAX_DAILY_LOSS", default=0.02),
    "min_risk_reward": env.float("MIN_RISK_REWARD", default=1.5),
    "min_signal_score": env.float("MIN_SIGNAL_SCORE", default=65),
    "min_ml_probability": env.float("MIN_ML_PROBABILITY", default=0.65),
    "min_profit_factor": env.float("MIN_PROFIT_FACTOR", default=1.0),
}
NINEROUTER = {
    "base_url": env("NINEROUTER_BASE_URL", default="https://9router.com/v1").rstrip("/"),
    "api_key": env("NINEROUTER_API_KEY", default=""),
    "model": env("NINEROUTER_MODEL", default=""),
}
AUTO_PAPER_TRADING = {
    "enabled": env.bool("AUTO_PAPER_TRADING_ENABLED", default=True),
    "top_n": env.int("AUTO_PAPER_TOP_N", default=2),
    "expiry_minutes": env.int("AUTO_PAPER_EXPIRY_MINUTES", default=15),
}
