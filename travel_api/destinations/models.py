"""Destinations: browsable places to visit."""
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.text import slugify

from core.validators import validate_file_size, validate_image_type


class Destination(models.Model):
    """Tourist destination with details."""

    class ClimateChoices(models.TextChoices):
        TROPICAL = "tropical", "Tropical"
        DRY = "dry", "Dry"
        TEMPERATE = "temperate", "Temperate"
        CONTINENTAL = "continental", "Continental"
        POLAR = "polar", "Polar"

    class CategoryChoices(models.TextChoices):
        BEACH = "beach", "Beach"
        MOUNTAIN = "mountain", "Mountain"
        CITY = "city", "City"
        CULTURAL = "cultural", "Cultural"
        ADVENTURE = "adventure", "Adventure"
        RELAXATION = "relaxation", "Relaxation"

    name = models.CharField(max_length=200, unique=True)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    country = models.CharField(max_length=100)
    description = models.TextField()
    category = models.CharField(max_length=20, choices=CategoryChoices.choices)
    climate = models.CharField(max_length=20, choices=ClimateChoices.choices)
    best_time_to_visit = models.CharField(max_length=200, blank=True)
    avg_daily_cost = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(0)],
        help_text="Average daily spend per traveller (USD).",
    )
    image = models.ImageField(
        upload_to="destinations/", null=True, blank=True,
        validators=[validate_file_size, validate_image_type],
    )
    latitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
        validators=[MinValueValidator(-90), MaxValueValidator(90)],
    )
    longitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
        validators=[MinValueValidator(-180), MaxValueValidator(180)],
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["country", "category"]),
            models.Index(fields=["climate"]),
            models.Index(fields=["avg_daily_cost"]),
        ]

    def __str__(self):
        return f"{self.name}, {self.country}"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    @property
    def average_rating(self):
        """Mean destination rating; uses the queryset annotation when present (avoids N+1)."""
        annotated = getattr(self, "avg_rating", None)
        if hasattr(self, "avg_rating"):
            return round(float(annotated), 2) if annotated is not None else 0
        value = self.reviews.aggregate(avg=models.Avg("rating"))["avg"]
        return round(float(value), 2) if value else 0

    @property
    def review_count(self):
        if hasattr(self, "review_total"):
            return self.review_total
        return self.reviews.count()

    def budget_category(self):
        """Classify the destination by daily cost (budget / moderate / luxury)."""
        if self.avg_daily_cost < 100:
            return "budget"
        return "moderate" if self.avg_daily_cost < 250 else "luxury"
