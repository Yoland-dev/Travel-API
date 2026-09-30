"""Accounts: custom user and saved searches."""
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone

from core.validators import validate_file_size, validate_image_type


class User(AbstractUser):
    """Custom user model with travel-specific profile fields."""

    email = models.EmailField(unique=True)
    phone = models.CharField(
        max_length=20, blank=True,
        validators=[RegexValidator(r"^\+?[0-9 \-]{6,20}$", "Enter a valid phone number.")],
    )
    date_of_birth = models.DateField(null=True, blank=True)
    bio = models.TextField(max_length=500, blank=True)
    profile_picture = models.ImageField(
        upload_to="profiles/", null=True, blank=True,
        validators=[validate_file_size, validate_image_type],
    )
    travel_preferences = models.JSONField(
        default=dict, blank=True,
        help_text="e.g. {'categories': ['beach'], 'climates': ['tropical'], 'max_daily_budget': 200}",
    )
    favorite_destinations = models.ManyToManyField(
        "destinations.Destination", blank=True, related_name="favorited_by",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "User"
        verbose_name_plural = "Users"

    def __str__(self):
        return self.username

    def clean(self):
        super().clean()
        if self.date_of_birth and self.date_of_birth > timezone.now().date():
            raise ValidationError({"date_of_birth": "Date of birth cannot be in the future."})

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip() or self.username


class SavedSearch(models.Model):
    """A search a user chose to keep (trip or destination search preferences)."""

    class SearchType(models.TextChoices):
        TRIP = "trip", "Trip"
        DESTINATION = "destination", "Destination"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="saved_searches")
    name = models.CharField(max_length=100)
    search_type = models.CharField(max_length=20, choices=SearchType.choices)
    query_params = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "Saved searches"
        indexes = [models.Index(fields=["user", "search_type"])]

    def __str__(self):
        return f"{self.name} ({self.search_type})"
