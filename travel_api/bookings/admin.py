from django.contrib import admin

from .models import Accommodation, Activity, Booking

admin.site.register([Accommodation, Activity, Booking])
