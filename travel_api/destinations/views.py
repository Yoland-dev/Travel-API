"""Destination browsing: ViewSet, search view, slug lookup and recommendations (FBV)."""
from django.db.models import Avg, Case, Count, IntegerField, Q, Prefetch, Value, When
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import filters, generics, serializers, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated, IsAuthenticatedOrReadOnly
from rest_framework.response import Response
from rest_framework.views import APIView
from django_filters.rest_framework import DjangoFilterBackend

from accounts.serializers import SavedSearchSerializer
from bookings.models import Activity
from bookings.serializers import PopularActivitySerializer
from core.pagination import SmallPagination

from .filters import DestinationFilter
from .models import Destination
from .serializers import (
    DestinationDetailSerializer, DestinationImageSerializer, DestinationListSerializer,
    RecommendedDestinationSerializer,
)
from .utils import CLIMATE_PROFILES


def annotated_destinations():
    """Active destinations with rating/review aggregates computed in SQL."""
    return Destination.objects.filter(is_active=True).annotate(
        avg_rating=Avg("reviews__rating"), review_total=Count("reviews", distinct=True),
    ).order_by("name")  # annotate() with aggregates drops Meta.ordering


class DestinationViewSet(viewsets.ReadOnlyModelViewSet):
    """Browse destinations (public, read-only).

    Example: GET /api/v1/destinations/?category=beach&search=bali&ordering=-avg_daily_cost
    """

    permission_classes = [AllowAny]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = DestinationFilter
    search_fields = ["name", "description", "country"]
    ordering_fields = ["name", "avg_daily_cost", "created_at"]

    def get_queryset(self):
        qs = annotated_destinations()
        if self.action == "list":
            # only(): the list serializer needs just these columns
            return qs.only("id", "name", "slug", "country", "category", "climate", "avg_daily_cost", "image")
        return qs.prefetch_related(
            Prefetch("activities", queryset=Activity.objects.filter(is_available=True).order_by("name"))
        )

    def get_serializer_class(self):
        if self.action == "list":
            return DestinationListSerializer
        if self.action == "upload_image":
            return DestinationImageSerializer
        return DestinationDetailSerializer

    def get_permissions(self):
        if self.action == "upload_image":
            return [IsAuthenticated(), IsAdminUser()]
        return [AllowAny()]

    @action(detail=True, methods=["get"])
    def popular_activities(self, request, pk=None):
        """Activities at this destination ranked by number of bookings."""
        destination = self.get_object()
        activities = (destination.activities.filter(is_available=True)
                      .annotate(booking_count=Count("bookings")).order_by("-booking_count", "name")[:10])
        return Response(PopularActivitySerializer(activities, many=True, context={"request": request}).data)

    @action(detail=True, methods=["get"])
    def weather_info(self, request, pk=None):
        """Seasonal weather profile based on the destination's climate."""
        destination = self.get_object()
        profile = CLIMATE_PROFILES.get(destination.climate, {})
        return Response({"destination": destination.name, "climate": destination.climate,
                         "best_time_to_visit": destination.best_time_to_visit, **profile})

    @action(detail=True, methods=["post"], parser_classes=[MultiPartParser, FormParser], url_path="upload-image")
    def upload_image(self, request, pk=None):
        """Admin only: upload a destination photo (multipart, field 'image')."""
        destination = self.get_object()
        serializer = DestinationImageSerializer(destination, data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)


