import os
from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "truck_booking_app.settings")

app = Celery("truck_booking_app")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
