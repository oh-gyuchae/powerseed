"""Create demo data for local development: `python manage.py seed_demo`."""

from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from campaigns import services
from campaigns.models import PIPELINE, Campaign, Client, Stage
from influencers.models import Influencer


class Command(BaseCommand):
    help = "로컬 개발용 데모 데이터(관리자 계정 admin/admin, 캠페인 1개, 인플루언서 14명)를 만듭니다."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("DEBUG=1 환경에서만 실행할 수 있습니다.")
        with transaction.atomic():
            self._seed()

    def _seed(self):
        User = get_user_model()
        admin, created = User.objects.get_or_create(
            username="admin", defaults={"is_staff": True, "is_superuser": True}
        )
        if created:
            admin.set_password("admin")
            admin.save()
            self.stdout.write("관리자 계정 생성: admin / admin")

        client, _ = Client.objects.get_or_create(name="데모 고객사")
        campaign, created = Campaign.objects.get_or_create(
            client=client,
            name="데모 카페 시딩",
            defaults={
                "status": Campaign.Status.ACTIVE,
                "visit_location": "서울 성동구 데모카페",
                "default_fee": 100000,
                "manager": admin,
            },
        )
        if not created:
            self.stdout.write("데모 캠페인이 이미 있습니다. 건너뜁니다.")
            return

        now = timezone.now()
        stages = PIPELINE + [Stage.DECLINED, Stage.DROPPED]
        for i, stage in enumerate(stages, start=1):
            influencer, _ = Influencer.objects.get_or_create(
                instagram_handle=f"demo_creator_{i:02d}",
                defaults={
                    "account_name": f"데모 크리에이터 {i}",
                    "follower_count": 5000 * i,
                    "monthly_reels_avg": 3000 * i,
                    "owner": admin,
                },
            )
            p, _ = services.add_to_campaign(influencer, campaign, user=admin)
            # Walk the pipeline so StatusLog history looks realistic.
            target = PIPELINE.index(stage) if stage in PIPELINE else 2
            for step in PIPELINE[1 : target + 1]:
                services.change_stage(p, step, user=admin)
            if stage in (Stage.DECLINED, Stage.DROPPED):
                services.change_stage(p, stage, user=admin)
            if stage in (Stage.CONFIRMED, Stage.VISIT_SCHEDULED):
                p.confirmed_visit_at = now + timedelta(days=-1 if stage == Stage.CONFIRMED else 2)
                p.upload_due_at = p.confirmed_visit_at + timedelta(days=3)
                p.save()
        self.stdout.write(self.style.SUCCESS(f"데모 캠페인 생성 완료: /campaigns/{campaign.pk}/"))