class DestinationSearchView(APIView):
    """Advanced destination search with relevance ranking; POST saves the search."""

    permission_classes = [IsAuthenticatedOrReadOnly]

    @extend_schema(responses=DestinationListSerializer(many=True))
    def get(self, request):
        """GET /destinations/search/?q=beach&min_cost=50&max_cost=200&sort=rating"""
        params = request.query_params
        qs = annotated_destinations()
        q = params.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(name__icontains=q) | Q(description__icontains=q)
                | Q(country__icontains=q) | Q(activities__name__icontains=q)
            ).distinct()
            qs = qs.annotate(relevance=Case(
                When(name__icontains=q, then=Value(3)),
                When(country__icontains=q, then=Value(2)),
                default=Value(1), output_field=IntegerField()))
        try:
            if params.get("min_cost"):
                qs = qs.filter(avg_daily_cost__gte=float(params["min_cost"]))
            if params.get("max_cost"):
                qs = qs.filter(avg_daily_cost__lte=float(params["max_cost"]))
        except ValueError:
            return Response({"error": "min_cost and max_cost must be numbers."}, status=status.HTTP_400_BAD_REQUEST)
        for field in ("category", "climate"):
            if params.get(field):
                qs = qs.filter(**{field: params[field]})
        ordering = {"rating": ["-avg_rating", "name"], "cost": ["avg_daily_cost", "name"]}.get(params.get("sort"))
        if ordering is None:
            ordering = ["-relevance", "-avg_rating", "name"] if q else ["name"]
        paginator = SmallPagination()
        page = paginator.paginate_queryset(qs.order_by(*ordering), request, view=self)
        return paginator.get_paginated_response(
            DestinationListSerializer(page, many=True, context={"request": request}).data)

    @extend_schema(request=SavedSearchSerializer, responses={201: SavedSearchSerializer})
    def post(self, request):
        """Save the current search as a preference for later."""
        serializer = SavedSearchSerializer(data={**request.data, "search_type": "destination"})
        serializer.is_valid(raise_exception=True)
        serializer.save(user=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class DestinationBySlugView(generics.RetrieveAPIView):
    """Retrieve a destination by its URL slug."""

    permission_classes = [AllowAny]
    serializer_class = DestinationDetailSerializer
    lookup_field = "slug"

    def get_queryset(self):
        return annotated_destinations()


@extend_schema(responses=RecommendedDestinationSerializer(many=True))
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def recommendations(request):
    """Personalised destination recommendations from preferences, favourites and past trips.

    Example: GET /api/v1/destinations/recommendations/?limit=5
    """
    try:
        limit = max(1, min(int(request.query_params.get("limit", 10)), 50))
    except ValueError:
        return Response({"error": "limit must be an integer."}, status=status.HTTP_400_BAD_REQUEST)
    prefs = request.user.travel_preferences or {}
    visited = request.user.owned_itineraries.values_list("destination_id", flat=True)
    favorite_rows = list(request.user.favorite_destinations.values_list("id", "category"))
    favorite_categories = {category for _, category in favorite_rows}
    # already-visited and already-favourited places are not "discoveries"
    candidates = annotated_destinations().exclude(pk__in=list(visited)).exclude(pk__in=[i for i, _ in favorite_rows])
    scored = []
    for dest in candidates:
        # Additive scoring: each matched preference adds points; rating only breaks ties.
        score, reasons = 0.0, []
        if dest.category in prefs.get("categories", []) or dest.category in favorite_categories:
            score += 3
            reasons.append(f"matches your interest in {dest.category}")
        if dest.climate in prefs.get("climates", []):
            score += 2
            reasons.append(f"{dest.climate} climate you like")
        max_budget = prefs.get("max_daily_budget")
        if max_budget is not None and dest.avg_daily_cost <= max_budget:
            score += 2
            reasons.append("fits your daily budget")
        score += float(dest.avg_rating or 0) / 5  # rating is a tie-breaker
        dest.score, dest.reasons = round(score, 2), reasons
        scored.append(dest)
    # Highest score first; name keeps the order deterministic for equal scores.
    scored.sort(key=lambda d: (-d.score, d.name))
    return Response(RecommendedDestinationSerializer(scored[:limit], many=True, context={"request": request}).data)


@extend_schema(methods=["GET"], responses=DestinationListSerializer(many=True))
@extend_schema(methods=["POST", "DELETE"],
               request=inline_serializer("FavoriteRequest", {"destination": serializers.IntegerField()}),
               responses={200: DestinationListSerializer(many=True)})
@api_view(["GET", "POST", "DELETE"])
@permission_classes([IsAuthenticated])
def favorites(request):
    """List (GET), add (POST) or remove (DELETE) favourite destinations.

    Example: POST /api/v1/destinations/favorites/ {"destination": 3}
    """
    user = request.user
    if request.method in ("POST", "DELETE"):
        destination = Destination.objects.filter(pk=request.data.get("destination"), is_active=True).first()
        if destination is None:
            return Response({"error": "Destination not found."}, status=status.HTTP_404_NOT_FOUND)
        if request.method == "POST":
            user.favorite_destinations.add(destination)
        else:
            user.favorite_destinations.remove(destination)
    qs = annotated_destinations().filter(favorited_by=user)
    code = status.HTTP_201_CREATED if request.method == "POST" else status.HTTP_200_OK
    return Response(DestinationListSerializer(qs, many=True, context={"request": request}).data, status=code)
