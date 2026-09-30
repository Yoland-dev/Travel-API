"""Itinerary serializers (base + list/detail/write variants)."""
from django.contrib.auth import get_user_model
from rest_framework import serializers

from bookings.models import Activity
from core.validators import validate_document_type, validate_file_size
from destinations.serializers import DestinationListSerializer

from .models import ActivityLog, Collaboration, DailyPlan, Itinerary, ItineraryDocument
from .utils import log_activity

User = get_user_model()


class CollaborationSerializer(serializers.ModelSerializer):
    """Collaboration through-model with the user's public details."""

    username = serializers.CharField(source="user.username", read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)

    class Meta:
        model = Collaboration
        fields = ["id", "user", "username", "email", "role", "invited_at"]
        read_only_fields = ["id", "user", "invited_at"]


class DailyPlanSerializer(serializers.ModelSerializer):
    """A single day in an itinerary."""

    activities = serializers.PrimaryKeyRelatedField(queryset=Activity.objects.all(), many=True, required=False)
    activities_count = serializers.SerializerMethodField(help_text="Number of activities planned that day.")

    class Meta:
        model = DailyPlan
        fields = ["id", "itinerary", "day_number", "date", "title", "notes", "activities", "activities_count",
                  "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_activities_count(self, obj):
        return obj.activities.count()

    def validate(self, attrs):
        itinerary = attrs.get("itinerary") or (self.instance.itinerary if self.instance else None)
        date = attrs.get("date") or (self.instance.date if self.instance else None)
        if itinerary and date and not (itinerary.start_date <= date <= itinerary.end_date):
            raise serializers.ValidationError({"date": "Date must fall within the itinerary dates."})
        wrong = [a.name for a in attrs.get("activities", []) if itinerary and a.destination_id != itinerary.destination_id]
        if wrong:
            raise serializers.ValidationError({"activities": f"Not at the trip destination: {', '.join(wrong)}"})
        return attrs

    def validate_itinerary(self, value):
        if self.instance and value.pk != self.instance.itinerary_id:
            raise serializers.ValidationError("A daily plan cannot be moved to another itinerary.")
        return value


class BaseItinerarySerializer(serializers.ModelSerializer):
    """Shared computed fields and date validation for all itinerary serializers."""

    duration_days = serializers.ReadOnlyField(help_text="Inclusive number of days.")
    budget_remaining = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True,
                                                help_text="Budget minus actual spending.")
    my_role = serializers.SerializerMethodField(help_text="Your role: owner, admin, editor, viewer.")

    class Meta:
        model = Itinerary
        fields = ["id", "title", "start_date", "end_date", "duration_days", "budget", "budget_remaining",
                  "status", "is_public", "my_role"]
        read_only_fields = ["id", "owner", "status", "created_at", "updated_at"]

    def get_my_role(self, obj):
        request = self.context.get("request")
        return obj.get_user_role(request.user) if request else None

    def validate(self, data):
        start = data.get("start_date") or (self.instance.start_date if self.instance else None)
        end = data.get("end_date") or (self.instance.end_date if self.instance else None)
        if start and end and end < start:
            raise serializers.ValidationError({"end_date": "End date must be after start date"})
        return data


class ItineraryListSerializer(BaseItinerarySerializer):
    """Lightweight list serializer."""

    destination_name = serializers.CharField(source="destination.name", read_only=True)
    owner_username = serializers.CharField(source="owner.username", read_only=True)

    class Meta(BaseItinerarySerializer.Meta):
        fields = BaseItinerarySerializer.Meta.fields + ["destination", "destination_name", "owner", "owner_username"]


class ItineraryDetailSerializer(BaseItinerarySerializer):
    """Detailed serializer with nested objects."""

    destination = DestinationListSerializer(read_only=True)
    daily_plans = DailyPlanSerializer(many=True, read_only=True)
    collaborations = CollaborationSerializer(many=True, read_only=True)
    bookings_count = serializers.SerializerMethodField(help_text="Number of bookings on this trip.")
    owner_username = serializers.CharField(source="owner.username", read_only=True)

    class Meta(BaseItinerarySerializer.Meta):
        fields = BaseItinerarySerializer.Meta.fields + [
            "description", "destination", "owner", "owner_username", "actual_spent", "daily_plans",
            "collaborations", "bookings_count", "created_at", "updated_at",
        ]

    def get_bookings_count(self, obj):
        return obj.bookings.count()


