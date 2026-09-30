"""Booking serializers."""
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from itineraries.models import ActivityLog
from itineraries.utils import log_activity

from .models import Accommodation, Activity, Booking


class AccommodationSerializer(serializers.ModelSerializer):
    destination_name = serializers.CharField(source="destination.name", read_only=True)
    type_display = serializers.CharField(source="get_accommodation_type_display", read_only=True)

    class Meta:
        model = Accommodation
        fields = ["id", "name", "destination", "destination_name", "accommodation_type", "type_display",
                  "description", "price_per_night", "max_guests", "amenities", "address", "contact_email",
                  "contact_phone", "image", "is_available"]
        read_only_fields = ["id"]


class ActivitySerializer(serializers.ModelSerializer):
    destination_name = serializers.CharField(source="destination.name", read_only=True)

    class Meta:
        model = Activity
        fields = ["id", "name", "destination", "destination_name", "category", "description", "duration_hours",
                  "price", "max_participants", "requirements", "image", "is_available"]
        read_only_fields = ["id"]


class PopularActivitySerializer(ActivitySerializer):
    """Activity plus its number of bookings (annotated by the view)."""

    booking_count = serializers.IntegerField(read_only=True, help_text="How many times it was booked.")

    class Meta(ActivitySerializer.Meta):
        fields = ActivitySerializer.Meta.fields + ["booking_count"]


class BookingSerializer(serializers.ModelSerializer):
    """Create/update bookings. Price, status and code are computed by the server."""

    item_name = serializers.SerializerMethodField(help_text="Name of the booked accommodation or activity.")
    nights = serializers.SerializerMethodField(help_text="Nights for accommodation bookings.")

    class Meta:
        model = Booking
        fields = ["id", "user", "itinerary", "accommodation", "activity", "item_name", "booking_date", "check_in",
                  "check_out", "nights", "guests_count", "price", "status", "confirmation_code", "notes",
                  "created_at", "updated_at"]
        read_only_fields = ["id", "user", "price", "status", "confirmation_code", "created_at", "updated_at"]
        extra_kwargs = {"booking_date": {"required": False}}

    def get_item_name(self, obj):
        target = obj.accommodation or obj.activity
        return target.name if target else None

    def get_nights(self, obj):
        return obj.nights

    def validate_itinerary(self, value):
        user = self.context["request"].user
        if not value.can_edit(user):
            raise serializers.ValidationError("You cannot book for this itinerary.")
        return value

    def validate(self, attrs):
        """Delegate the business rules to Booking.clean() using an unsaved probe instance."""
        src = self.instance
        keys = ("itinerary", "accommodation", "activity", "check_in", "check_out", "guests_count", "booking_date")
        data = {k: attrs.get(k, getattr(src, k, None) if src else None) for k in keys}
        if data["accommodation"] and not data["booking_date"]:
            data["booking_date"] = attrs["booking_date"] = data["check_in"]
        if data["guests_count"] is None:
            data["guests_count"] = 1
        if not data["booking_date"] and not data["accommodation"]:
            raise serializers.ValidationError({"booking_date": "This field is required for activities."})
        try:
            Booking(**data).clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages)
        return attrs

    def create(self, validated_data):
        """Attach the user, compute the price and write an audit entry."""
        booking = Booking(user=self.context["request"].user, **validated_data)
        booking.price = booking.calculate_price()
        booking.save()
        log_activity(booking.user, ActivityLog.ActionChoices.BOOKING, booking.itinerary,
                     f"Booked {self.get_item_name(booking)} (${booking.price})")
        return booking

    def update(self, instance, validated_data):
        """Only pending/confirmed bookings can change; the price is recomputed."""
        if instance.status in (Booking.StatusChoices.CANCELLED, Booking.StatusChoices.COMPLETED):
            raise serializers.ValidationError(f"A {instance.status} booking cannot be modified.")
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.price = instance.calculate_price()
        instance.save()
        return instance


class BookingDetailSerializer(BookingSerializer):
    """Adds nested accommodation/activity and a refund estimate."""

    accommodation = AccommodationSerializer(read_only=True)
    activity = ActivitySerializer(read_only=True)
    refund_estimate = serializers.SerializerMethodField(help_text="Refund if cancelled today.")
    itinerary_title = serializers.CharField(source="itinerary.title", read_only=True)

    class Meta(BookingSerializer.Meta):
        fields = BookingSerializer.Meta.fields + ["refund_estimate", "itinerary_title"]

    def get_refund_estimate(self, obj):
        if obj.status in (Booking.StatusChoices.CANCELLED, Booking.StatusChoices.COMPLETED):
            return "0.00"
        return str(obj.calculate_refund())


class BulkBookingItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    action = serializers.ChoiceField(choices=["confirm", "cancel"])
    notes = serializers.CharField(required=False, allow_blank=True)


class BulkBookingUpdateSerializer(serializers.Serializer):
    updates = BulkBookingItemSerializer(many=True, allow_empty=False)
    all_or_nothing = serializers.BooleanField(default=False, help_text="Roll everything back if any item fails.")

    def validate_updates(self, value):
        if len(value) > 50:
            raise serializers.ValidationError("At most 50 updates per request.")
        return value
