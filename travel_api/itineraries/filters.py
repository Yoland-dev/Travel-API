"""Filters for itineraries, bookings-independent."""
from django_filters import rest_framework as filters

from .models import Itinerary


class ItineraryFilter(filters.FilterSet):
    """Custom filters for itineraries."""

    min_budget = filters.NumberFilter(field_name="budget", lookup_expr="gte")
    max_budget = filters.NumberFilter(field_name="budget", lookup_expr="lte")
    start_date_after = filters.DateFilter(field_name="start_date", lookup_expr="gte")
    start_date_before = filters.DateFilter(field_name="start_date", lookup_expr="lte")
    destination_country = filters.CharFilter(field_name="destination__country", lookup_expr="iexact")
    status = filters.MultipleChoiceFilter(choices=Itinerary.STATUS_CHOICES)

    class Meta:
        model = Itinerary
        fields = ["status", "destination", "is_public"]
