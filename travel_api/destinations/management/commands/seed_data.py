"""Load demo destinations, accommodations, activities and a demo user."""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from bookings.models import Accommodation, Activity
from destinations.models import Destination

DESTINATIONS = [
    ("Paris", "France", "city", "temperate", 220, "Spring and autumn"),
    ("Bali", "Indonesia", "beach", "tropical", 70, "April to October"),
    ("Cape Town", "South Africa", "adventure", "temperate", 90, "November to March"),
    ("Kyoto", "Japan", "cultural", "temperate", 150, "March-May, Oct-Nov"),
    ("Zermatt", "Switzerland", "mountain", "continental", 380, "December to March"),
]


class Command(BaseCommand):
    help = "Seed the database with demo data (idempotent)."

    def handle(self, *args, **options):
        for name, country, category, climate, cost, best in DESTINATIONS:
            dest, _ = Destination.objects.get_or_create(name=name, defaults=dict(
                country=country, category=category, climate=climate, avg_daily_cost=cost,
                best_time_to_visit=best, description=f"{name} is a wonderful {category} destination."))
            Accommodation.objects.get_or_create(name=f"{name} Grand Hotel", destination=dest, defaults=dict(
                accommodation_type="hotel", description="Comfortable central hotel", price_per_night=cost,
                max_guests=4, address=f"1 Main Street, {name}"))
            Activity.objects.get_or_create(name=f"{name} City Tour", destination=dest, defaults=dict(
                category="tour", description="Guided highlights tour", duration_hours=3, price=40, max_participants=15))
        User = get_user_model()
        if not User.objects.filter(username="demo").exists():
            User.objects.create_user("demo", "demo@example.com", "DemoPass123!")
        self.stdout.write(self.style.SUCCESS("Seed data loaded (demo user: demo / DemoPass123!)"))
