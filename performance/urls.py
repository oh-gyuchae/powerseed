from django.urls import path

from . import views

app_name = "performance"

urlpatterns = [
    path("content/", views.content_list, name="list"),
    path("participations/<int:pk>/posts/add/", views.post_add, name="add"),
    path("reports/", views.report, name="report"),
]
