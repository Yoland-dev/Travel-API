"""Itinerary views: FBVs (search, report), CBVs (collaboration, documents) and ViewSets."""
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ObjectDoesNotExist
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Avg, Case, Count, ExpressionWrapper, F, IntegerField, DecimalField, Prefetch, Q, Sum, Value, When
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import filters, generics, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import NotFound
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.serializers import SavedSearchSerializer
from budgets.models import Expense
from core.pagination import SmallPagination

from .filters import ItineraryFilter
from .models import ActivityLog, DailyPlan, Itinerary, ItineraryDocument
from .pdf import build_itinerary_pdf
from .permissions import (
    CanEditItinerary, CanEditRelatedItinerary, IsTripOwner, IsTripOwnerOrCollaborator, check_can_edit,
)
from .selectors import visible_itineraries
from .serializers import (
    ActivityLogSerializer, CollaborationSerializer, CollaboratorRoleSerializer, DailyPlanSerializer,
    ItineraryDetailSerializer, ItineraryDocumentSerializer, ItineraryListSerializer, ItinerarySerializer,
    SetStatusSerializer, ShareItinerarySerializer,
)
from .utils import log_activity

Action = ActivityLog.ActionChoices


# --------------------------------------------------------------------------- FBVs
@extend_schema(
    methods=["GET"], responses=ItineraryListSerializer(many=True),
    parameters=[OpenApiParameter("q", str, description="Text search"),
                OpenApiParameter("status", str, many=True), OpenApiParameter("min_budget", float),
                OpenApiParameter("max_budget", float), OpenApiParameter("ordering", str)],
)
@extend_schema(methods=["POST"], request=SavedSearchSerializer, responses={201: SavedSearchSerializer})
@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def trip_search(request):
    """GET: search trips with filters and relevance ranking. POST: save the search.

    Example: GET /api/v1/itineraries/search/?q=paris&status=planning&min_budget=500&ordering=budget
    """
    if request.method == "POST":
        serializer = SavedSearchSerializer(data={**request.data, "search_type": "trip"})
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        serializer.save(user=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    params = request.query_params
    qs = visible_itineraries(request.user, include_public=True)
    q = params.get("q", "").strip()
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q)
                       | Q(destination__name__icontains=q) | Q(destination__country__icontains=q))
        # ranking: title match > destination match > everything else
        qs = qs.annotate(relevance=Case(
            When(title__icontains=q, then=Value(3)),
            When(destination__name__icontains=q, then=Value(2)),
            default=Value(1), output_field=IntegerField()))
    statuses = params.getlist("status")
    if statuses:
        qs = qs.filter(status__in=statuses)
    try:
        if params.get("min_budget"):
            qs = qs.filter(budget__gte=Decimal(params["min_budget"]))
        if params.get("max_budget"):
            qs = qs.filter(budget__lte=Decimal(params["max_budget"]))
        if params.get("start_after"):
            qs = qs.filter(start_date__gte=params["start_after"])
        if params.get("start_before"):
            qs = qs.filter(start_date__lte=params["start_before"])
    except (InvalidOperation, ValueError):
        return Response({"error": "Invalid numeric or date filter."}, status=status.HTTP_400_BAD_REQUEST)
    except Exception:  # malformed dates raise a Django ValidationError at filter time
        return Response({"error": "Invalid numeric or date filter."}, status=status.HTTP_400_BAD_REQUEST)

    ordering = params.get("ordering")
    allowed = {"start_date", "-start_date", "budget", "-budget", "created_at", "-created_at"}
    if ordering in allowed:
        qs = qs.order_by(ordering)
    elif q:
        qs = qs.order_by("-relevance", "-start_date")
    paginator = SmallPagination()
    try:
        page = paginator.paginate_queryset(qs, request)
    except Exception:  # invalid date strings surface lazily when the query runs
        return Response({"error": "Invalid numeric or date filter."}, status=status.HTTP_400_BAD_REQUEST)
    data = ItineraryListSerializer(page, many=True, context={"request": request}).data
    return paginator.get_paginated_response(data)


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def generate_trip_report(request, trip_id):
    """Comprehensive report: budget vs actual, bookings, day plans and collaborators.

    Example: GET /api/v1/itineraries/12/report/
    """
    itinerary = get_object_or_404(visible_itineraries(request.user).prefetch_related("daily_plans"), pk=trip_id)
    expense_rows = (itinerary.expenses.values("category")
                    .annotate(total=Sum("amount"), count=Count("id")).order_by("-total"))
    booking_stats = itinerary.bookings.exclude(status="cancelled").aggregate(
        total_price=Sum("price"), count=Count("id"))
    by_status = itinerary.bookings.values("status").annotate(count=Count("id"))
    try:
        allocated = itinerary.budget_detail.total_budget
    except ObjectDoesNotExist:
        allocated = None
    spent = itinerary.expenses.aggregate(total=Sum("amount"))["total"] or Decimal("0")
    # Guard against division by zero when a trip has no budget.
    percent = round(float(spent / itinerary.budget * 100), 1) if itinerary.budget else 0
    return Response({
        "trip": {"id": itinerary.id, "title": itinerary.title, "destination": itinerary.destination.name,
                 "start_date": itinerary.start_date, "end_date": itinerary.end_date,
                 "duration_days": itinerary.duration_days, "status": itinerary.status},
        "budget": {"planned": itinerary.budget, "allocated_by_category": allocated, "spent": spent,
                   "remaining": itinerary.budget - spent, "percent_used": percent,
                   "over_budget": spent > itinerary.budget, "spending_by_category": list(expense_rows)},
        "bookings": {"active_count": booking_stats["count"], "active_total": booking_stats["total_price"] or 0,
                     "by_status": list(by_status)},
        "daily_plans": [{"day": p.day_number, "date": p.date, "title": p.title} for p in itinerary.daily_plans.all()],
        "collaborators": [{"username": c.user.username, "role": c.role} for c in itinerary.collaborations.all()],
    })


