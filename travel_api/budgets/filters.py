from django_filters import rest_framework as filters

from .models import Expense


class ExpenseFilter(filters.FilterSet):
    category = filters.MultipleChoiceFilter(choices=Expense.CategoryChoices.choices)
    min_amount = filters.NumberFilter(field_name="amount", lookup_expr="gte")
    max_amount = filters.NumberFilter(field_name="amount", lookup_expr="lte")
    date_from = filters.DateFilter(field_name="date", lookup_expr="gte")
    date_to = filters.DateFilter(field_name="date", lookup_expr="lte")

    class Meta:
        model = Expense
        fields = ["itinerary", "category", "paid_by"]
