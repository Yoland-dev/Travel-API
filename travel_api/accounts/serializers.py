"""Serializers for registration, authentication, profile and saved searches."""
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from rest_framework import serializers

from .models import SavedSearch

User = get_user_model()

PREFERENCE_KEYS = {"categories", "climates", "max_daily_budget"}


class UserRegistrationSerializer(serializers.ModelSerializer):
    """Create an account; passwords are write-only."""

    password = serializers.CharField(write_only=True, min_length=8, style={"input_type": "password"},
                                     help_text="At least 8 characters; validated by Django's password rules.")
    password_confirm = serializers.CharField(write_only=True, help_text="Must match password.")

    class Meta:
        model = User
        fields = ["id", "username", "email", "password", "password_confirm", "first_name", "last_name", "phone"]
        read_only_fields = ["id"]

    def validate_email(self, value):
        value = value.lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value

    def validate(self, attrs):
        if attrs["password"] != attrs["password_confirm"]:
            raise serializers.ValidationError({"password_confirm": "Passwords do not match."})
        candidate = User(username=attrs.get("username", ""), email=attrs.get("email", ""))
        validate_password(attrs["password"], candidate)
        return attrs

    def create(self, validated_data):
        validated_data.pop("password_confirm")
        return User.objects.create_user(**validated_data)


class UserSerializer(serializers.ModelSerializer):
    """Profile representation and update."""

    full_name = serializers.SerializerMethodField(help_text="First + last name, or the username.")
    owned_trips_count = serializers.SerializerMethodField(help_text="Number of trips this user owns.")

    class Meta:
        model = User
        fields = [
            "id", "username", "email", "first_name", "last_name", "full_name", "phone", "date_of_birth",
            "bio", "profile_picture", "travel_preferences", "favorite_destinations", "owned_trips_count",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "username", "created_at", "updated_at"]

    def get_full_name(self, obj):
        return obj.full_name

    def get_owned_trips_count(self, obj):
        return obj.owned_itineraries.count()

    def validate_email(self, value):
        value = value.lower()
        qs = User.objects.filter(email__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value

    def validate_travel_preferences(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("Preferences must be a JSON object.")
        unknown = set(value) - PREFERENCE_KEYS
        if unknown:
            raise serializers.ValidationError(f"Unknown preference keys: {', '.join(sorted(unknown))}")
        for key in ("categories", "climates"):
            if key in value and not isinstance(value[key], list):
                raise serializers.ValidationError(f"'{key}' must be a list.")
        return value


class LoginSerializer(serializers.Serializer):
    """Credentials (username or email) for token login."""

    username = serializers.CharField(help_text="Username or email address.")
    password = serializers.CharField(write_only=True, style={"input_type": "password"})


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=8)

    def validate_old_password(self, value):
        if not self.context["request"].user.check_password(value):
            raise serializers.ValidationError("Old password is incorrect.")
        return value

    def validate_new_password(self, value):
        validate_password(value, self.context["request"].user)
        return value


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    """Validates uid + token and exposes the user as attrs['user']."""

    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(write_only=True, min_length=8)

    def validate(self, attrs):
        try:
            user = User.objects.get(pk=force_str(urlsafe_base64_decode(attrs["uid"])))
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            raise serializers.ValidationError({"uid": "Invalid reset link."})
        if not default_token_generator.check_token(user, attrs["token"]):
            raise serializers.ValidationError({"token": "Invalid or expired token."})
        validate_password(attrs["new_password"], user)
        attrs["user"] = user
        return attrs


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField(help_text="The refresh token to blacklist.")


class SavedSearchSerializer(serializers.ModelSerializer):
    class Meta:
        model = SavedSearch
        fields = ["id", "name", "search_type", "query_params", "created_at"]
        read_only_fields = ["id", "created_at"]

    def validate_query_params(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("query_params must be a JSON object.")
        return value
