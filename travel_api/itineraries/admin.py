from django.contrib import admin

from .models import ActivityLog, Collaboration, DailyPlan, Itinerary, ItineraryDocument

admin.site.register([Itinerary, Collaboration, DailyPlan, ItineraryDocument, ActivityLog])
