from django.tasks import task

from . import services


@task
def run_hashtag_job(job_id: int):
    services.run_job(job_id)
