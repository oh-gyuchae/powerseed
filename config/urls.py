from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "PowerSeed 관리자"
admin.site.site_title = "PowerSeed"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),
    path("", include("campaigns.urls")),
    path("", include("sheets.urls")),
    path("", include("surveys.urls")),
    path("", include("messaging.urls")),
]
