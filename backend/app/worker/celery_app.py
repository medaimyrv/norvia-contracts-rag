import os

from celery import Celery

# Provisional: en T03 la configuración pasa a pydantic-settings.
celery_app = Celery("norvia", broker=os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