class ItinerarySerializer(BaseItinerarySerializer):
    """Create/update serializer. Status changes go through the set_status action."""

    class Meta(BaseItinerarySerializer.Meta):
        fields = BaseItinerarySerializer.Meta.fields + [
            "description", "destination", "owner", "actual_spent", "created_at", "updated_at",
        ]
        read_only_fields = BaseItinerarySerializer.Meta.read_only_fields + ["actual_spent"]

    def validate_budget(self, value):
        if value <= 0:
            raise serializers.ValidationError("Budget must be greater than zero")
        return value

    def validate_destination(self, value):
        if not value.is_active:
            raise serializers.ValidationError("This destination is no longer available.")
        return value

    def create(self, validated_data):
        """Create the trip (a Budget row is added by a signal) and write an audit entry."""
        itinerary = super().create(validated_data)
        log_activity(itinerary.owner, ActivityLog.ActionChoices.CREATED, itinerary, f"Created trip '{itinerary.title}'")
        return itinerary

    def update(self, instance, validated_data):
        """Update the trip and record which fields changed."""
        changed = [f for f, v in validated_data.items() if getattr(instance, f) != v]
        instance = super().update(instance, validated_data)
        if changed:
            user = self.context["request"].user
            log_activity(user, ActivityLog.ActionChoices.UPDATED, instance, f"Updated {', '.join(changed)}")
        return instance


class SetStatusSerializer(serializers.Serializer):
    """Move a trip through planning -> booked -> in_progress -> completed."""

    status = serializers.ChoiceField(choices=Itinerary.STATUS_CHOICES)

    def validate_status(self, value):
        itinerary = self.context["itinerary"]
        if not itinerary.can_transition_to(value):
            raise serializers.ValidationError(f"Cannot move a trip from '{itinerary.status}' to '{value}'.")
        return value


class ShareItinerarySerializer(serializers.Serializer):
    """Add a collaborator by email with a role."""

    email = serializers.EmailField(help_text="Email of an existing user.")
    role = serializers.ChoiceField(choices=Collaboration.RoleChoices.choices, default="viewer")

    def validate_email(self, value):
        user = User.objects.filter(email__iexact=value).first()
        if user is None:
            raise serializers.ValidationError("No user with this email.")
        return user  # resolved to the user object

    def validate(self, attrs):
        itinerary = self.context["itinerary"]
        user = attrs["email"]
        if itinerary.owner_id == user.id:
            raise serializers.ValidationError({"email": "The owner already has full access."})
        if self.context.get("reject_existing", True) and itinerary.collaborations.filter(user=user).exists():
            raise serializers.ValidationError({"email": "This user is already a collaborator."})
        return attrs

    def create(self, validated_data):
        return self.context["itinerary"].add_collaborator(validated_data["email"], validated_data["role"])


class CollaboratorRoleSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=Collaboration.RoleChoices.choices)


class ItineraryDocumentSerializer(serializers.ModelSerializer):
    """Upload an itinerary PDF or photo."""

    file = serializers.FileField(validators=[validate_file_size, validate_document_type],
                                 help_text="PDF, JPG or PNG up to 5 MB.")
    uploaded_by_username = serializers.CharField(source="uploaded_by.username", read_only=True)

    class Meta:
        model = ItineraryDocument
        fields = ["id", "itinerary", "title", "file", "file_type", "file_size", "uploaded_by_username", "created_at"]
        read_only_fields = ["id", "itinerary", "file_type", "file_size", "created_at"]


class ActivityLogSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True, default=None)
    action_display = serializers.CharField(source="get_action_display", read_only=True)

    class Meta:
        model = ActivityLog
        fields = ["id", "user", "username", "itinerary", "action", "action_display", "description", "created_at"]
        read_only_fields = fields
