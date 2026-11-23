"""구글 폼 연동: 문항 불러오기 -> 응답 가져오기 -> 인플루언서 매칭 -> 플랫폼에 옮겨 적기."""

import uuid
from dataclasses import dataclass, field
from urllib.parse import urlencode

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from campaigns import services as campaign_services
from campaigns.models import Participation, Stage
from influencers.models import Influencer, is_valid_handle, normalize_handle

from . import parsing
from .google_forms import GoogleFormsClient, GoogleFormsError
from .models import UNIQUE_TARGETS, CampaignForm, FormQuestion, FormResponse, Target

# 응답이 들어오면 '설문 응답'으로 옮길 단계 (이미 더 진행된 건은 그대로 둔다)
_BEFORE_RESPONDED = {Stage.CONTACT_TARGET, Stage.CONTACTED, Stage.SURVEY_SENT}


@dataclass
class SyncResult:
    questions: int = 0
    new: int = 0
    updated: int = 0
    unmatched: int = 0
    errors: list[str] = field(default_factory=list)

    def summary(self):
        text = f"문항 {self.questions}개, 새 응답 {self.new}건, 수정된 응답 {self.updated}건"
        if self.unmatched:
            text += f", 연결 필요 {self.unmatched}건"
        return text


# ---------------------------------------------------------------- 연결 / 동기화


def connect_form(campaign, form_url) -> CampaignForm:
    from .google_forms import parse_form_id

    form_id = parse_form_id(form_url)
    cf, _ = CampaignForm.objects.update_or_create(campaign=campaign, defaults={"form_id": form_id})
    return cf


def sync_form(cf: CampaignForm, client=None) -> SyncResult:
    """구글 폼에서 문항·응답을 모두 가져와 반영. API 오류는 last_error에 남기고 GoogleFormsError로 다시 던진다."""
    try:
        client = client or GoogleFormsClient.from_settings()
        form = client.get_form(cf.form_id)
        result = SyncResult(questions=refresh_questions(cf, form))
        for raw in client.list_responses(cf.form_id):
            _import_response(cf, raw, result)
    except GoogleFormsError as e:
        cf.last_error = str(e)
        cf.save(update_fields=["last_error", "updated_at"])
        raise
    result.unmatched = cf.responses.filter(participation__isnull=True).count()
    cf.synced_at = timezone.now()
    cf.last_error = ""
    cf.save(update_fields=["synced_at", "last_error", "updated_at"])
    return result


@transaction.atomic
def refresh_questions(cf: CampaignForm, form: dict) -> int:
    """폼 구조를 FormQuestion으로. 새 문항은 제목으로 칸을 추정하고, 기존 문항의 매핑은 유지한다."""
    cf.title = (form.get("info") or {}).get("title", "")[:300]
    cf.responder_uri = form.get("responderUri", "")
    cf.save(update_fields=["title", "responder_uri", "updated_at"])

    existing = {q.question_id: q for q in cf.questions.all()}
    taken = {q.target for q in existing.values() if q.is_active and q.target in UNIQUE_TARGETS}
    seen = set()
    for position, (qid, title, kind, options) in enumerate(_iter_questions(form)):
        seen.add(qid)
        q = existing.get(qid)
        if q is None:
            target = parsing.guess_target(title)
            if target in taken:
                target = Target.EXTRA  # 같은 칸에 두 문항이 겹치지 않게
            taken.add(target)
            q = FormQuestion(form=cf, question_id=qid, target=target)
        q.title, q.kind, q.options, q.position, q.is_active = title[:500], kind, options, position, True
        q.save()
    cf.questions.exclude(question_id__in=seen).update(is_active=False)
    return len(seen)


def _iter_questions(form):
    for item in form.get("items", []):
        title = item.get("title", "")
        if "questionItem" in item:
            question = item["questionItem"]["question"]
            yield question["questionId"], title, *_kind(question)
        elif "questionGroupItem" in item:  # 객관식 그리드: 행마다 질문 하나
            for question in item["questionGroupItem"].get("questions", []):
                row = (question.get("rowQuestion") or {}).get("title", "")
                yield question["questionId"], f"{title} - {row}", "grid", []


