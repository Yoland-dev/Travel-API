"""Destination filtering."""
from django_filters import rest_framework as filters

from .models import Destination


class DestinationFilter(filters.FilterSet):
    """Advanced destination filtering."""

    climate = filters.MultipleChoiceFilter(choices=Destination.ClimateChoices.choices)
    category = filters.MultipleChoiceFilter(choices=Destination.CategoryChoices.choices)
    country = filters.CharFilter(field_name="country", lookup_expr="iexact")
    min_cost = filters.NumberFilter(field_name="avg_daily_cost", lookup_expr="gte")
    max_cost = filters.NumberFilter(field_name="avg_daily_cost", lookup_expr="lte")
    budget_range = filters.CharFilter(method="filter_by_budget")

    def filter_by_budget(self, queryset, name, value):
        if value == "budget":
            return queryset.filter(avg_daily_cost__lt=100)
        if value == "moderate":
            return queryset.filter(avg_daily_cost__gte=100, avg_daily_cost__lt=250)
        if value == "luxury":
            return queryset.filter(avg_daily_cost__gte=250)
        return queryset

    class Meta:
        model = Destination
        fields = ["country", "category", "climate"]
