from django.contrib import admin

from .models import Destination


@admin.register(Destination)
class DestinationAdmin(admin.ModelAdmin):
    list_display = ("name", "country", "category", "climate", "avg_daily_cost", "is_active")
    list_filter = ("category", "climate", "is_active")
    search_fields = ("name", "country")
