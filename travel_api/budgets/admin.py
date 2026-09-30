from django.contrib import admin

from .models import Budget, Expense

admin.site.register([Budget, Expense])
