from django.urls import include, path

urlpatterns = [
    path("", include("hotspot.urls")),
    # Retain existing administration and reverse names for archived data.
    path("", include("config.urls")),
]
