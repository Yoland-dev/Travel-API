from django.urls import path

from . import views

app_name = "budgets"

urlpatterns = [
    path("itinerary/<int:trip_id>/", views.BudgetDetailView.as_view(), name="budget-detail"),
]
