"""수집 중인 Apify 작업 상태 확인 (cron). 화면을 열어 두지 않아도 수집이 끝까지 진행되게 한다."""

from django.core.management.base import BaseCommand

from collector.services import poll_running_jobs


class Command(BaseCommand):
    help = "수집 중인 Apify 해시태그 수집 작업을 확인해 다음 단계로 넘긴다."

    def handle(self, *args, **options):
        count = poll_running_jobs()
        self.stdout.write(f"확인한 수집 작업: {count}건")
