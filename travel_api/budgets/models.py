"""Budgets and expenses."""
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Sum

from core.validators import validate_file_size, validate_image_type
from itineraries.models import Itinerary


def _money(**kwargs):
    return models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)], **kwargs)


class Budget(models.Model):
    """Per-category budget allocation for an itinerary (one-to-one)."""

    itinerary = models.OneToOneField(Itinerary, on_delete=models.CASCADE, related_name="budget_detail")
    accommodation_budget = _money()
    activities_budget = _money()
    food_budget = _money()
    transport_budget = _money()
    shopping_budget = _money()
    miscellaneous_budget = _money()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Budget"

    def __str__(self):
        return f"Budget for {self.itinerary.title}"

    @property
    def total_budget(self):
        return (self.accommodation_budget + self.activities_budget + self.food_budget
                + self.transport_budget + self.shopping_budget + self.miscellaneous_budget)

    def category_budget(self, category):
        """Allocated amount for an Expense category value."""
        return getattr(self, f"{category}_budget")

    def spent_by_category(self):
        """Actual spending grouped by category, as {category: Decimal}."""
        rows = self.itinerary.expenses.values("category").annotate(total=Sum("amount"))
        spent = {c: Decimal("0") for c in Expense.CategoryChoices.values}
        spent.update({r["category"]: r["total"] for r in rows})
        return spent


class Expense(models.Model):
    """Individual expense within a trip budget."""

    class CategoryChoices(models.TextChoices):
        ACCOMMODATION = "accommodation", "Accommodation"
        ACTIVITIES = "activities", "Activities"
        FOOD = "food", "Food"
        TRANSPORT = "transport", "Transport"
        SHOPPING = "shopping", "Shopping"
        MISCELLANEOUS = "miscellaneous", "Miscellaneous"

    itinerary = models.ForeignKey(Itinerary, on_delete=models.CASCADE, related_name="expenses")
    paid_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="expenses",
    )
    category = models.CharField(max_length=20, choices=CategoryChoices.choices)
    description = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    date = models.DateField()
    receipt = models.ImageField(
        upload_to="receipts/", null=True, blank=True, validators=[validate_file_size, validate_image_type],
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "-id"]
        indexes = [models.Index(fields=["itinerary", "category"]), models.Index(fields=["date"])]

    def __str__(self):
        return f"{self.description} - ${self.amount}"
