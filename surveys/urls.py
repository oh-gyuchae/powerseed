from django.urls import path

from . import views

app_name = "surveys"

urlpatterns = [
    path("campaigns/<int:pk>/survey/", views.survey_settings, name="settings"),
    path("campaigns/<int:pk>/survey/connect/", views.survey_connect, name="connect"),
    path("campaigns/<int:pk>/survey/sync/", views.survey_sync, name="sync"),
    path("campaigns/<int:pk>/survey/questions/", views.survey_questions, name="questions"),
    path(
        "campaigns/<int:pk>/survey/responses/<int:response_pk>/link/",
        views.survey_link_response,
        name="link_response",
    ),
]
