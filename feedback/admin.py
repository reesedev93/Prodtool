from django.contrib import admin

from .models import (
    CustomerFeedbackImporterSettings,
    FeatureRequest,
    Feedback,
    FeedbackImporter,
    Theme,
)


class FeedbackImporterAdmin(admin.ModelAdmin):
    list_display = ("name", "module")
    # list_filter = ('business__customer', 'sequence_number', 'sent')


class CustomerFeedbackImporterSettingsAdmin(admin.ModelAdmin):
    list_display = (
        "importer",
        "customer",
        "last_requested_at",
        "account_id",
    )
    list_filter = (
        "importer",
        "customer",
    )


class FeedbackAdmin(admin.ModelAdmin):
    change_list_template = "admin/feedback_changelist.html"

    list_display = ("short_problem", "feature_request", "state", "user", "created_by")
    list_filter = ("updated", "source_updated", "customer", "source", "state")
    readonly_fields = ("user", "feature_request", "themes", "feedback_type")

    def short_problem(self, obj):
        return obj.get_problem_snippet()

    short_problem.short_description = "Short Problem"


class FeatureRequestAdmin(admin.ModelAdmin):
    list_display = ("title", "customer")
    list_filter = ("customer",)
    search_fields = (
        "title",
        "description",
        "import_token",
    )


class ThemeAdmin(admin.ModelAdmin):
    list_display = ("title", "customer")
    list_filter = ("customer",)


admin.site.register(FeedbackImporter, FeedbackImporterAdmin)
admin.site.register(
    CustomerFeedbackImporterSettings, CustomerFeedbackImporterSettingsAdmin
)
admin.site.register(Feedback, FeedbackAdmin)
admin.site.register(FeatureRequest, FeatureRequestAdmin)
admin.site.register(Theme, ThemeAdmin)