# --------------------------------------------------------------------------- CBVs
class ItineraryListCreateView(generics.ListCreateAPIView):
    """List the trips you own, or create a new one."""

    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        return ItinerarySerializer if self.request.method == "POST" else ItineraryListSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Itinerary.objects.none()
        return Itinerary.objects.filter(owner=self.request.user).select_related("destination", "owner")

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class TripCollaborationView(APIView):
    """Manage collaborators: GET list, POST add, PATCH change role, DELETE remove."""

    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAuthenticated(), IsTripOwnerOrCollaborator()]
        return [IsAuthenticated(), IsTripOwner()]

    def get_itinerary(self, request, trip_id):
        itinerary = visible_itineraries(request.user).filter(pk=trip_id).first()
        if itinerary is None:
            raise NotFound("Itinerary not found.")
        self.check_object_permissions(request, itinerary)
        return itinerary

    @extend_schema(responses=CollaborationSerializer(many=True))
    def get(self, request, trip_id):
        itinerary = self.get_itinerary(request, trip_id)
        return Response(CollaborationSerializer(itinerary.collaborations.all(), many=True).data)

    @extend_schema(request=ShareItinerarySerializer, responses={201: CollaborationSerializer})
    def post(self, request, trip_id):
        itinerary = self.get_itinerary(request, trip_id)
        serializer = ShareItinerarySerializer(data=request.data, context={"itinerary": itinerary})
        serializer.is_valid(raise_exception=True)
        collab = serializer.save()
        log_activity(request.user, Action.SHARED, itinerary, f"Shared with {collab.user.username} as {collab.role}")
        return Response(CollaborationSerializer(collab).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=CollaboratorRoleSerializer, responses=CollaborationSerializer)
    def patch(self, request, trip_id, user_id):
        itinerary = self.get_itinerary(request, trip_id)
        collab = get_object_or_404(itinerary.collaborations, user_id=user_id)
        serializer = CollaboratorRoleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        collab.role = serializer.validated_data["role"]
        collab.save(update_fields=["role"])
        log_activity(request.user, Action.SHARED, itinerary, f"Changed {collab.user.username} to {collab.role}")
        return Response(CollaborationSerializer(collab).data)

    @extend_schema(responses={204: None})
    def delete(self, request, trip_id, user_id):
        itinerary = self.get_itinerary(request, trip_id)
        collab = get_object_or_404(itinerary.collaborations, user_id=user_id)
        username = collab.user.username
        collab.delete()
        log_activity(request.user, Action.UNSHARED, itinerary, f"Removed {username}")
        return Response(status=status.HTTP_204_NO_CONTENT)


