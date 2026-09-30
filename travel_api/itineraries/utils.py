"""Helpers for the audit trail."""
from .models import ActivityLog


def log_activity(user, action, itinerary=None, description=""):
    """Record an audit-trail entry."""
    return ActivityLog.objects.create(
        user=user if getattr(user, "is_authenticated", False) else None,
        action=action, itinerary=itinerary, description=description[:300],
    )
