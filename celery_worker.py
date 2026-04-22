from celery import Celery
from video_generator import generate_video_task

celery = Celery('worker', broker='redis://localhost:6379/0', backend='redis://localhost:6379/0')
celery.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
)

if __name__ == '__main__':
    celery.start()