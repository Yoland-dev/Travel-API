from django.urls import path

from . import views

app_name = "reviews"

urlpatterns = [
    path("target/<str:target_type>/<int:target_id>/", views.TargetReviewsView.as_view(), name="target-reviews"),
]
