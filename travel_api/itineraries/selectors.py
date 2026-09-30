"""Reusable itinerary querysets."""
from django.db.models import Prefetch, Q

from .models import Collaboration, Itinerary


def visible_itineraries(user, include_public=False):
    """Trips the user owns or collaborates on (optionally also public trips)."""
    shared_ids = Collaboration.objects.filter(user=user).values("itinerary_id")
    condition = Q(owner=user) | Q(pk__in=shared_ids)
    if include_public:
        condition |= Q(is_public=True)
    # only(): the API needs just these collaborator columns
    collaborators = Collaboration.objects.select_related("user").only(
        "id", "itinerary", "user", "role", "invited_at", "user__username", "user__email")
    return (Itinerary.objects.filter(condition)
            .select_related("destination", "owner")
            .prefetch_related(Prefetch("collaborations", queryset=collaborators)))
