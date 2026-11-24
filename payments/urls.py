from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path("payments/", views.payment_list, name="list"),
    path("participations/<int:pk>/payments/add/", views.payment_add, name="add"),
]