class ItineraryDocumentListCreateView(generics.ListCreateAPIView):
    """GET the documents of a trip or POST (multipart) a new PDF/photo."""

    serializer_class = ItineraryDocumentSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def get_itinerary(self):
        itinerary = visible_itineraries(self.request.user, include_public=True).filter(pk=self.kwargs["trip_id"]).first()
        if itinerary is None:
            raise NotFound("Itinerary not found.")
        return itinerary

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ItineraryDocument.objects.none()
        return (ItineraryDocument.objects.filter(itinerary=self.get_itinerary())
                .select_related("uploaded_by"))

    def perform_create(self, serializer):
        itinerary = self.get_itinerary()
        check_can_edit(itinerary, self.request.user)
        doc = serializer.save(itinerary=itinerary, uploaded_by=self.request.user)
        log_activity(self.request.user, Action.DOCUMENT, itinerary, f"Uploaded '{doc.title}'")


class ItineraryDocumentDetailView(generics.RetrieveDestroyAPIView):
    """Retrieve or delete one document (delete needs edit rights)."""

    serializer_class = ItineraryDocumentSerializer
    permission_classes = [IsAuthenticated, CanEditRelatedItinerary]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ItineraryDocument.objects.none()
        ids = visible_itineraries(self.request.user, include_public=True).values("id")
        return (ItineraryDocument.objects.filter(itinerary_id=self.kwargs["trip_id"], itinerary__in=ids)
                .select_related("itinerary", "itinerary__owner").prefetch_related("itinerary__collaborations"))

    def perform_destroy(self, instance):
        instance.file.delete(save=False)  # remove the file from storage too
        instance.delete()


