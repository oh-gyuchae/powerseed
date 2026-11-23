"""진행 중 캠페인의 구글 폼 응답을 모두 가져온다. 운영에서는 cron 등으로 주기 실행 (예: 10분마다)."""

from django.core.management.base import BaseCommand

from campaigns.models import Campaign
from surveys import services
from surveys.google_forms import GoogleFormsError
from surveys.models import CampaignForm


class Command(BaseCommand):
    help = "진행 중(준비중/진행중) 캠페인에 연결된 구글 폼의 문항·응답을 동기화합니다."

    def handle(self, *args, **options):
        forms = CampaignForm.objects.select_related("campaign").filter(
            campaign__status__in=[Campaign.Status.PLANNING, Campaign.Status.ACTIVE]
        )
        failed = 0
        for cf in forms:
            try:
                result = services.sync_form(cf)
            except GoogleFormsError as e:
                failed += 1
                self.stderr.write(f"[실패] {cf.campaign}: {e}")
                continue
            self.stdout.write(f"[완료] {cf.campaign}: {result.summary()}")
        if failed:
            self.stderr.write(self.style.ERROR(f"{failed}개 폼 동기화 실패"))
