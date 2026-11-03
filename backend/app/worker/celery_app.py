from celery import Celery

from app.settings import get_settings

celery_app = Celery("norvia", broker=get_settings().redis_url, include=["app.worker.tasks"])
celery_app.conf.update(
    # [D4] El mensaje se confirma al TERMINAR la tarea: si el worker muere, Redis lo reentrega
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,  # con acks_late, no acaparar tareas que otro worker podría hacer
    # Si un worker muere, la tarea vuelve a la cola tras este tiempo (por defecto sería 1 h)
    broker_transport_options={"visibility_timeout": 600},
    task_time_limit=300,  # una ingesta colgada se mata antes de que se reentregue
    task_ignore_result=True,  # el estado vive en PostgreSQL, no en Celery [D4]
    broker_connection_retry_on_startup=True,
)

# Sweeper cada minuto (servicio `beat` aparte: un solo planificador aunque haya varios workers)
celery_app.conf.beat_schedule = {
    "sweep-stuck-documents": {"task": "sweep_stuck_documents", "schedule": 60.0},
}
