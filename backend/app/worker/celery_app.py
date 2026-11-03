from celery import Celery

from app.settings import get_settings

celery_app = Celery("norvia", broker=get_settings().redis_url)