# --------------------------------------------------------------------------- ViewSets
class ItineraryViewSet(viewsets.ModelViewSet):
    """CRUD for itineraries plus duplicate, export_pdf, share, upcoming and status actions.

    Example: GET /api/v1/itineraries/?status=planning&search=paris&ordering=-start_date
    """

    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = ItineraryFilter
    search_fields = ["title", "description", "destination__name"]
    ordering_fields = ["created_at", "start_date", "budget"]

    def get_queryset(self):
        qs = visible_itineraries(self.request.user, include_public=self.action == "retrieve")
        if self.action == "list":
            return qs.defer("description")  # list serializer does not show it
        return qs.prefetch_related(
            Prefetch("daily_plans", queryset=DailyPlan.objects.prefetch_related("activities")))

    def get_serializer_class(self):
        if self.action == "list":
            return ItineraryListSerializer
        if self.action == "retrieve":
            return ItineraryDetailSerializer
        return ItinerarySerializer

    def get_permissions(self):
        if self.action in ("update", "partial_update", "set_status"):
            return [IsAuthenticated(), CanEditItinerary()]
        if self.action in ("destroy", "share_with_user"):
            return [IsAuthenticated(), IsTripOwner()]
        if self.action in ("duplicate", "export_pdf"):
            return [IsAuthenticated(), IsTripOwnerOrCollaborator()]
        return [IsAuthenticated()]

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    def perform_destroy(self, instance):
        log_activity(self.request.user, Action.DELETED, None, f"Deleted trip '{instance.title}'")
        instance.delete()

    @action(detail=True, methods=["post"])
    def duplicate(self, request, pk=None):
        """Copy a trip (day plans and budget split, not bookings) to a new planning-stage trip."""
        original = self.get_object()
        shift = timedelta(0)
        if request.data.get("start_date"):
            try:
                new_start = timezone.datetime.strptime(request.data["start_date"], "%Y-%m-%d").date()
            except ValueError:
                return Response({"error": "start_date must be YYYY-MM-DD."}, status=status.HTTP_400_BAD_REQUEST)
            shift = new_start - original.start_date
        # Atomic so a half-copied trip is never left behind if any step fails.
        with transaction.atomic():
            copy = Itinerary.objects.create(
                title=f"Copy of {original.title}", description=original.description, destination=original.destination,
                owner=request.user, start_date=original.start_date + shift, end_date=original.end_date + shift,
                budget=original.budget)
            for plan in original.daily_plans.all():
                new_plan = DailyPlan.objects.create(
                    itinerary=copy, day_number=plan.day_number, date=plan.date + shift, title=plan.title, notes=plan.notes)
                new_plan.activities.set(plan.activities.all())
            source = getattr(original, "budget_detail", None)
            if source:
                for field in ("accommodation", "activities", "food", "transport", "shopping", "miscellaneous"):
                    setattr(copy.budget_detail, f"{field}_budget", getattr(source, f"{field}_budget"))
                copy.budget_detail.save()
        log_activity(request.user, Action.CREATED, copy, f"Duplicated from '{original.title}'")
        return Response(ItineraryDetailSerializer(copy, context={"request": request}).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"], url_path="export-pdf")
    def export_pdf(self, request, pk=None):
        """Download the itinerary as a PDF."""
        itinerary = self.get_object()
        try:
            content = build_itinerary_pdf(itinerary)
        except Exception:
            return Response({"error": "Could not generate the PDF."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        response = HttpResponse(content, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="itinerary-{itinerary.pk}.pdf"'
        return response

    @action(detail=True, methods=["post"], url_path="share")
    def share_with_user(self, request, pk=None):
        """Share the itinerary with another user by email (owner only)."""
        itinerary = self.get_object()
        serializer = ShareItinerarySerializer(data=request.data, context={"itinerary": itinerary})
        serializer.is_valid(raise_exception=True)
        collab = serializer.save()
        log_activity(request.user, Action.SHARED, itinerary, f"Shared with {collab.user.username} as {collab.role}")
        try:
            send_mail(f"{request.user.username} shared a trip with you",
                      f"You were added to '{itinerary.title}' as {collab.role}.", None, [collab.user.email])
        except Exception:  # a mail failure must not undo the share
            pass
        return Response(CollaborationSerializer(collab).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get"], url_path="upcoming")
    def upcoming_trips(self, request):
        """Your future trips ordered by start date."""
        qs = (self.get_queryset().filter(start_date__gte=timezone.now().date())
              .exclude(status__in=["cancelled", "completed"]).order_by("start_date"))
        page = self.paginate_queryset(qs)
        serializer = ItineraryListSerializer(page, many=True, context={"request": request})
        return self.get_paginated_response(serializer.data)

    @action(detail=True, methods=["post"], url_path="status")
    def set_status(self, request, pk=None):
        """Change the trip status (validated transitions)."""
        itinerary = self.get_object()
        serializer = SetStatusSerializer(data=request.data, context={"itinerary": itinerary})
        serializer.is_valid(raise_exception=True)
        old = itinerary.status
        itinerary.status = serializer.validated_data["status"]
        itinerary.save(update_fields=["status", "updated_at"])
        log_activity(request.user, Action.STATUS, itinerary, f"Status {old} -> {itinerary.status}")
        return Response(ItineraryListSerializer(itinerary, context={"request": request}).data)


class DailyPlanViewSet(viewsets.ModelViewSet):
    """Day-by-day planning: CRUD on the days of trips you can access."""

    serializer_class = DailyPlanSerializer
    permission_classes = [IsAuthenticated, CanEditRelatedItinerary]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["itinerary", "date"]
    search_fields = ["title", "notes"]
    ordering_fields = ["day_number", "date"]

    def get_queryset(self):
        ids = visible_itineraries(self.request.user, include_public=True).values("id")
        return (DailyPlan.objects.filter(itinerary__in=ids)
                .select_related("itinerary", "itinerary__owner").prefetch_related("activities", "itinerary__collaborations"))

    def perform_create(self, serializer):
        check_can_edit(serializer.validated_data["itinerary"], self.request.user)
        serializer.save()


class ActivityLogViewSet(viewsets.ReadOnlyModelViewSet):
    """Audit trail of actions on trips you own or share."""

    serializer_class = ActivityLogSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ["itinerary", "action", "user"]
    ordering_fields = ["created_at"]

    def get_queryset(self):
        user = self.request.user
        ids = visible_itineraries(user).values("id")
        return ActivityLog.objects.filter(Q(itinerary__in=ids) | Q(user=user)).select_related("user", "itinerary").distinct()


class TripAnalyticsViewSet(viewsets.ViewSet):
    """Statistics over the trips you own."""

    permission_classes = [IsAuthenticated]
    serializer_class = None

    def _owned(self, request):
        return Itinerary.objects.filter(owner=request.user)

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def list(self, request):
        """Totals, averages and status breakdown."""
        qs = self._owned(request)
        totals = qs.aggregate(trips=Count("id"), total_budget=Sum("budget"), total_spent=Sum("actual_spent"),
                              avg_budget=Avg("budget"))
        durations = [(e - s).days + 1 for s, e in qs.values_list("start_date", "end_date")]
        return Response({
            **totals,
            "avg_duration_days": round(sum(durations) / len(durations), 1) if durations else 0,
            "by_status": list(qs.values("status").annotate(count=Count("id")).order_by("status")),
            "upcoming": qs.filter(start_date__gte=timezone.now().date()).exclude(status__in=["cancelled", "completed"]).count(),
        })

    @extend_schema(responses=OpenApiTypes.OBJECT)
    @action(detail=False, methods=["get"], url_path="budget-summary")
    def budget_summary(self, request):
        """Spending by category and trips that exceed their budget."""
        qs = self._owned(request)
        by_category = (Expense.objects.filter(itinerary__owner=request.user).values("category")
                       .annotate(total=Sum("amount"), count=Count("id")).order_by("-total"))
        over = (qs.filter(actual_spent__gt=F("budget"))
                .annotate(variance=ExpressionWrapper(F("budget") - F("actual_spent"), output_field=DecimalField()))
                .values("id", "title", "budget", "actual_spent", "variance"))
        return Response({"totals": qs.aggregate(budget=Sum("budget"), spent=Sum("actual_spent")),
                         "spending_by_category": list(by_category), "over_budget_trips": list(over)})

    @extend_schema(responses=OpenApiTypes.OBJECT)
    @action(detail=False, methods=["get"], url_path="destination-preferences")
    def destination_preferences(self, request):
        """Which destination categories, climates and places you choose most."""
        qs = self._owned(request)
        categories = qs.values("destination__category").annotate(trips=Count("id")).order_by("-trips")
        climates = qs.values("destination__climate").annotate(trips=Count("id")).order_by("-trips")
        top = (qs.values("destination__name", "destination__country").annotate(trips=Count("id")).order_by("-trips")[:5])
        return Response({"favorite_category": categories[0]["destination__category"] if categories else None,
                         "categories": list(categories), "climates": list(climates), "top_destinations": list(top)})
