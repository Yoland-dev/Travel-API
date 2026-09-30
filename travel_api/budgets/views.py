"""Budget and expense views."""
from django.db.models import Count, Sum
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, generics, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from itineraries.permissions import CanEditRelatedItinerary, check_can_edit
from itineraries.selectors import visible_itineraries

from .filters import ExpenseFilter
from .models import Budget, Expense
from .serializers import BudgetSerializer, ExpenseSerializer


class BudgetDetailView(generics.RetrieveUpdateAPIView):
    """GET/PUT/PATCH the category budget of a trip (edit needs editor rights)."""

    serializer_class = BudgetSerializer
    permission_classes = [IsAuthenticated, CanEditRelatedItinerary]

    def get_object(self):
        itinerary = visible_itineraries(self.request.user).filter(pk=self.kwargs["trip_id"]).first()
        if itinerary is None:
            raise NotFound("Itinerary not found.")
        budget, _ = Budget.objects.select_related("itinerary").get_or_create(itinerary=itinerary)
        budget.itinerary = itinerary  # keep the prefetched collaborations for permission checks
        self.check_object_permissions(self.request, budget)
        return budget


class ExpenseViewSet(viewsets.ModelViewSet):
    """Expenses on trips you can see; only editors may add, change or delete.

    Example: GET /api/v1/expenses/?itinerary=4&category=food&ordering=-amount
    """

    serializer_class = ExpenseSerializer
    permission_classes = [IsAuthenticated, CanEditRelatedItinerary]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = ExpenseFilter
    search_fields = ["description", "notes"]
    ordering_fields = ["date", "amount", "created_at"]

    def get_queryset(self):
        ids = visible_itineraries(self.request.user).values("id")
        return (Expense.objects.filter(itinerary__in=ids)
                .select_related("itinerary", "itinerary__owner", "paid_by").prefetch_related("itinerary__collaborations"))

    def perform_create(self, serializer):
        check_can_edit(serializer.validated_data["itinerary"], self.request.user)
        serializer.save()

    @action(detail=False, methods=["get"])
    def summary(self, request):
        """Totals per category for the filtered expenses (use ?itinerary=<id>)."""
        qs = self.filter_queryset(self.get_queryset())
        rows = qs.values("category").annotate(total=Sum("amount"), count=Count("id")).order_by("-total")
        return Response({"total": qs.aggregate(total=Sum("amount"))["total"] or 0, "by_category": list(rows)})
