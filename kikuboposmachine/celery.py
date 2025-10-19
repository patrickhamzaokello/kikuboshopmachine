import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'kikuboposmachine.settings')

celery_app = Celery('kikuboposmachine')
celery_app.config_from_object('django.conf:settings', namespace='CELERY')
celery_app.autodiscover_tasks()

celery_app.conf.timezone = 'UTC'

celery_app.conf.beat_schedule = {


}
