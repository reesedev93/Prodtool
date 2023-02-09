from django.contrib import admin

from .models import Source


class SourceAdmin(admin.ModelAdmin):
    list_display = ("name", "last_checked")


admin.site.register(Source, SourceAdmin)
