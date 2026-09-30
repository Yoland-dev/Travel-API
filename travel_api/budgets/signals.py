"""Keep budgets and itinerary totals in sync automatically."""
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from itineraries.models import Itinerary

from .models import Budget, Expense


@receiver(post_save, sender=Itinerary)
def create_budget_for_itinerary(sender, instance, created, raw=False, **kwargs):
    """Every new itinerary gets an (empty) Budget record."""
    if created and not raw:
        Budget.objects.get_or_create(itinerary=instance)


@receiver([post_save, post_delete], sender=Expense)
def refresh_itinerary_spent(sender, instance, **kwargs):
    """Recompute Itinerary.actual_spent whenever an expense changes."""
    itinerary = Itinerary.objects.filter(pk=instance.itinerary_id).first()
    if itinerary:
        itinerary.recalculate_spent()
