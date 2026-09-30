"""Root URL configuration (API is versioned under /api/v1/)."""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter

from accounts.views import SavedSearchViewSet
from bookings.views import AccommodationViewSet, ActivityViewSet, BookingViewSet
from budgets.views import ExpenseViewSet
from destinations.views import DestinationViewSet
from itineraries.views import (
    ActivityLogViewSet, DailyPlanViewSet, ItineraryViewSet, TripAnalyticsViewSet,
)
from reviews.views import ReviewViewSet

router = DefaultRouter()
router.register(r"saved-searches", SavedSearchViewSet, basename="saved-search")
router.register(r"itineraries", ItineraryViewSet, basename="itinerary")
router.register(r"daily-plans", DailyPlanViewSet, basename="daily-plan")
router.register(r"activity-logs", ActivityLogViewSet, basename="activity-log")
router.register(r"analytics", TripAnalyticsViewSet, basename="analytics")
router.register(r"destinations", DestinationViewSet, basename="destination")
router.register(r"accommodations", AccommodationViewSet, basename="accommodation")
router.register(r"activities", ActivityViewSet, basename="activity")
router.register(r"bookings", BookingViewSet, basename="booking")
router.register(r"reviews", ReviewViewSet, basename="review")
router.register(r"expenses", ExpenseViewSet, basename="expense")

urlpatterns = [
    path("admin/", admin.site.urls),
    # API documentation
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
    # App-level routes come BEFORE the router so /itineraries/search/ is not read as a pk.
    path("api/v1/accounts/", include("accounts.urls")),
    path("api/v1/itineraries/", include("itineraries.urls")),
    path("api/v1/destinations/", include("destinations.urls")),
    path("api/v1/bookings/", include("bookings.urls")),
    path("api/v1/reviews/", include("reviews.urls")),
    path("api/v1/budgets/", include("budgets.urls")),
    path("api/v1/", include(router.urls)),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
