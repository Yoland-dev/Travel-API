"""Destination serializers."""
from rest_framework import serializers

from core.validators import validate_file_size, validate_image_type

from .models import Destination


class DestinationListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for list views."""

    average_rating = serializers.ReadOnlyField(help_text="Mean review rating (0 when unreviewed).")
    review_count = serializers.SerializerMethodField(help_text="Number of reviews.")
    budget_category = serializers.SerializerMethodField(help_text="budget / moderate / luxury by daily cost.")

    class Meta:
        model = Destination
        fields = ["id", "name", "slug", "country", "category", "climate", "avg_daily_cost", "image",
                  "average_rating", "review_count", "budget_category"]
        read_only_fields = ["id", "slug"]

    def get_review_count(self, obj):
        return obj.review_count

    def get_budget_category(self, obj):
        return obj.budget_category()


class DestinationDetailSerializer(DestinationListSerializer):
    """Detailed serializer (extends the list serializer)."""

    total_itineraries = serializers.SerializerMethodField(help_text="Trips planned to this destination.")
    top_activities = serializers.SerializerMethodField(help_text="Up to 5 available activities.")

    class Meta(DestinationListSerializer.Meta):
        fields = DestinationListSerializer.Meta.fields + [
            "description", "best_time_to_visit", "latitude", "longitude", "is_active",
            "total_itineraries", "top_activities", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "slug", "created_at", "updated_at"]

    def get_total_itineraries(self, obj):
        return obj.itineraries.count()

    def get_top_activities(self, obj):
        from bookings.serializers import ActivitySerializer
        # 'activities' may be prefetched with a filtered queryset (see the view)
        return ActivitySerializer(list(obj.activities.all())[:5], many=True, context=self.context).data


class DestinationImageSerializer(serializers.ModelSerializer):
    """Upload/replace a destination photo (size and type validated)."""

    image = serializers.ImageField(validators=[validate_file_size, validate_image_type],
                                   help_text="JPG or PNG, max 5 MB.")

    class Meta:
        model = Destination
        fields = ["id", "image"]
        read_only_fields = ["id"]


class RecommendedDestinationSerializer(DestinationListSerializer):
    """List serializer plus recommendation score and reasons."""

    score = serializers.SerializerMethodField(help_text="Higher is a better match.")
    reasons = serializers.SerializerMethodField(help_text="Why this destination was suggested.")

    class Meta(DestinationListSerializer.Meta):
        fields = DestinationListSerializer.Meta.fields + ["score", "reasons"]

    def get_score(self, obj):
        return getattr(obj, "score", 0)

    def get_reasons(self, obj):
        return getattr(obj, "reasons", [])
