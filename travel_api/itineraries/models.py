"""Itineraries: trips, day plans, collaboration, documents and audit log."""
import os
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Sum

from core.validators import validate_document_type, validate_file_size
from destinations.models import Destination


class Itinerary(models.Model):
    """A user's trip plan."""

    class StatusChoices(models.TextChoices):
        PLANNING = "planning", "Planning"
        BOOKED = "booked", "Booked"
        IN_PROGRESS = "in_progress", "In Progress"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    STATUS_CHOICES = StatusChoices.choices
    # Allowed trip status transitions (trip status tracking).
    ALLOWED_TRANSITIONS = {
        "planning": ["booked", "cancelled"],
        "booked": ["planning", "in_progress", "cancelled"],
        "in_progress": ["completed", "cancelled"],
        "completed": [],
        "cancelled": ["planning"],
    }

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    destination = models.ForeignKey(Destination, on_delete=models.PROTECT, related_name="itineraries")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="owned_itineraries")
    collaborators = models.ManyToManyField(
        settings.AUTH_USER_MODEL, through="Collaboration",
        related_name="shared_itineraries", blank=True,
    )
    start_date = models.DateField()
    end_date = models.DateField()
    budget = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    actual_spent = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)],
    )
    status = models.CharField(max_length=20, choices=StatusChoices.choices, default=StatusChoices.PLANNING)
    is_public = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-start_date"]
        verbose_name_plural = "Itineraries"
        indexes = [
            models.Index(fields=["owner", "status"]),
            models.Index(fields=["start_date", "end_date"]),
        ]

    def __str__(self):
        return f"{self.title} - {self.destination.name}"

    def clean(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError("End date must be after start date")

    @property
    def duration_days(self):
        return (self.end_date - self.start_date).days + 1

    @property
    def budget_remaining(self):
        return self.budget - self.actual_spent

    @property
    def is_over_budget(self):
        return self.actual_spent > self.budget

    def get_user_role(self, user):
        """Return 'owner', a collaboration role, or None. Uses prefetched collaborations."""
        if not user or not user.is_authenticated:
            return None
        if self.owner_id == user.id:
            return "owner"
        # .all() reuses prefetched rows, so role checks cost no extra queries in list views.
        for collab in self.collaborations.all():
            if collab.user_id == user.id:
                return collab.role
        return None

    def can_view(self, user):
        return self.get_user_role(user) is not None or self.is_public

    def can_edit(self, user):
        """Owner and collaborators with editor/admin role may edit."""
        return self.get_user_role(user) in ("owner", "editor", "admin")

    def add_collaborator(self, user, role="viewer"):
        """Add (or update) a collaborator through the Collaboration model."""
        collab, created = Collaboration.objects.update_or_create(
            itinerary=self, user=user, defaults={"role": role},
        )
        return collab

    def can_transition_to(self, new_status):
        return new_status in self.ALLOWED_TRANSITIONS.get(self.status, [])

    def recalculate_spent(self):
        """Refresh actual_spent from the sum of expenses."""
        total = self.expenses.aggregate(total=Sum("amount"))["total"] or Decimal("0")
        Itinerary.objects.filter(pk=self.pk).update(actual_spent=total)
        self.actual_spent = total
        return total


class Collaboration(models.Model):
    """Through model for itinerary sharing (role-based)."""

    class RoleChoices(models.TextChoices):
        VIEWER = "viewer", "Viewer"
        EDITOR = "editor", "Editor"
        ADMIN = "admin", "Admin"

    itinerary = models.ForeignKey(Itinerary, on_delete=models.CASCADE, related_name="collaborations")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="collaborations")
    role = models.CharField(max_length=10, choices=RoleChoices.choices, default=RoleChoices.VIEWER)
    invited_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ["itinerary", "user"]
        ordering = ["invited_at"]

    def __str__(self):
        return f"{self.user.username} - {self.itinerary.title} ({self.role})"

    def clean(self):
        if self.itinerary_id and self.user_id and self.itinerary.owner_id == self.user_id:
            raise ValidationError("The trip owner cannot be added as a collaborator.")


class DailyPlan(models.Model):
    """Day-by-day plan within an itinerary."""

    itinerary = models.ForeignKey(Itinerary, on_delete=models.CASCADE, related_name="daily_plans")
    day_number = models.PositiveIntegerField()
    date = models.DateField()
    title = models.CharField(max_length=200)
    notes = models.TextField(blank=True)
    activities = models.ManyToManyField("bookings.Activity", related_name="daily_plans", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["day_number"]
        unique_together = ["itinerary", "day_number"]

    def __str__(self):
        return f"Day {self.day_number}: {self.title}"

    def clean(self):
        it = self.itinerary if self.itinerary_id else None
        if it and self.date and not (it.start_date <= self.date <= it.end_date):
            raise ValidationError("Date must fall within the itinerary dates.")


class ItineraryDocument(models.Model):
    """Uploaded itinerary PDF or photo."""

    itinerary = models.ForeignKey(Itinerary, on_delete=models.CASCADE, related_name="documents")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="uploaded_documents",
    )
    title = models.CharField(max_length=200)
    file = models.FileField(upload_to="itinerary_documents/", validators=[validate_file_size, validate_document_type])
    file_type = models.CharField(max_length=10, blank=True)
    file_size = models.PositiveIntegerField(default=0, help_text="Size in bytes")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["itinerary"])]

    def __str__(self):
        return f"{self.title} ({self.file_type})"

    def save(self, *args, **kwargs):
        if self.file:
            self.file_type = os.path.splitext(self.file.name)[1].lstrip(".").lower()
            self.file_size = self.file.size
        super().save(*args, **kwargs)


class ActivityLog(models.Model):
    """Audit trail entry."""

    class ActionChoices(models.TextChoices):
        CREATED = "created", "Created"
        UPDATED = "updated", "Updated"
        DELETED = "deleted", "Deleted"
        STATUS = "status_changed", "Status changed"
        SHARED = "shared", "Shared"
        UNSHARED = "unshared", "Unshared"
        BOOKING = "booking", "Booking"
        EXPENSE = "expense", "Expense"
        DOCUMENT = "document", "Document"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="activity_logs",
    )
    itinerary = models.ForeignKey(
        Itinerary, on_delete=models.SET_NULL, null=True, blank=True, related_name="activity_logs",
    )
    action = models.CharField(max_length=20, choices=ActionChoices.choices)
    description = models.CharField(max_length=300)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["itinerary", "created_at"]), models.Index(fields=["user"])]

    def __str__(self):
        return f"{self.action}: {self.description}"
