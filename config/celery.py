"""
Celery (Tema 8.4): tareas en segundo plano y programadas.

Iniciar en Windows (sin Redis: la cola vive en la carpeta .celery/):
    celery -A config worker --pool=solo -l info      # ejecuta las tareas
    celery -A config beat -l info                    # dispara las tareas programadas
"""
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("optiruta")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
