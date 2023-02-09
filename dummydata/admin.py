from django.contrib import admin
from .models import DummyData

class DummyDataAdmin(admin.ModelAdmin):
    list_display = ('customer', 'reference')
    list_filter = ('customer',)

admin.site.register(DummyData, DummyDataAdmin)

