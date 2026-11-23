from django.http import HttpResponse


class HealthCheckMiddleware:
    """배포 플랫폼의 상태 확인용. 내부 요청은 Host·HTTPS 조건이 다를 수 있어 가장 먼저 응답한다."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == "/healthz":
            return HttpResponse("ok", content_type="text/plain")
        return self.get_response(request)
