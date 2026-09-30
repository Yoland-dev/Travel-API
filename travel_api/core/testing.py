"""Factories and a base test case shared by every app's tests."""
import shutil
import tempfile
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from PIL import Image
from rest_framework.test import APIClient, APITestCase

from bookings.models import Accommodation, Activity
from destinations.models import Destination
from itineraries.models import Itinerary

User = get_user_model()
PASSWORD = "StrongPass123!"
TODAY = date.today()


def make_user(username="user", **kwargs):
    kwargs.setdefault("email", f"{username}@example.com")
    return User.objects.create_user(username=username, password=PASSWORD, **kwargs)


def make_destination(name="Paris", country="France", **kwargs):
    defaults = dict(description="City of light", category="city", climate="temperate",
                    avg_daily_cost=Decimal("150.00"), best_time_to_visit="Spring")
    defaults.update(kwargs)
    return Destination.objects.create(name=name, country=country, **defaults)


def make_itinerary(owner, destination, **kwargs):
    start = kwargs.pop("start_date", TODAY + timedelta(days=30))
    defaults = dict(title="Paris Trip", start_date=start, end_date=start + timedelta(days=6), budget=Decimal("2000"))
    defaults.update(kwargs)
    return Itinerary.objects.create(owner=owner, destination=destination, **defaults)


def make_accommodation(destination, **kwargs):
    defaults = dict(name="Hotel Lumiere", accommodation_type="hotel", description="Nice", max_guests=4,
                    price_per_night=Decimal("100.00"), address="1 Rue de Paris")
    defaults.update(kwargs)
    return Accommodation.objects.create(destination=destination, **defaults)


def make_activity(destination, **kwargs):
    defaults = dict(name="Eiffel Tour", category="tour", description="Go up", duration_hours=Decimal("2.5"),
                    price=Decimal("50.00"), max_participants=10)
    defaults.update(kwargs)
    return Activity.objects.create(destination=destination, **defaults)


def png_file(name="photo.png"):
    buf = BytesIO()
    Image.new("RGB", (10, 10), "red").save(buf, format="PNG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/png")


def pdf_file(name="plan.pdf", size=None):
    content = b"%PDF-1.4 test pdf"
    if size:
        content += b"0" * size
    return SimpleUploadedFile(name, content, content_type="application/pdf")


class BaseAPITest(APITestCase):
    """Creates an owner, another user, a destination and a trip; isolates uploaded media."""

    def setUp(self):
        self._media = tempfile.mkdtemp()
        self._override = override_settings(MEDIA_ROOT=self._media)
        self._override.enable()
        self.owner = make_user("owner")
        self.other = make_user("other")
        self.destination = make_destination()
        self.itinerary = make_itinerary(self.owner, self.destination)
        self.client = APIClient()
        self.client.force_authenticate(user=self.owner)

    def tearDown(self):
        self._override.disable()
        shutil.rmtree(self._media, ignore_errors=True)

    def login_as(self, user):
        self.client.force_authenticate(user=user)
