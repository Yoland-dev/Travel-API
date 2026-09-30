from rest_framework import permissions


class IsBookingOwner(permissions.BasePermission):
    """Only the user who made the booking may modify it."""

    def has_object_permission(self, request, view, obj):
        return obj.user_id == request.user.id
