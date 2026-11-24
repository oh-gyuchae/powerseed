"""Create demo data for local development: `python manage.py seed_demo`."""

from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from campaigns import services
from campaigns.models import EXIT_STAGES, PIPELINES, Campaign, CampaignKind, Client, Participation, Stage
from core.choices import Country, Currency
from influencers.models import Category, Influencer
from messaging.models import MessageTemplate
from payments.models import ExchangeRate, Payment
from performance.models import ContentPost

DEMO_RATES = {Currency.USD: "1380", Currency.JPY: "9.2", Currency.EUR: "1490"}

# (핸들, 국가, 카테고리, 도착 단계)
OVERSEAS = [
    ("demo_us_glow", Country.US, Category.SKINCARE, Stage.PAID),
    ("demo_us_makeup", Country.US, Category.MAKEUP, Stage.UPLOADED),
    ("demo_us_hair", Country.US, Category.HAIR, Stage.DRAFT_REVIEW),
    ("demo_jp_beauty", Country.JP, Category.SKINCARE, Stage.UPLOADED),
    ("demo_jp_nail", Country.JP, Category.NAIL, Stage.SHIPPED),
    ("demo_fr_chic", Country.FR, Category.MAKEUP, Stage.NEGOTIATING),
    ("demo_fr_skin", Country.FR, Category.SKINCARE, Stage.DECLINED),
    ("demo_us_body", Country.US, Category.BODY, Stage.NO_RESPONSE),
    ("demo_jp_hair", Country.JP, Category.HAIR, Stage.CONTACT_TARGET),
]
CURRENCY_OF = {Country.US: Currency.USD, Country.JP: Currency.JPY, Country.FR: Currency.EUR}
FEE_OF = {Currency.USD: 800, Currency.JPY: 90000, Currency.EUR: 700}


