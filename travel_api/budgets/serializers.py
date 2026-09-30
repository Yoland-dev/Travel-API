"""Budget and expense serializers."""
from decimal import Decimal

from rest_framework import serializers

from itineraries.models import ActivityLog
from itineraries.utils import log_activity

from .models import Budget, Expense


class BudgetSerializer(serializers.ModelSerializer):
    """Per-category allocation with computed totals."""

    total_budget = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True,
                                            help_text="Sum of all category allocations.")
    spent_by_category = serializers.SerializerMethodField(help_text="Actual spending per category.")
    unallocated = serializers.SerializerMethodField(help_text="Trip budget minus allocations.")

    class Meta:
        model = Budget
        fields = ["id", "itinerary", "accommodation_budget", "activities_budget", "food_budget",
                  "transport_budget", "shopping_budget", "miscellaneous_budget", "total_budget",
                  "spent_by_category", "unallocated", "created_at", "updated_at"]
        read_only_fields = ["id", "itinerary", "created_at", "updated_at"]

    def get_spent_by_category(self, obj):
        return {k: f"{Decimal(v):.2f}" for k, v in obj.spent_by_category().items()}

    def get_unallocated(self, obj):
        return f"{Decimal(obj.itinerary.budget - obj.total_budget):.2f}"

    def validate(self, attrs):
        current = self.instance
        fields = [f for f in self.Meta.fields if f.endswith("_budget") and f != "total_budget"]
        # Fall back to the stored value for fields not sent in a partial update.
        total = sum((attrs.get(f, getattr(current, f, Decimal("0"))) for f in fields), Decimal("0"))
        if current and total > current.itinerary.budget:
            raise serializers.ValidationError("Category budgets exceed the trip budget.")
        return attrs


class ExpenseSerializer(serializers.ModelSerializer):
    """Record spending against a trip."""

    paid_by_username = serializers.CharField(source="paid_by.username", read_only=True, default=None)

    class Meta:
        model = Expense
        fields = ["id", "itinerary", "category", "description", "amount", "date", "receipt", "notes",
                  "paid_by", "paid_by_username", "created_at", "updated_at"]
        read_only_fields = ["id", "paid_by", "created_at", "updated_at"]

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("Amount must be greater than zero.")
        return value

    def validate_itinerary(self, value):
        if self.instance and value.pk != self.instance.itinerary_id:
            raise serializers.ValidationError("An expense cannot be moved to another itinerary.")
        return value

    def create(self, validated_data):
        expense = Expense.objects.create(paid_by=self.context["request"].user, **validated_data)
        log_activity(expense.paid_by, ActivityLog.ActionChoices.EXPENSE, expense.itinerary,
                     f"Added expense '{expense.description}' ${expense.amount}")
        return expense

    def update(self, instance, validated_data):
        instance = super().update(instance, validated_data)  # signal refreshes the trip total
        log_activity(self.context["request"].user, ActivityLog.ActionChoices.EXPENSE, instance.itinerary,
                     f"Edited expense '{instance.description}'")
        return instance

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["amount_display"] = f"${instance.amount:,.2f}"
        data["category_display"] = instance.get_category_display()
        return data
