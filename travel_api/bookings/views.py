"""Bookings: bulk FBV, detail CBV and ViewSets."""
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from rest_framework import filters, generics, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from itineraries.models import ActivityLog
from itineraries.utils import log_activity

from .filters import AccommodationFilter, BookingFilter
from .models import Accommodation, Activity, Booking
from .permissions import IsBookingOwner
from .serializers import (
    AccommodationSerializer, ActivitySerializer, BookingDetailSerializer, BookingSerializer,
    BulkBookingUpdateSerializer,
)


class _Abort(Exception):
    """Raised inside the transaction to trigger a full rollback."""


@extend_schema(request=BulkBookingUpdateSerializer, responses={200: None})
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def bulk_update_bookings(request):
    """Confirm or cancel several of your bookings in one request.

    Example body: {"updates": [{"id": 1, "action": "confirm"}, {"id": 2, "action": "cancel"}],
    "all_or_nothing": false}
    """
    serializer = BulkBookingUpdateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    items = serializer.validated_data["updates"]
    all_or_nothing = serializer.validated_data["all_or_nothing"]
    # One query for every referenced booking; restricting to request.user blocks touching others' bookings.
    bookings = {b.id: b for b in Booking.objects.filter(user=request.user, id__in=[i["id"] for i in items])
                .select_related("accommodation", "activity", "itinerary")}
    results = []
    try:
        with transaction.atomic():
            for item in items:
                booking = bookings.get(item["id"])
                if booking is None:
                    results.append({"id": item["id"], "success": False, "error": "Booking not found."})
                    succeeded = False
                else:
                    succeeded = _apply(booking, item, results)
                if not succeeded and all_or_nothing:
                    raise _Abort()  # undo every change made so far
    except _Abort:
        return Response({"success_count": 0, "failure_count": len(items), "rolled_back": True,
                         "results": results}, status=status.HTTP_400_BAD_REQUEST)
    ok = sum(1 for r in results if r["success"])
    return Response({"success_count": ok, "failure_count": len(results) - ok, "rolled_back": False,
                     "results": results})


def _apply(booking, item, results):
    """Apply one bulk item inside a savepoint; append the outcome to results."""
    # Nested atomic() = savepoint, so one failing item does not poison the outer transaction.
    try:
        with transaction.atomic():
            refund = None
            if item["action"] == "confirm":
                booking.confirm()
            else:
                refund = booking.cancel()
            if item.get("notes"):
                booking.notes = item["notes"]
                booking.save(update_fields=["notes", "updated_at"])
        log_activity(booking.user, ActivityLog.ActionChoices.BOOKING, booking.itinerary,
                     f"Bulk {item['action']} booking #{booking.pk}")
        results.append({"id": booking.id, "success": True, "status": booking.status,
                        "refund": str(refund) if refund is not None else None})
        return True
    except DjangoValidationError as exc:
        results.append({"id": booking.id, "success": False, "error": " ".join(exc.messages)})
        return False


class BookingDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, update or delete one of your bookings."""

    serializer_class = BookingDetailSerializer
    permission_classes = [IsAuthenticated, IsBookingOwner]

    def get_queryset(self):
        return Booking.objects.filter(user=self.request.user).select_related(
            "accommodation", "activity", "itinerary", "user")


class BookingViewSet(viewsets.ModelViewSet):
    """Manage accommodation and activity bookings; confirm and cancel actions."""

    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = BookingFilter
    search_fields = ["accommodation__name", "activity__name", "confirmation_code"]
    ordering_fields = ["created_at", "booking_date", "price"]

    def get_queryset(self):
        return Booking.objects.filter(user=self.request.user).select_related(
            "accommodation", "activity", "itinerary")

    def get_serializer_class(self):
        return BookingDetailSerializer if self.action == "retrieve" else BookingSerializer

    def get_permissions(self):
        if self.action in ("update", "partial_update", "destroy", "confirm", "cancel"):
            return [IsAuthenticated(), IsBookingOwner()]
        return [IsAuthenticated()]

    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        """Confirm a pending booking and issue a confirmation code."""
        booking = self.get_object()
        try:
            booking.confirm()
        except DjangoValidationError as exc:
            return Response({"error": exc.messages[0]}, status=status.HTTP_400_BAD_REQUEST)
        log_activity(request.user, ActivityLog.ActionChoices.BOOKING, booking.itinerary,
                     f"Confirmed booking #{booking.pk}")
        return Response(BookingSerializer(booking, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        """Cancel a booking and report the refund amount."""
        booking = self.get_object()
        try:
            refund = booking.cancel()
        except DjangoValidationError as exc:
            return Response({"error": exc.messages[0]}, status=status.HTTP_400_BAD_REQUEST)
        log_activity(request.user, ActivityLog.ActionChoices.BOOKING, booking.itinerary,
                     f"Cancelled booking #{booking.pk}")
        return Response({"booking": BookingSerializer(booking, context={"request": request}).data,
                         "refund_amount": str(refund)})


class AccommodationViewSet(viewsets.ReadOnlyModelViewSet):
    """Browse accommodations (public)."""

    queryset = Accommodation.objects.filter(is_available=True).select_related("destination")
    serializer_class = AccommodationSerializer
    permission_classes = [AllowAny]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = AccommodationFilter
    search_fields = ["name", "description", "address"]
    ordering_fields = ["price_per_night", "name"]


class ActivityViewSet(viewsets.ReadOnlyModelViewSet):
    """Browse activities (public)."""

    queryset = Activity.objects.filter(is_available=True).select_related("destination")
    serializer_class = ActivitySerializer
    permission_classes = [AllowAny]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["destination", "category"]
    search_fields = ["name", "description"]
    ordering_fields = ["price", "name", "duration_hours"]
