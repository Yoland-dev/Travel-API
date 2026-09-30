"""Bookings: accommodations, activities and user bookings."""
import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from core.validators import validate_file_size, validate_image_type
from destinations.models import Destination
from itineraries.models import Itinerary


class Accommodation(models.Model):
    """Hotels, hostels, vacation rentals."""

    class TypeChoices(models.TextChoices):
        HOTEL = "hotel", "Hotel"
        HOSTEL = "hostel", "Hostel"
        RENTAL = "rental", "Vacation Rental"
        RESORT = "resort", "Resort"
        BNB = "bnb", "B&B"

    name = models.CharField(max_length=200)
    destination = models.ForeignKey(Destination, on_delete=models.CASCADE, related_name="accommodations")
    accommodation_type = models.CharField(max_length=10, choices=TypeChoices.choices)
    description = models.TextField()
    price_per_night = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    max_guests = models.PositiveIntegerField()
    amenities = models.JSONField(default=list, blank=True)
    address = models.CharField(max_length=300)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=20, blank=True)
    image = models.ImageField(
        upload_to="accommodations/", null=True, blank=True,
        validators=[validate_file_size, validate_image_type],
    )
    is_available = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["destination", "accommodation_type"]),
            models.Index(fields=["price_per_night"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.get_accommodation_type_display()})"


class Activity(models.Model):
    """Tours, attractions, experiences."""

    class CategoryChoices(models.TextChoices):
        TOUR = "tour", "Tour"
        ATTRACTION = "attraction", "Attraction"
        DINING = "dining", "Dining"
        SHOPPING = "shopping", "Shopping"
        ENTERTAINMENT = "entertainment", "Entertainment"
        OUTDOOR = "outdoor", "Outdoor"

    name = models.CharField(max_length=200)
    destination = models.ForeignKey(Destination, on_delete=models.CASCADE, related_name="activities")
    category = models.CharField(max_length=20, choices=CategoryChoices.choices)
    description = models.TextField()
    duration_hours = models.DecimalField(max_digits=4, decimal_places=1, validators=[MinValueValidator(0)])
    price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    max_participants = models.PositiveIntegerField(null=True, blank=True)
    requirements = models.TextField(blank=True)
    image = models.ImageField(
        upload_to="activities/", null=True, blank=True,
        validators=[validate_file_size, validate_image_type],
    )
    is_available = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "Activities"
        indexes = [models.Index(fields=["destination", "category"])]

    def __str__(self):
        return f"{self.name} - {self.destination.name}"


class Booking(models.Model):
    """A user's booking for either an accommodation or an activity."""

    class StatusChoices(models.TextChoices):
        PENDING = "pending", "Pending"
        CONFIRMED = "confirmed", "Confirmed"
        CANCELLED = "cancelled", "Cancelled"
        COMPLETED = "completed", "Completed"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="bookings")
    itinerary = models.ForeignKey(Itinerary, on_delete=models.CASCADE, related_name="bookings")
    accommodation = models.ForeignKey(
        Accommodation, on_delete=models.SET_NULL, null=True, blank=True, related_name="bookings",
    )
    activity = models.ForeignKey(
        Activity, on_delete=models.SET_NULL, null=True, blank=True, related_name="bookings",
    )
    booking_date = models.DateField()
    check_in = models.DateField(null=True, blank=True)
    check_out = models.DateField(null=True, blank=True)
    guests_count = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=StatusChoices.choices, default=StatusChoices.PENDING)
    confirmation_code = models.CharField(max_length=50, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["itinerary"]),
            models.Index(fields=["booking_date"]),
        ]

    def __str__(self):
        if self.accommodation_id:
            return f"Booking: {self.accommodation.name}"
        if self.activity_id:
            return f"Booking: {self.activity.name}"
        return f"Booking #{self.pk}"

    def clean(self):
        """Business rules: exactly one target, valid dates, capacity, matching destination."""
        if not self.accommodation and not self.activity:
            raise ValidationError("Booking must have either accommodation or activity")
        if self.accommodation and self.activity:
            raise ValidationError("Booking cannot have both accommodation and activity")
        target = self.accommodation or self.activity
        if not target.is_available:
            raise ValidationError("This item is not available for booking.")
        if self.itinerary_id and target.destination_id != self.itinerary.destination_id:
            raise ValidationError("Booked item must belong to the itinerary's destination.")
        if self.accommodation:
            if not self.check_in or not self.check_out:
                raise ValidationError("check_in and check_out are required for accommodations.")
            if self.check_out <= self.check_in:
                raise ValidationError("check_out must be after check_in.")
            if self.guests_count > self.accommodation.max_guests:
                raise ValidationError(f"Maximum {self.accommodation.max_guests} guests allowed.")
        else:
            cap = self.activity.max_participants
            if cap and self.guests_count > cap:
                raise ValidationError(f"Maximum {cap} participants allowed.")

    @property
    def nights(self):
        if self.check_in and self.check_out:
            return (self.check_out - self.check_in).days
        return 0

    def calculate_price(self):
        """Accommodation: nights x nightly rate. Activity: price x participants."""
        if self.accommodation:
            return self.accommodation.price_per_night * self.nights
        if self.activity:
            return self.activity.price * self.guests_count
        return Decimal("0")

    def calculate_refund(self, today=None):
        """Refund policy: 100% if >=7 days ahead, 50% if >=2 days, otherwise 0."""
        today = today or timezone.now().date()
        start = self.check_in or self.booking_date
        days_ahead = (start - today).days
        if days_ahead >= 7:
            rate = Decimal("1.0")
        elif days_ahead >= 2:
            rate = Decimal("0.5")
        else:
            rate = Decimal("0")
        return (self.price * rate).quantize(Decimal("0.01"))

    def confirm(self):
        """Confirm a pending booking and issue a confirmation code."""
        if self.status != self.StatusChoices.PENDING:
            raise ValidationError("Only pending bookings can be confirmed.")
        self.status = self.StatusChoices.CONFIRMED
        self.confirmation_code = f"TRV-{uuid.uuid4().hex[:10].upper()}"
        self.save(update_fields=["status", "confirmation_code", "updated_at"])

    def cancel(self):
        """Cancel the booking; returns the refund amount."""
        if self.status in (self.StatusChoices.CANCELLED, self.StatusChoices.COMPLETED):
            raise ValidationError(f"A {self.status} booking cannot be cancelled.")
        refund = self.calculate_refund()
        self.status = self.StatusChoices.CANCELLED
        self.save(update_fields=["status", "updated_at"])
        return refund
