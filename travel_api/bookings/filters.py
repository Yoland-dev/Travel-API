from django_filters import rest_framework as filters

from .models import Accommodation, Booking


class BookingFilter(filters.FilterSet):
    status = filters.MultipleChoiceFilter(choices=Booking.StatusChoices.choices)
    booking_type = filters.CharFilter(method="filter_type")
    date_from = filters.DateFilter(field_name="booking_date", lookup_expr="gte")
    date_to = filters.DateFilter(field_name="booking_date", lookup_expr="lte")

    def filter_type(self, queryset, name, value):
        if value == "accommodation":
            return queryset.filter(accommodation__isnull=False)
        if value == "activity":
            return queryset.filter(activity__isnull=False)
        return queryset

    class Meta:
        model = Booking
        fields = ["status", "itinerary"]


class AccommodationFilter(filters.FilterSet):
    max_price = filters.NumberFilter(field_name="price_per_night", lookup_expr="lte")
    min_price = filters.NumberFilter(field_name="price_per_night", lookup_expr="gte")
    guests = filters.NumberFilter(field_name="max_guests", lookup_expr="gte")

    class Meta:
        model = Accommodation
        fields = ["destination", "accommodation_type", "is_available"]
