"""Reviews and ratings for destinations, accommodations and activities."""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

from bookings.models import Accommodation, Activity
from destinations.models import Destination


class Review(models.Model):
    """A rating and comment on exactly one target."""

    TARGETS = ("destination", "accommodation", "activity")

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reviews")
    destination = models.ForeignKey(Destination, on_delete=models.CASCADE, related_name="reviews", null=True, blank=True)
    accommodation = models.ForeignKey(Accommodation, on_delete=models.CASCADE, related_name="reviews", null=True, blank=True)
    activity = models.ForeignKey(Activity, on_delete=models.CASCADE, related_name="reviews", null=True, blank=True)
    rating = models.PositiveIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    title = models.CharField(max_length=200)
    content = models.TextField()
    visit_date = models.DateField()
    images = models.JSONField(default=list, blank=True)
    helpful_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["destination", "rating"]),
            models.Index(fields=["user"]),
        ]
        constraints = [
            models.UniqueConstraint(fields=["user", "destination"], condition=Q(destination__isnull=False),
                                    name="unique_user_destination_review"),
            models.UniqueConstraint(fields=["user", "accommodation"], condition=Q(accommodation__isnull=False),
                                    name="unique_user_accommodation_review"),
            models.UniqueConstraint(fields=["user", "activity"], condition=Q(activity__isnull=False),
                                    name="unique_user_activity_review"),
        ]

    def __str__(self):
        return f"{self.title} by {self.user.username}"

    def clean(self):
        targets = [self.destination_id, self.accommodation_id, self.activity_id]
        if sum(1 for t in targets if t) != 1:
            raise ValidationError("Review must be for exactly one item")
        if self.visit_date and self.visit_date > timezone.now().date():
            raise ValidationError("Visit date cannot be in the future.")

    @property
    def target(self):
        return self.destination or self.accommodation or self.activity

    @property
    def target_type(self):
        for name in self.TARGETS:
            if getattr(self, f"{name}_id"):
                return name
        return None
