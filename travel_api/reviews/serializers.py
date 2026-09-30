"""Review serializers."""
from django.utils import timezone
from rest_framework import serializers

from .models import Review


class ReviewSerializer(serializers.ModelSerializer):
    """Rate one destination, accommodation or activity."""

    username = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = Review
        fields = ["id", "user", "username", "destination", "accommodation", "activity", "rating", "title",
                  "content", "visit_date", "images", "helpful_count", "created_at", "updated_at"]
        read_only_fields = ["id", "user", "helpful_count", "created_at", "updated_at"]

    def validate_rating(self, value):
        if not 1 <= value <= 5:
            raise serializers.ValidationError("Rating must be between 1 and 5.")
        return value

    def validate_visit_date(self, value):
        if value > timezone.now().date():
            raise serializers.ValidationError("Visit date cannot be in the future.")
        return value

    def validate(self, attrs):
        src = self.instance
        targets = {k: attrs.get(k, getattr(src, k, None) if src else None)
                   for k in Review.TARGETS}
        if src:  # the reviewed item is fixed once created
            for name in Review.TARGETS:
                if name in attrs and attrs[name] != getattr(src, name):
                    raise serializers.ValidationError("The reviewed item cannot be changed.")
        if sum(1 for v in targets.values() if v) != 1:
            raise serializers.ValidationError("Review must be for exactly one item")
        user = self.context["request"].user
        target_name, target = next((k, v) for k, v in targets.items() if v)
        # The DB constraint is conditional (one nullable FK per row), so DRF cannot check it for us.
        duplicate = Review.objects.filter(user=user, **{target_name: target})
        if src:
            duplicate = duplicate.exclude(pk=src.pk)
        if duplicate.exists():
            raise serializers.ValidationError("You have already reviewed this item.")
        return attrs

    def create(self, validated_data):
        return Review.objects.create(user=self.context["request"].user, **validated_data)

    def update(self, instance, validated_data):
        """Editable: rating, text, visit date and images only."""
        for field in ("rating", "title", "content", "visit_date", "images"):
            if field in validated_data:
                setattr(instance, field, validated_data[field])
        instance.save()
        return instance

    def to_representation(self, instance):
        data = super().to_representation(instance)
        target = instance.target
        data["target_type"] = instance.target_type
        data["target_name"] = getattr(target, "name", None)
        return data
