from django.urls import path

from . import views

app_name = "influencers"

urlpatterns = [
    path("influencers/", views.influencer_list, name="list"),
]
