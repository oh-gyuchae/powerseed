from django.urls import path

from . import views

app_name = "campaigns"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("campaigns/<int:pk>/", views.campaign_board, name="board"),
    path("campaigns/<int:pk>/add/", views.campaign_add_influencers, name="add_influencers"),
    path("participations/<int:pk>/", views.participation_detail, name="participation"),
    path("participations/<int:pk>/stage/", views.participation_change_stage, name="change_stage"),
]
