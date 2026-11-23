from django.urls import path

from . import views

app_name = "collector"

urlpatterns = [
    path("collector/", views.job_list, name="jobs"),
    path("collector/jobs/<int:pk>/", views.job_review, name="review"),
    path("collector/jobs/<int:pk>/bulk/", views.job_bulk, name="bulk"),
]
