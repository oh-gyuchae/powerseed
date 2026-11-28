from django.urls import path

from . import views

app_name = "messaging"

urlpatterns = [
    path("participations/<int:pk>/messages/compose/", views.compose, name="compose"),
    path("participations/<int:pk>/messages/send/", views.send, name="send"),
    path("campaigns/<int:campaign_pk>/outreach/", views.outreach, name="outreach"),
    path("participations/<int:pk>/outreach/send/", views.outreach_send, name="outreach_send"),
    path("hooks/<str:provider>/", views.webhook, name="webhook"),
]
