from django.urls import path, register_converter

from . import views


class ExportFormatConverter:
    regex = "csv|xlsx"

    def to_python(self, value):
        return value

    def to_url(self, value):
        return value


register_converter(ExportFormatConverter, "exportfmt")

app_name = "sheets"

urlpatterns = [
    path("campaigns/<int:pk>/sheet/", views.campaign_sheet, name="sheet"),
    path("campaigns/<int:pk>/export.<exportfmt:fmt>", views.campaign_export, name="export"),
    path("participations/<int:pk>/row/", views.sheet_row, name="row"),
]
