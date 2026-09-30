from django.urls import path

from . import views

app_name = "bookings"

urlpatterns = [
    path("bulk-update/", views.bulk_update_bookings, name="bulk-update"),
    path("items/<int:pk>/", views.BookingDetailView.as_view(), name="booking-item"),
]