def _kind(question):
    if "choiceQuestion" in question:
        choice = question["choiceQuestion"]
        kind = {"RADIO": "radio", "CHECKBOX": "checkbox", "DROP_DOWN": "dropdown"}.get(choice.get("type"), "choice")
        return kind, [o.get("value", "") for o in choice.get("options", []) if "value" in o]
    for key, kind in [
        ("textQuestion", "text"),
        ("dateQuestion", "date"),
        ("timeQuestion", "time"),
        ("scaleQuestion", "scale"),
        ("ratingQuestion", "rating"),
        ("fileUploadQuestion", "file"),
    ]:
        if key in question:
            if key == "textQuestion" and question[key].get("paragraph"):
                return "paragraph", []
            return kind, []
    return "other", []


def _import_response(cf, raw, result):
    submitted_at = parse_datetime(raw.get("lastSubmittedTime") or raw.get("createTime"))
    answers = {}
    for qid, answer in (raw.get("answers") or {}).items():
        if "textAnswers" in answer:
            answers[qid] = [a.get("value", "") for a in answer["textAnswers"].get("answers", [])]
        elif "fileUploadAnswers" in answer:
            answers[qid] = [a.get("fileName", "") for a in answer["fileUploadAnswers"].get("answers", [])]

    resp, created = FormResponse.objects.get_or_create(
        form=cf, response_id=raw["responseId"], defaults={"answers": answers, "submitted_at": submitted_at}
    )
    if not created and resp.submitted_at == submitted_at:
        return  # 변경 없음
    resp.answers, resp.submitted_at = answers, submitted_at
    resp.respondent_handle = _answer_for(cf, resp, Target.INSTAGRAM_HANDLE, handle=True)
    if resp.participation_id is None:
        resp.participation, resp.match_method = _match(cf, resp)
    resp.save()
    if created:
        result.new += 1
    else:
        result.updated += 1
    if resp.participation_id:
        apply_response(resp)


def _answer_for(cf, resp, target, *, handle=False):
    q = next((q for q in _active_questions(cf) if q.target == target), None)
    values = resp.answers.get(q.question_id, []) if q else []
    value = values[0].strip() if values else ""
    return normalize_handle(value) if handle else value


def _active_questions(cf):
    cache = getattr(cf, "_active_questions_cache", None)
    if cache is None:
        cache = cf._active_questions_cache = list(cf.questions.filter(is_active=True))
    return cache


def _match(cf, resp):
    participations = Participation.objects.filter(campaign=cf.campaign)
    code = _answer_for(cf, resp, Target.PARTICIPATION_CODE)
    if code:
        try:
            p = participations.filter(survey_token=uuid.UUID(code)).first()
        except ValueError:
            p = None
        if p:
            return p, FormResponse.MatchMethod.CODE
    handle = resp.respondent_handle
    if handle:
        p = participations.filter(influencer__instagram_handle=handle).first()
        if p:
            return p, FormResponse.MatchMethod.HANDLE
    return None, ""


# ---------------------------------------------------------------- 옮겨 적기


