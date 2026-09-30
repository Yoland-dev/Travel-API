"""Role-based permissions: owner, collaborator (viewer/editor/admin)."""
from rest_framework import permissions
from rest_framework.exceptions import PermissionDenied

from .models import Itinerary


class IsTripOwner(permissions.BasePermission):
    """Only the trip owner."""

    def has_object_permission(self, request, view, obj):
        return obj.owner_id == request.user.id


class IsTripOwnerOrCollaborator(permissions.BasePermission):
    """Read for owner/collaborators (and public trips); writes are owner-only."""

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return obj.can_view(request.user)
        return obj.owner_id == request.user.id


class CanEditItinerary(permissions.BasePermission):
    """Owner, or collaborators whose role is editor/admin."""

    def has_object_permission(self, request, view, obj):
        return obj.can_edit(request.user)


class CanEditRelatedItinerary(permissions.BasePermission):
    """For objects that hang off an itinerary (daily plan, document, expense, budget).

    Reads need any access to the trip; writes need edit rights.
    """

    def has_object_permission(self, request, view, obj):
        itinerary = obj if isinstance(obj, Itinerary) else obj.itinerary
        if request.method in permissions.SAFE_METHODS:
            return itinerary.can_view(request.user)
        return itinerary.can_edit(request.user)


def check_can_edit(itinerary, user):
    """Raise 403 unless the user may edit the itinerary (used where DRF has no object check)."""
    if not itinerary.can_edit(user):
        raise PermissionDenied("You do not have permission to modify this itinerary.")
