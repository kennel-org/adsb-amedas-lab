from django.urls import path

from . import views

urlpatterns = [
    path("", views.map_view, name="map"),
    path("api/latest/", views.latest_points_api, name="latest_points_api"),
]