class Command(BaseCommand):
    help = "로컬 개발용 데모 데이터(관리자 admin/admin, 방문형·배송형 캠페인 각 1개)를 만듭니다."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("DEBUG=1 환경에서만 실행할 수 있습니다.")
        with transaction.atomic():
            admin = self._admin()
            client, _ = Client.objects.get_or_create(name="데모 고객사")
            self._visit_campaign(admin, client)
            self._shipping_campaign(admin, client)

    def _admin(self):
        User = get_user_model()
        admin, created = User.objects.get_or_create(
            username="admin", defaults={"is_staff": True, "is_superuser": True}
        )
        if created:
            admin.set_password("admin")
            admin.save()
            self.stdout.write("관리자 계정 생성: admin / admin")

        MessageTemplate.objects.get_or_create(
            name="설문 안내",
            defaults={
                "subject": "[{{캠페인}}] 참여 설문 부탁드립니다",
                "body": (
                    "안녕하세요 {{이름}}님!\n"
                    "{{캠페인}} 시딩 관련해서 아래 설문 작성 부탁드려요.\n"
                    "{{설문링크}}\n"
                    "감사합니다."
                ),
            },
        )
        return admin

    @staticmethod
    def _walk(p, stage, admin):
        """Walk the pipeline so StatusLog history looks realistic."""
        pipeline = PIPELINES[p.campaign.kind]
        if stage in pipeline:
            target = pipeline.index(stage)
        else:
            target = 1 if stage == Stage.NO_RESPONSE else 2  # 무응답은 컨택 직후, 거절·이탈은 조금 진행한 뒤
        for step in pipeline[1 : target + 1]:
            services.change_stage(p, step, user=admin)
        if stage not in pipeline:
            services.change_stage(p, stage, user=admin)

    def _visit_campaign(self, admin, client):
        campaign, created = Campaign.objects.get_or_create(
            client=client,
            name="데모 카페 시딩",
            defaults={
                "kind": CampaignKind.VISIT,
                "status": Campaign.Status.ACTIVE,
                "visit_location": "서울 성동구 데모카페",
                "default_fee": 100000,
                "manager": admin,
            },
        )
        if not created:
            self.stdout.write("방문형 데모 캠페인이 이미 있습니다. 건너뜁니다.")
            return

        now = timezone.now()
        stages = PIPELINES[CampaignKind.VISIT] + EXIT_STAGES[CampaignKind.VISIT]
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
            self._walk(p, stage, admin)
            if stage in (Stage.CONFIRMED, Stage.VISIT_SCHEDULED):
                p.confirmed_visit_at = now + timedelta(days=-1 if stage == Stage.CONFIRMED else 2)
                p.upload_due_at = p.confirmed_visit_at + timedelta(days=3)
                p.save()
        self.stdout.write(self.style.SUCCESS(f"방문형 데모 캠페인 생성 완료: /campaigns/{campaign.pk}/"))

    def _shipping_campaign(self, admin, client):
        today = timezone.localdate()
        for currency, rate in DEMO_RATES.items():
            ExchangeRate.objects.get_or_create(
                currency=currency,
                effective_date=today - timedelta(days=30),
                defaults={"rate": Decimal(rate), "notes": "데모 환율"},
            )

        campaign, created = Campaign.objects.get_or_create(
            client=client,
            name="데모 해외 스킨케어 시딩",
            defaults={"kind": CampaignKind.SHIPPING, "status": Campaign.Status.ACTIVE, "manager": admin},
        )
        if not created:
            self.stdout.write("배송형 데모 캠페인이 이미 있습니다. 건너뜁니다.")
            return

        now = timezone.now()
        for i, (handle, country, category, stage) in enumerate(OVERSEAS, start=1):
            currency = CURRENCY_OF[country]
            influencer, _ = Influencer.objects.get_or_create(
                instagram_handle=handle,
                defaults={
                    "account_name": handle.replace("demo_", "").replace("_", " ").title(),
                    "country": country,
                    "category": category,
                    "languages": {Country.US: "영어", Country.JP: "일본어", Country.FR: "프랑스어"}[country],
                    "follower_count": 20000 * i,
                    "monthly_reels_avg": 15000 * i,
                    "engagement_rate": Decimal("3.5") + i % 3,
                    "desired_rate": FEE_OF[currency],
                    "desired_rate_currency": currency,
                    "owner": admin,
                },
            )
            p, _ = services.add_to_campaign(
                influencer,
                campaign,
                user=admin,
                defaults={
                    "fee_amount": FEE_OF[currency],
                    "fee_currency": currency,
                    "collab_type": Participation.CollabType.PAID,
                    "deliverables": "릴스 1 + 스토리 2",
                },
            )
            self._walk(p, stage, admin)
            p.refresh_from_db()
            if p.shipped_at:
                p.carrier, p.tracking_number = "DHL", f"DEMO{i:08d}"
                p.product_cost, p.shipping_cost = 35000, 42000
            # 업로드 예정일: 초안 검수 중인 건은 이미 지나 '업로드 예정일 경과'로 표시된다
            if stage in (Stage.SHIPPED, Stage.DRAFT_REVIEW):
                p.upload_due_at = now + timedelta(days=5 if stage == Stage.SHIPPED else -2)
            p.next_action = {Stage.NEGOTIATING: "단가 회신 대기", Stage.SHIPPED: "수령 확인 DM"}.get(stage, "")
            p.save()

            if stage in (Stage.UPLOADED, Stage.PAID):
                ContentPost.objects.create(
                    participation=p,
                    url=f"https://www.instagram.com/reel/DEMO{i:04d}/",
                    posted_at=today - timedelta(days=10 * i),
                    views_d7=12000 * i,
                    likes_d7=900 * i,
                    comments_d7=40 * i,
                    saves_d7=120 * i,
                    shares_d7=60 * i,
                    views_d30=20000 * i if stage == Stage.PAID else None,
                    likes_d30=1400 * i if stage == Stage.PAID else None,
                    discount_code_uses=15 * i,
                    revenue=900000 * i,
                )
                Payment.objects.create(
                    participation=p,
                    installment=Payment.Installment.DEPOSIT if stage == Stage.UPLOADED else Payment.Installment.FULL,
                    amount=Decimal(FEE_OF[currency]) / (2 if stage == Stage.UPLOADED else 1),
                    currency=currency,
                    method=Payment.Method.PAYPAL,
                    fee=Decimal("12.50") if currency == Currency.USD else None,
                    tax_document=Payment.TaxDocument.W8BEN if country == Country.US else Payment.TaxDocument.NONE,
                    tax_document_received=country == Country.US,
                    invoice_received=True,
                    paid_at=today - timedelta(days=3),
                )
        self.stdout.write(self.style.SUCCESS(f"배송형 데모 캠페인 생성 완료: /campaigns/{campaign.pk}/"))
