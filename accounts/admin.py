from collections import OrderedDict

from django import forms
from django.contrib import admin
from django.contrib.auth import login
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import AdminPasswordChangeForm, ReadOnlyPasswordHashField
from django.shortcuts import redirect
from django.utils.translation import gettext_lazy as _

from common.admin_mixins import CSVExportMixin

from .models import (
    Customer,
    Discount,
    FeatureRequestNotificationSettings,
    FeedbackTriageSettings,
    OnboardingTask,
    StatusEmailSettings,
    Subscription,
    User,
)


class UserCreationForm(forms.ModelForm):
    """A form for creating new users. Includes all the required
    fields, plus a repeated password."""

    password1 = forms.CharField(label="Password", widget=forms.PasswordInput)
    password2 = forms.CharField(
        label="Password confirmation", widget=forms.PasswordInput
    )

    class Meta:
        model = User
        fields = ("email", "customer", "job")

    def clean_password2(self):
        # Check that the two password entries match
        password1 = self.cleaned_data.get("password1")
        password2 = self.cleaned_data.get("password2")
        if password1 and password2 and password1 != password2:
            raise forms.ValidationError("Passwords don't match")
        return password2

    def save(self, commit=True):
        # Save the provided password in hashed format
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


class UserChangeForm(forms.ModelForm):
    """A form for updating users. Includes all the fields on
    the user, but replaces the password field with admin's
    password hash display field.
    """

    password = ReadOnlyPasswordHashField(
        label=_("Password"),
        help_text=_(
            "Raw passwords are not stored, so there is no way to see this "
            "user's password, but you can change the password using "
            '<a href="{}">this form</a>.'
        ),
    )

    class Meta:
        model = User
        fields = ("email", "password", "is_active", "is_admin", "is_staff")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        password = self.fields.get("password")
        if password:
            password.help_text = password.help_text.format("../password/")
        user_permissions = self.fields.get("user_permissions")
        if user_permissions:
            user_permissions.queryset = user_permissions.queryset.select_related(
                "content_type"
            )

    def clean_password(self):
        # Regardless of what the user provides, return the initial value.
        # This is done here, rather than on the field, because the
        # field does not have access to the initial value
        return self.initial["password"]


class OnboardingTaskChangeForm(forms.ModelForm):
    class Meta:
        model = OnboardingTask
        fields = (
            "customer",
            "task_type",
            "completed",
        )


class CustomerAdmin(admin.ModelAdmin):
    list_display = ("name", "whitelisted_domain", "onboarding_percent_complete")


class SubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        "customer",
        "plan",
        "next_mrr_payment",
        "card_on_file",
        "is_per_seat_plan",
        "trial_end_date",
    )
    list_filter = (
        "customer",
        "card_on_file",
    )
    search_fields = ("customer__user__email", "customer__name")


def spoof_login(modeladmin, request, queryset):
    assert request.user.is_superuser
    user = queryset.first()
    if user:
        login(request, user)
        return redirect("feedback-list")


spoof_login.short_description = "Login as selected user"


class UserAdmin(CSVExportMixin, BaseUserAdmin):
    # The forms to add and change user instances
    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm

    export_fields = OrderedDict(
        (
            ("id", None),
            ("customer.name", None),
            ("last_login", None),
            ("email", None),
            ("first_name", None),
            ("last_name", None),
            ("role", None),
            ("customer.subscription.status", None),
            ("customer.subscription.card_on_file", None),
            ("date_joined", None),
            ("is_superuser", None),
            ("is_admin", None),
            ("is_staff", None),
            ("is_active", None),
        )
    )

    # The fields to be used in displaying the User model.
    # These override the definitions on the base UserAdmin
    # that reference specific fields on auth.User.
    list_display = (
        "email",
        "first_name",
        "last_name",
        "role",
        "is_staff",
        "create_feedback_email",
        "customer",
    )
    list_filter = (
        "date_joined",
        "customer__subscription__card_on_file",
        "is_superuser",
        "role",
        "customer",
    )
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "email",
                    "first_name",
                    "last_name",
                    "password",
                    "date_joined",
                    "last_login",
                )
            },
        ),
        (
            "Custom info",
            {"fields": ("customer", "role", "job", "create_feedback_email",)},
        ),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_admin",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
    )

    # add_fieldsets is not a standard ModelAdmin attribute. UserAdmin
    # overrides get_fieldsets to use this attribute when creating a user.
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "customer", "job", "password1", "password2"),
            },
        ),
    )
    search_fields = ("email",)
    ordering = ("email",)
    filter_horizontal = (
        "groups",
        "user_permissions",
    )
    actions = [spoof_login]


class StatusEmailSettingsAdmin(admin.ModelAdmin):
    list_display = ("customer", "user", "notify", "last_notified")
    list_filter = ("customer", "notify")
    search_fields = ("user__email",)


class FeatureRequestNotificationSettingsAdmin(admin.ModelAdmin):
    list_display = (
        "customer",
        "reply_to",
        "bcc",
    )
    list_filter = ("customer",)


class FeedbackTriageSettingsAdmin(admin.ModelAdmin):
    list_display = (
        "customer",
        "skip_inbox_if_feature_request_set",
    )
    list_filter = ("customer",)


class OnboardingTaskAdmin(admin.ModelAdmin):
    form = OnboardingTaskChangeForm
    list_display = ("customer",)


class DiscountAdmin(CSVExportMixin, admin.ModelAdmin):
    list_display = (
        "code",
        "promo_text",
        "subscription_id",
        "plan",
    )

    export_fields = OrderedDict((("code", None),))


admin.site.register(Customer, CustomerAdmin)
admin.site.register(User, UserAdmin)
admin.site.register(Subscription, SubscriptionAdmin)
admin.site.register(StatusEmailSettings, StatusEmailSettingsAdmin)
admin.site.register(
    FeatureRequestNotificationSettings, FeatureRequestNotificationSettingsAdmin
)
admin.site.register(FeedbackTriageSettings, FeedbackTriageSettingsAdmin)
admin.site.register(OnboardingTask, OnboardingTaskAdmin)
admin.site.register(Discount, DiscountAdmin)
