from django.urls import path

from . import views

app_name = "itineraries"

# Specific paths first: they must win over the router's /itineraries/<pk>/ pattern.
urlpatterns = [
    path("search/", views.trip_search, name="trip-search"),
    path("mine/", views.ItineraryListCreateView.as_view(), name="itinerary-mine"),
    path("<int:trip_id>/report/", views.generate_trip_report, name="trip-report"),
    path("<int:trip_id>/collaborators/", views.TripCollaborationView.as_view(), name="collaborators"),
    path("<int:trip_id>/collaborators/<int:user_id>/", views.TripCollaborationView.as_view(), name="collaborator-detail"),
    path("<int:trip_id>/documents/", views.ItineraryDocumentListCreateView.as_view(), name="documents"),
    path("<int:trip_id>/documents/<int:pk>/", views.ItineraryDocumentDetailView.as_view(), name="document-detail"),
]
