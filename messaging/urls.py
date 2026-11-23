from django.urls import path

from . import views

app_name = "messaging"

urlpatterns = [
    path("participations/<int:pk>/messages/compose/", views.compose, name="compose"),
    path("participations/<int:pk>/messages/send/", views.send, name="send"),
    path("hooks/<str:provider>/", views.webhook, name="webhook"),
]
