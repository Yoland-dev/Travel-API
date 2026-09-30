from django.urls import path

from . import views

app_name = "destinations"

urlpatterns = [
    path("search/", views.DestinationSearchView.as_view(), name="destination-search"),
    path("recommendations/", views.recommendations, name="recommendations"),
    path("favorites/", views.favorites, name="favorites"),
    path("slug/<slug:slug>/", views.DestinationBySlugView.as_view(), name="destination-by-slug"),
]
