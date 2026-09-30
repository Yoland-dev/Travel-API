"""Authentication endpoints (function-based) and the profile view (class-based)."""
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import filters, generics, status, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from .models import SavedSearch
from .serializers import (
    SavedSearchSerializer,
    ChangePasswordSerializer, LoginSerializer, LogoutSerializer, PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer, UserRegistrationSerializer, UserSerializer,
)

User = get_user_model()


def _token_payload(user, request=None):
    """User data plus a fresh JWT pair."""
    refresh = RefreshToken.for_user(user)
    return {
        "user": UserSerializer(user, context={"request": request}).data,
        "tokens": {"refresh": str(refresh), "access": str(refresh.access_token)},
    }


@extend_schema(
    request=UserRegistrationSerializer, responses={201: UserSerializer},
    examples=[OpenApiExample("Register", value={
        "username": "amina", "email": "amina@example.com", "password": "StrongPass123!",
        "password_confirm": "StrongPass123!"}, request_only=True)],
)
@api_view(["POST"])
@permission_classes([AllowAny])
def register(request):
    """Register a new user and return JWT tokens.

    Example: POST /api/v1/accounts/register/ with username, email, password, password_confirm.
    """
    serializer = UserRegistrationSerializer(data=request.data)
    if serializer.is_valid():
        user = serializer.save()
        return Response(_token_payload(user, request), status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(request=LoginSerializer, responses={200: UserSerializer})
@api_view(["POST"])
@permission_classes([AllowAny])
def login(request):
    """Authenticate with username (or email) and password; returns JWT tokens."""
    serializer = LoginSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    identifier = serializer.validated_data["username"]
    if "@" in identifier:  # allow login by email
        match = User.objects.filter(email__iexact=identifier).first()
        identifier = match.username if match else identifier
    user = authenticate(username=identifier, password=serializer.validated_data["password"])
    if user is None:
        return Response({"error": "Invalid credentials"}, status=status.HTTP_401_UNAUTHORIZED)
    return Response(_token_payload(user, request))


@extend_schema(request=LogoutSerializer, responses={205: None})
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def logout(request):
    """Blacklist the supplied refresh token."""
    serializer = LogoutSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    try:
        RefreshToken(serializer.validated_data["refresh"]).blacklist()
    except TokenError:
        return Response({"error": "Invalid or expired token."}, status=status.HTTP_400_BAD_REQUEST)
    return Response(status=status.HTTP_205_RESET_CONTENT)


@extend_schema(request=ChangePasswordSerializer, responses={200: None})
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def change_password(request):
    """Change the current user's password (requires the old password)."""
    serializer = ChangePasswordSerializer(data=request.data, context={"request": request})
    serializer.is_valid(raise_exception=True)
    request.user.set_password(serializer.validated_data["new_password"])
    request.user.save(update_fields=["password"])
    return Response({"detail": "Password updated."})


@extend_schema(request=PasswordResetRequestSerializer, responses={200: None})
@api_view(["POST"])
@permission_classes([AllowAny])
def password_reset_request(request):
    """Email a reset token. Always answers 200 so accounts cannot be enumerated."""
    serializer = PasswordResetRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    user = User.objects.filter(email__iexact=serializer.validated_data["email"], is_active=True).first()
    if user:
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)
        try:
            send_mail(
                "Password reset",
                f"Use uid={uid} and token={token} at /api/v1/accounts/password/reset/confirm/",
                None, [user.email],
            )
        except Exception:  # email problems must not reveal whether the account exists
            pass
    return Response({"detail": "If the account exists, a reset email has been sent."})


@extend_schema(request=PasswordResetConfirmSerializer, responses={200: None})
@api_view(["POST"])
@permission_classes([AllowAny])
def password_reset_confirm(request):
    """Set a new password using the uid/token from the reset email."""
    serializer = PasswordResetConfirmSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    user = serializer.validated_data["user"]
    user.set_password(serializer.validated_data["new_password"])
    user.save(update_fields=["password"])
    return Response({"detail": "Password has been reset."})


class UserProfileView(generics.RetrieveUpdateAPIView):
    """GET, PUT or PATCH the authenticated user's profile."""

    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user


class SavedSearchViewSet(viewsets.ModelViewSet):
    """Your saved trip/destination searches (list, create, rename, delete)."""

    serializer_class = SavedSearchSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["search_type"]
    search_fields = ["name"]
    ordering_fields = ["created_at", "name"]

    def get_queryset(self):
        return SavedSearch.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
