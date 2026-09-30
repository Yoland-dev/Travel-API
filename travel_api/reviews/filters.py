from django_filters import rest_framework as filters

from .models import Review


class ReviewFilter(filters.FilterSet):
    min_rating = filters.NumberFilter(field_name="rating", lookup_expr="gte")
    max_rating = filters.NumberFilter(field_name="rating", lookup_expr="lte")
    visited_after = filters.DateFilter(field_name="visit_date", lookup_expr="gte")

    class Meta:
        model = Review
        fields = ["destination", "accommodation", "activity", "rating", "user"]
