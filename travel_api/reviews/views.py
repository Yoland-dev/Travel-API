"""Review views."""
from django.db.models import Avg, Count, F
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, generics, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from accounts.permissions import IsOwnerOrReadOnly
from core.pagination import SmallPagination

from .filters import ReviewFilter
from .models import Review
from .serializers import ReviewSerializer

TARGET_TYPES = ("destination", "accommodation", "activity")


class ReviewViewSet(viewsets.ModelViewSet):
    """Reviews are public to read; only the author may edit or delete.

    Example: GET /api/v1/reviews/?destination=3&min_rating=4&ordering=-helpful_count
    """

    serializer_class = ReviewSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = ReviewFilter
    search_fields = ["title", "content"]
    ordering_fields = ["rating", "created_at", "helpful_count"]
    pagination_class = SmallPagination

    def get_queryset(self):
        return Review.objects.select_related("user", "destination", "accommodation", "activity")

    def get_permissions(self):
        if self.action in ("list", "retrieve", "summary"):
            return [AllowAny()]
        if self.action in ("update", "partial_update", "destroy"):
            return [IsAuthenticated(), IsOwnerOrReadOnly()]
        return [IsAuthenticated()]

    @action(detail=True, methods=["post"])
    def helpful(self, request, pk=None):
        """Mark a review as helpful (atomic counter increment)."""
        review = self.get_object()
        Review.objects.filter(pk=review.pk).update(helpful_count=F("helpful_count") + 1)
        review.refresh_from_db()
        return Response({"id": review.id, "helpful_count": review.helpful_count})

    @action(detail=False, methods=["get"])
    def mine(self, request):
        """Your own reviews."""
        page = self.paginate_queryset(self.filter_queryset(self.get_queryset().filter(user=request.user)))
        return self.get_paginated_response(self.get_serializer(page, many=True).data)

    @action(detail=False, methods=["get"])
    def summary(self, request):
        """Rating statistics: /reviews/summary/?destination=1 (or accommodation / activity)."""
        qs = self.filter_queryset(self.get_queryset())
        stats = qs.aggregate(average=Avg("rating"), count=Count("id"))
        distribution = {str(r): qs.filter(rating=r).count() for r in range(1, 6)}
        return Response({"average": round(stats["average"], 2) if stats["average"] else 0,
                         "count": stats["count"], "distribution": distribution})


class TargetReviewsView(generics.ListAPIView):
    """List reviews for one item: /reviews/target/<destination|accommodation|activity>/<id>/."""

    serializer_class = ReviewSerializer
    permission_classes = [AllowAny]
    pagination_class = SmallPagination

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Review.objects.none()
        target_type = self.kwargs["target_type"]
        if target_type not in TARGET_TYPES:
            raise NotFound("Unknown review target type.")
        return (Review.objects.filter(**{f"{target_type}_id": self.kwargs["target_id"]})
                .select_related("user", "destination", "accommodation", "activity").order_by("-helpful_count", "-created_at"))