@transaction.atomic
def apply_response(resp: FormResponse, *, user=None):
    """응답 1건을 연결된 참여 건/인플루언서에 옮겨 적는다. 같은 응답을 여러 번 반영해도 결과는 같다."""
    p = resp.participation
    influencer = p.influencer
    year = (p.campaign.start_date or timezone.localdate()).year
    extras = dict(p.form_answers or {})

    for q in _active_questions(resp.form):
        values = [v for v in resp.answers.get(q.question_id, []) if v.strip()]
        if not values or q.target in (Target.IGNORE, Target.PARTICIPATION_CODE, Target.INSTAGRAM_HANDLE):
            continue
        text = ", ".join(values)
        match q.target:
            case Target.EXTRA:
                extras[q.question_id] = text
            case Target.ACCOUNT_NAME:
                influencer.account_name = text[:100]
            case Target.EMAIL:
                email = values[0].strip()
                try:
                    validate_email(email)
                    influencer.email = email
                except ValidationError:
                    pass
            case Target.FOLLOWER_COUNT:
                influencer.follower_count = parsing.parse_amount(text) or influencer.follower_count
            case Target.MONTHLY_REELS_AVG:
                avg = parsing.parse_amount(text)
                if avg is not None:
                    influencer.monthly_reels_avg = avg
                    influencer.reels_avg_source = Influencer.ReelsAvgSource.SURVEY
                    influencer.reels_avg_updated_at = timezone.now()
            case Target.PARTICIPATION_STATUS if not p.is_closed:
                p.participation_status = parsing.parse_participation_status(text) or p.participation_status
            case Target.AVAILABLE_VISIT_DATES:
                p.available_visit_dates = parsing.parse_dates(values, year=year) or p.available_visit_dates
            case Target.FEE_REQUESTED:
                p.fee_requested = parsing.parse_amount(text) or p.fee_requested
            case Target.PAYOUT_METHOD:
                p.payout_method = parsing.parse_payout_method(text) or p.payout_method
            case Target.SPECIAL_NOTES:
                p.special_notes = text

    p.form_answers = extras
    p.survey_submitted_at = resp.submitted_at
    influencer.save()
    p.save()
    if p.stage in _BEFORE_RESPONDED:
        campaign_services.change_stage(p, Stage.RESPONDED, user=user, memo="구글 폼 응답")
    resp.applied_at = timezone.now()
    resp.save(update_fields=["applied_at", "updated_at"])


def reapply_all(cf: CampaignForm, *, user=None) -> int:
    """매핑을 바꾼 뒤 저장된 응답을 다시 옮겨 적기 (API 호출 없음). 제출 순서대로 적용해 최신 응답이 남는다."""
    count = 0
    for resp in cf.responses.filter(participation__isnull=False).select_related("participation").order_by(
        "submitted_at"
    ):
        apply_response(resp, user=user)
        count += 1
    return count


@transaction.atomic
def link_response(resp: FormResponse, participation=None, *, user=None):
    """매칭 안 된 응답을 수동 연결. participation이 없으면 응답자 인스타 계정으로 새로 캠페인에 추가한다."""
    if participation is None:
        handle = resp.respondent_handle
        if not is_valid_handle(handle):
            raise ValueError("응답에 올바른 인스타 계정이 없어 새로 추가할 수 없습니다.")
        influencer, _ = Influencer.objects.get_or_create(
            instagram_handle=handle, defaults={"owner": user, "source": Influencer.Source.SURVEY}
        )
        participation, _ = campaign_services.add_to_campaign(influencer, resp.form.campaign, user=user)
    elif participation.campaign_id != resp.form.campaign_id:
        raise ValueError("다른 캠페인의 참여 건에는 연결할 수 없습니다.")
    resp.participation = participation
    resp.match_method = FormResponse.MatchMethod.MANUAL
    resp.save(update_fields=["participation", "match_method", "updated_at"])
    apply_response(resp, user=user)
    return participation


# ---------------------------------------------------------------- 개인 링크


def survey_link(participation) -> str:
    """인플루언서별 구글 폼 링크. '참여 코드' 문항이 있으면 코드가 미리 채워진 링크를 만든다."""
    cf = CampaignForm.objects.filter(campaign_id=participation.campaign_id).first()
    if cf is None or not cf.responder_uri:
        return ""
    code_q = cf.questions.filter(is_active=True, target=Target.PARTICIPATION_CODE).first()
    if code_q is None:
        return cf.responder_uri
    try:
        entry_id = int(code_q.question_id, 16)  # 미리 채우기 링크의 entry 번호 = 질문 ID(16진수)의 10진수 값
    except ValueError:
        return cf.responder_uri
    query = urlencode({"usp": "pp_url", f"entry.{entry_id}": str(participation.survey_token)})
    return f"{cf.responder_uri}?{query}"
