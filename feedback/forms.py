from urllib.parse import quote

from crispy_forms.helper import FormHelper
from crispy_forms.layout import HTML, ButtonHolder, Fieldset, Layout, Submit
from dal import autocomplete
from django import forms
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.contrib.staticfiles.templatetags.staticfiles import static
from django.core import validators
from django.core.exceptions import ValidationError
from django.core.mail import EmailMessage, EmailMultiAlternatives, mail_admins
from django.db.models import Q
from django.template import loader
from django.template.defaultfilters import truncatechars
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.html import mark_safe
from django.utils.text import format_lazy
from ratelimit.core import get_usage

from accounts.models import FeatureRequestNotificationSettings, OnboardingTask
from appaccounts.models import AppCompany, AppUser, FilterableAttribute
from common.utils import email_list_from_string
from internal_analytics import tracking
from sharedwidgets.fields import InputAndChoiceField
from sharedwidgets.widgets import MarkdownWidget, NoRenderWidget

from .models import FeatureRequest, Feedback, FeedbackFromRule, FeedbackTemplate, Theme


def get_plan_choices(customer):
    return [(None, "All")] + [
        (p, p)
        for p in AppCompany.objects.filter(customer=customer)
        .exclude(plan="")
        .values_list("plan", flat=True)
        .distinct()
    ]


def get_feedback_type_choices():
    return [(None, "All")] + list(Feedback.TYPE_CHOICES)


def get_theme_choices(customer):
    return [(None, "Any"), (-1, "None")] + [
        (t.id, t.title) for t in Theme.objects.filter(customer=customer)
    ]


def get_state_choices():
    return [(None, "All"), ("ALL_ACTIVE", "All Active")] + list(
        FeatureRequest.STATE_CHOICES
    )


def get_priority_choices():
    return [(None, "All"), ("NOT_SET", "Not Set")] + list(
        FeatureRequest.PRIORITY_CHOICES
    )


def get_effort_choices():
    return [(None, "All"), ("NOT_SET", "Not Set")] + list(FeatureRequest.EFFORT_CHOICES)


class FeedbackCreateForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request")
        super().__init__(*args, **kwargs)
        if self.request.GET.get("onboarding", "no") == "yes":
            try:
                default_user = AppUser.objects.get(
                    customer=self.request.user.customer, email=self.request.user.email
                )
                self.fields["user"].initial = default_user.id
                self.fields["user"].widget = forms.HiddenInput()
            except AppUser.DoesNotExist:
                pass

            self.fields["feedback_type"].initial = Feedback.INTERNAL
            self.fields["feedback_type"].widget = forms.HiddenInput()
            self.fields.pop("feature_request")
            self.fields.pop("themes")

    def save(self, commit=True):
        feedback = super(FeedbackCreateForm, self).save(commit=False)
        if commit:
            feedback.created_by = self.request.user
            feedback.customer = self.request.user.customer
            feedback.state = self.get_state()

            # If this is created by splitting off another piece of feedback,
            # we stuff some data from the original into this new piece
            split_feedback_id = self.request.GET.get("split_feedback_id", None)
            if split_feedback_id:
                try:
                    orig_feedback = Feedback.objects.filter(
                        customer=self.request.user.customer
                    ).get(id=split_feedback_id)
                    feedback.source = orig_feedback.source
                    feedback.source_url = orig_feedback.source_url
                    feedback.source_username = orig_feedback.source_username
                    feedback.source_created = orig_feedback.source_created
                    feedback.source_updated = orig_feedback.source_updated

                except Feedback.DoesNotExist:
                    pass

            feedback.save(override_auto_triage=True)
            self.save_m2m()

            if feedback.state == Feedback.ARCHIVED:
                OnboardingTask.objects.filter(
                    customer=feedback.customer,
                    task_type=OnboardingTask.TASK_TRIAGE_FEEDBACK,
                ).update(completed=True, updated=timezone.now())

            tracking.feedback_created(
                self.request.user.id,
                self.request.user.customer,
                feedback,
                tracking.EVENT_SOURCE_WEB_APP,
            )
        return feedback

    def get_state(self):
        if "save-to-inbox" in self.data:
            action = Feedback.ACTIVE
        elif "save-and-archive" in self.data:
            action = Feedback.ARCHIVED
        else:
            raise Exception(f"No valid action found. {self.data}")
        return action

    class Meta:
        model = Feedback
        fields = [
            "problem",
            "user",
            "feedback_type",
            "feature_request",
            "themes",
        ]
        labels = {
            "problem": "Customer Problem",
            "user": "Person",
            "feedback_type": "Feedback from",
            "themes": "Tags",
        }
        widgets = {
            "problem": MarkdownWidget(
                attrs={
                    "tabindex": "1",
                    "placeholder": "The problem this customer has is (include verbatim if possible)...",
                    "rows": "5",
                    "autofocus": True,
                }
            ),
            "user": autocomplete.ModelSelect2(
                url="app-user-autocomplete-no-create",
                attrs={
                    "tabindex": "2",
                    "allowClear": True,
                    "data-placeholder": "Select who provided the feedback...",
                    "delay": 250,
                    "minimumInputLength": 1,
                    "data-html": "true",
                },
            ),
            "feedback_type": forms.Select(
                attrs={
                    "tabindex": "3",
                    "data-toggle": "tooltip",
                    "data-placement": "right",
                    "data-original-title": "You can filter all feedback or feature requests by this field later. Required.",
                    "data-trigger": "focus",
                }
            ),
            "feature_request": autocomplete.ModelSelect2(
                url="feature-request-autocomplete",
                attrs={
                    "tabindex": "4",
                    "allowClear": True,
                    "data-placeholder": "Attach to new or existing feature request...",
                    "delay": 50,
                    "minimumInputLength": 1,
                    "data-toggle": "tooltip",
                    "data-placement": "right",
                    "data-original-title": "Choose or create a feature that describes a solution to this problem.  Optional.",
                    "data-trigger": "focus",
                    "data-html": "true",
                },
            ),
            "themes": autocomplete.ModelSelect2Multiple(
                url="theme-autocomplete",
                attrs={
                    "tabindex": "5",
                    "data-toggle": "tooltip",
                    "data-placement": "right",
                    "data-original-title": "Tags are a way to group similar feedback. Optional.",
                    "data-trigger": "focus",
                    "allowClear": True,
                    "data-placeholder": "Add Tags...",
                    "delay": 50,
                    "minimumInputLength": 1,
                    "data-html": "true",
                },
            ),
        }
        help_texts = {
            "feature_request": "Use one or two words, like 'Reporting 2.0' or 'Better Auth'. Include 'tags:tag1,tag2' at the end of your search to filter the list by tags",
            "themes": "Examples might be 'Q3 Survey' or 'From Skype'",
        }


class FeedbackEditForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request")
        super().__init__(*args, **kwargs)

    class Meta:
        model = Feedback
        fields = [
            "problem",
            "user",
            "feedback_type",
            "feature_request",
            "themes",
        ]
        labels = {
            "problem": "Customer Problem",
            "user": "Person",
            "feedback_type": "Feedback from",
            "themes": "Tags",
        }
        widgets = {
            "problem": MarkdownWidget(
                attrs={
                    "tabindex": "1",
                    "placeholder": "The problem this customer has is (include verbatim if possible)... ",
                    "rows": "5",
                    "autofocus": True,
                }
            ),
            "user": autocomplete.ModelSelect2(
                url="app-user-autocomplete-no-create",
                attrs={
                    "tabindex": "2",
                    "allowClear": True,
                    "data-placeholder": "Select who provided the feedback...",
                    "delay": 250,
                    "minimumInputLength": 1,
                    "data-toggle": "tooltip",
                    "data-placement": "bottom",
                    "data-trigger": "focus",
                    "data-html": "true",
                },
            ),
            "feedback_type": forms.Select(
                attrs={
                    "tabindex": "3",
                    "data-toggle": "tooltip",
                    "data-placement": "right",
                    "data-original-title": "You can filter all feedback or feature requests by this field later. Required.",
                    "data-trigger": "focus",
                }
            ),
            "feature_request": autocomplete.ModelSelect2(
                url="feature-request-autocomplete",
                attrs={
                    "tabindex": "4",
                    "allowClear": True,
                    "data-placeholder": "Attach to new or existing feature request...",
                    "delay": 50,
                    "minimumInputLength": 1,
                    "data-toggle": "tooltip",
                    "data-placement": "auto",
                    "data-original-title": "Choose or create a feature request that describes a solution to this problem.  Optional.",
                    "data-trigger": "focus",
                    "data-html": "true",
                },
            ),
            "themes": autocomplete.ModelSelect2Multiple(
                url="theme-autocomplete",
                attrs={
                    "tabindex": "5",
                    "data-toggle": "tooltip",
                    "data-placement": "right",
                    "data-original-title": "Tags are a way to group similar feedback. Optional.",
                    "data-trigger": "focus",
                    "allowClear": True,
                    "data-placeholder": "Add Tags...",
                    "delay": 50,
                    "minimumInputLength": 1,
                    "data-html": "true",
                },
            ),
        }
        help_texts = {
            "feature_request": "Use one or two words, like 'Reporting 2.0' or 'Better Auth'. Include 'tags:tag1,tag2' at the end of your search to filter the list by tags.",
            "themes": "Examples might be 'Q3 Survey' or 'From Skype'",
        }


class FeedbackTriageEditForm(forms.ModelForm):
    SNOOZE_FOR_CHOICES = (
        (1, "1 day"),
        (3, "3 days"),
        (7, "7 days"),
        (14, "14 days"),
    )

    snooze_for = forms.ChoiceField(
        choices=SNOOZE_FOR_CHOICES,
        widget=NoRenderWidget,
        validators=[validators.integer_validator],
        required=False,
    )

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request")
        super().__init__(*args, **kwargs)
        if self.request.GET.get("onboarding", "no") == "yes":
            self.fields["feature_request"].help_text = ""
            if self.instance.feedback_type:
                self.fields["feedback_type"].widget = forms.HiddenInput()
            self.fields.pop("themes")
            self.fields["feature_request"].widget.attrs["required"] = True

    def save(self, commit=True):
        feedback = super().save(commit=False)

        if self.cleaned_data["snooze_for"]:
            feedback.snooze_till = timezone.now() + timezone.timedelta(
                days=int(self.cleaned_data["snooze_for"])
            )

        if commit:
            feedback.save()
            self.save_m2m()

            if feedback.state == Feedback.ARCHIVED:
                OnboardingTask.objects.filter(
                    customer=feedback.customer,
                    task_type=OnboardingTask.TASK_TRIAGE_FEEDBACK,
                ).update(completed=True, updated=timezone.now())
        return feedback

    class Meta:
        model = Feedback
        fields = ["feedback_type", "feature_request", "themes"]
        widgets = {
            "feedback_type": forms.Select(
                attrs={
                    "tabindex": "1",
                    "data-toggle": "tooltip",
                    "data-placement": "right",
                    "data-original-title": "You can filter all feedback or feature requests by this field later. Required.",
                    "data-trigger": "focus",
                }
            ),
            "feature_request": autocomplete.ModelSelect2(
                url="feature-request-autocomplete",
                attrs={
                    "tabindex": "2",
                    "allowClear": True,
                    "data-placeholder": "Link to new or existing feature request...",
                    "delay": 50,
                    "minimumInputLength": 1,
                    "data-toggle": "tooltip",
                    "data-placement": "right",
                    "data-original-title": "Choose or create a feature request that describes a solution to this problem.",
                    "data-trigger": "focus",
                    "data-html": "true",
                },
            ),
            "themes": autocomplete.ModelSelect2Multiple(
                url="theme-autocomplete",
                attrs={
                    "tabindex": "3",
                    "data-toggle": "tooltip",
                    "data-placement": "right",
                    "data-original-title": "Tags are a way to group similar feedback. Optional",
                    "data-trigger": "focus",
                    "allowClear": True,
                    "data-placeholder": "Add Tags...",
                    "delay": 250,
                    "minimumInputLength": 1,
                    "data-html": "true",
                },
            ),
        }

        labels = {
            "feedback_type": "feedback From",
            "themes": "Tags",
        }

        help_texts = {
            "feature_request": mark_safe(
                "Use one or two words, like 'Reporting 2.0' or 'Better Auth'. Include 'tags:tag1,tag2' at the end of your search to filter the list by tags.<br>Create a new Feature Request by typing in the dropdown or <a href='#' id='create_fr_link' name='create-fr' value='Add FR' class='js-create-feature-request'>create one with all details here</a>."
            ),
            "themes": "Examples might be 'Q3 Survey' or 'From Skype'",
        }


class FeatureRequestEditForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request")
        super().__init__(*args, **kwargs)

    def clean_title(self):
        title_exists = (
            FeatureRequest.objects.filter(
                customer=self.request.user.customer, title=self.cleaned_data["title"]
            )
            .exclude(id=self.instance.id)
            .exists()
        )
        if title_exists:
            raise ValidationError("Feature with that title already exists")
        return self.cleaned_data["title"]

    def save(self, commit=True):
        fr = super(FeatureRequestEditForm, self).save(commit=False)
        if commit:
            fr.save()
            self.save_m2m()
        return fr

    class Meta:
        model = FeatureRequest
        fields = [
            "title",
            "description",
            "state",
            "priority",
            "effort",
            "themes",
        ]
        labels = {
            "state": "Status",
            "themes": "Tags",
        }
        widgets = {
            "customer": forms.HiddenInput(),
            "title": forms.TextInput(
                attrs={
                    "placeholder": "Keep it short and sweet",
                    "tabindex": "1",
                    "data-toggle": "tooltip",
                    "data-placement": "right",
                    "data-original-title": "Usually the one or two words you use to refer to this internally. Required.",
                    "data-trigger": "focus",
                    "autofocus": "autofocus",
                }
            ),
            "description": MarkdownWidget(
                attrs={
                    "placeholder": "A brief description of the feature...",
                    "rows": "5",
                    "tabindex": "2",
                }
            ),
            "state": forms.Select(
                attrs={
                    "tabindex": "3",
                    "data-toggle": "tooltip",
                    "data-placement": "right",
                    "data-original-title": "What's the status of this feature? Required.",
                    "data-trigger": "focus",
                }
            ),
            "priority": forms.Select(
                attrs={
                    "tabindex": "4",
                    "data-toggle": "tooltip",
                    "data-placement": "right",
                    "data-original-title": "Set a priority so you can filter by it (in combination with other fields) later. Optional.",
                    "data-trigger": "focus",
                }
            ),
            "effort": forms.Select(
                attrs={
                    "tabindex": "5",
                    "data-toggle": "tooltip",
                    "data-placement": "right",
                    "data-original-title": "How expensive will this be to build? Optional.",
                    "data-trigger": "focus",
                }
            ),
            "themes": autocomplete.ModelSelect2Multiple(
                url="theme-autocomplete",
                attrs={
                    "tabindex": "6",
                    "data-toggle": "tooltip",
                    "data-placement": "right",
                    "data-original-title": "Tags are a way to group similar features. Optional",
                    "data-trigger": "focus",
                    "allowClear": True,
                    "data-placeholder": "Add tags...",
                    "delay": 250,
                    "minimumInputLength": 1,
                    "data-html": "true",
                },
            ),
        }
        help_texts = {
            "themes": "Examples might be 'Lower Churn', 'Auth Improvements', or 'Pricing Feedback'",
        }


class FeatureRequestCreateForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request")
        super().__init__(*args, **kwargs)

        self.helper = FormHelper()
        self.helper.layout = Layout(
            Fieldset("", "title",),
            HTML(
                """
            <a id="toggle-advanced" href="#">Advanced</a>
            """
            ),
            Fieldset(
                "",
                "description",
                "state",
                "priority",
                "effort",
                "themes",
                style="display: none;",
                id="advanced-fieldset",
            ),
            ButtonHolder(
                Submit("submit", "Save New Feature", css_class="btn btn-primary"),
                HTML(
                    """
                or <a href="{{return}}">cancel</a>
                """
                ),
                css_class="pt-4",
            ),
        )

    def clean_title(self):
        title_exists = FeatureRequest.objects.filter(
            customer=self.request.user.customer, title=self.cleaned_data["title"]
        ).exists()
        if title_exists:
            raise ValidationError("Feature with that title already exists")
        return self.cleaned_data["title"]

    def save(self, commit=True):
        fr = super(FeatureRequestCreateForm, self).save(commit=False)
        if commit:
            fr.customer = self.request.user.customer
            fr.save()
            self.save_m2m()
        return fr

    class Meta:
        model = FeatureRequest
        fields = ["title", "description", "state", "priority", "effort", "themes"]
        labels = {
            "title": "Feature Request Title",
            "state": "Status",
            "themes": "Tags",
        }
        widgets = {
            "customer": forms.HiddenInput(),
            "title": forms.TextInput(
                attrs={
                    "placeholder": "Keep it short and sweet",
                    "tabindex": "1",
                    "data-toggle": "tooltip",
                    "data-placement": "right",
                    "data-original-title": "Usually the one or two words you use to refer to this internally. Required.",
                    "data-trigger": "focus",
                    "autofocus": "autofocus",
                }
            ),
            "description": MarkdownWidget(
                attrs={
                    "placeholder": "A brief description of the feature...",
                    "rows": "5",
                    "tabindex": "2",
                }
            ),
            "state": forms.Select(
                attrs={
                    "tabindex": "3",
                    "data-toggle": "tooltip",
                    "data-placement": "right",
                    "data-original-title": "What's the status of this feature? Required.",
                    "data-trigger": "focus",
                }
            ),
            "priority": forms.Select(
                attrs={
                    "tabindex": "4",
                    "data-toggle": "tooltip",
                    "data-placement": "right",
                    "data-original-title": "Set a priority so you can filter by it (in combination with other fields) later. Optional.",
                    "data-trigger": "focus",
                }
            ),
            "effort": forms.Select(
                attrs={
                    "tabindex": "5",
                    "data-toggle": "tooltip",
                    "data-placement": "right",
                    "data-original-title": "How expensive will this be to build? Optional.",
                    "data-trigger": "focus",
                }
            ),
            "themes": autocomplete.ModelSelect2Multiple(
                url="theme-autocomplete",
                attrs={
                    "tabindex": "6",
                    "data-toggle": "tooltip",
                    "data-placement": "right",
                    "data-original-title": "Tags are a way to group similar features. Optional",
                    "data-trigger": "focus",
                    "allowClear": True,
                    "data-placeholder": "Add tags...",
                    "delay": 250,
                    "minimumInputLength": 1,
                    "data-html": "true",
                },
            ),
        }
        help_texts = {
            "themes": "Examples might be 'Lower Churn', 'Auth Improvements', or 'Pricing Feedback'",
        }


class FeatureRequestMergeForm(forms.Form):
    feature_request_to_keep = forms.IntegerField(
        required=True, widget=forms.HiddenInput()
    )
    feature_request_to_merge = autocomplete.Select2ListChoiceField(
        required=False,
        widget=autocomplete.Select2(
            url="feature-request-autocomplete-no-create",
            attrs={
                "allowClear": True,
                "delay": 50,
                "minimumInputLength": 1,
                "data-html": "true",
                "data-placeholder": "Choose a feature...",
            },
        ),
    )

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request")

        super().__init__(*args, **kwargs)

        to_merge = self.request.POST.get("feature_request_to_merge", None)
        if to_merge:
            fr_to_merge = FeatureRequest.objects.get(
                customer=self.request.user.customer, id=to_merge,
            )

            self.fields["feature_request_to_merge"].choices = [
                (to_merge, fr_to_merge.title,),
            ]

    def clean(self):
        cleaned_data = super().clean()
        if int(self.cleaned_data["feature_request_to_keep"]) == int(
            self.cleaned_data["feature_request_to_merge"]
        ):
            raise forms.ValidationError("You can't merge a feature with itself.")
        return cleaned_data

    def save(self, commit=True):
        try:
            fr_to_keep = FeatureRequest.objects.get(
                customer=self.request.user.customer,
                id=self.cleaned_data["feature_request_to_keep"],
            )

            fr_to_merge = FeatureRequest.objects.get(
                customer=self.request.user.customer,
                id=self.cleaned_data["feature_request_to_merge"],
            )

            fr_to_merge.feedback_set.all().update(feature_request=fr_to_keep)

            to_keep_title = truncatechars(fr_to_keep.title, 100)
            to_merge_title = truncatechars(fr_to_merge.title, 100)

            fr_to_merge.delete()

            messages.success(
                self.request,
                f"'{to_keep_title}' and '{to_merge_title}' have been merged.",
            )
        except FeatureRequest.DoesNotExist:
            pass


class BaseListFilterMixin:
    def get_filter(self, field_name, keyword_or_callable):
        if callable(keyword_or_callable):
            keyword, value = keyword_or_callable(self.cleaned_data[field_name])
        else:
            keyword = keyword_or_callable
            value = self.cleaned_data[field_name]
        return (keyword, value)

    def get_mapping_list(self):
        raise NotImplementedError

    def get_queryset_filter_args(self):
        args = {}
        for field_name, filter_name in self.get_mapping_list():
            if self.cleaned_data[field_name]:
                keyword, value = self.get_filter(field_name, filter_name)
                args[keyword] = value
        return args


class FilterForm(forms.Form):
    OPERATION_PREFIX = "__op__"
    OPERATION_CHOICES = (
        (f"{OPERATION_PREFIX}gte", ">="),
        (f"{OPERATION_PREFIX}lte", "<="),
    )

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request")
        super().__init__(*args, **kwargs)
        for filterable_attribute in self.get_visiable_filterable_attributes():
            if filterable_attribute.attribute_type in (
                FilterableAttribute.ATTRIBUTE_TYPE_FLOAT,
                FilterableAttribute.ATTRIBUTE_TYPE_INT,
            ):
                # Numerics get the fancy two part select and textbox widget
                self.fields[filterable_attribute.name] = InputAndChoiceField(
                    required=False, choices=FilterForm.OPERATION_CHOICES
                )
                self.fields[
                    filterable_attribute.name
                ].choices = FilterForm.OPERATION_CHOICES
                self.fields[
                    filterable_attribute.name
                ].label = f"{filterable_attribute.friendly_name} ({filterable_attribute.get_related_object_type_display()})"
                self.initial[filterable_attribute.name] = self.fields[
                    filterable_attribute.name
                ].choices[0][0]
            else:
                # Everyone else just gets a select
                self.fields[filterable_attribute.name] = forms.ChoiceField(
                    required=False
                )
                self.fields[
                    filterable_attribute.name
                ].choices = filterable_attribute.get_choices()
                self.fields[
                    filterable_attribute.name
                ].label = f"{filterable_attribute.friendly_name} ({filterable_attribute.get_related_object_type_display()})"
                self.initial[filterable_attribute.name] = self.fields[
                    filterable_attribute.name
                ].choices[0][0]

        for visible in self.visible_fields():
            visible.field.widget.attrs["class"] = "form-control"

        default_user_id = self.request.GET.get("user", None)
        if default_user_id:
            try:
                default_user = AppUser.objects.get(
                    customer=self.request.user.customer, id=default_user_id
                )
                self.fields["user"].choices = [
                    (
                        default_user.id,
                        default_user.get_friendly_name_email_and_company(),
                    ),
                ]
                self.fields["user"].initial = default_user.id
            except AppUser.DoesNotExist:
                pass

        default_company_id = self.request.GET.get("company", None)
        if default_company_id:
            try:
                default_company = AppCompany.objects.get(
                    customer=self.request.user.customer, id=default_company_id
                )
                self.fields["company"].choices = [
                    (default_company.id, default_company.name),
                ]
                self.fields["company"].initial = default_company.id
            except AppCompany.DoesNotExist:
                pass

    def get_base_queryset(self):
        raise NotImplementedError

    def get_filter(
        self, form_field_name, orm_lookup_or_callable, coercion_fuction=None
    ):
        if callable(orm_lookup_or_callable):
            orm_lookup, value = orm_lookup_or_callable(
                self.cleaned_data[form_field_name]
            )
        elif self.is_numeric_lookup(form_field_name):
            orm_lookup, value = self.get_numeric_lookup_and_value(
                form_field_name, orm_lookup_or_callable, coercion_fuction
            )
        else:
            orm_lookup = orm_lookup_or_callable
            value = self.cleaned_data[form_field_name]
            if coercion_fuction:
                value = coercion_fuction(value)
        return (orm_lookup, value)

    def is_numeric_lookup(self, form_field_name):
        # It's a special numeric look up if it looks like __op__gte~100
        value = self.cleaned_data[form_field_name]
        return type(value) is str and value.startswith(FilterForm.OPERATION_PREFIX)

    def get_numeric_lookup_and_value(
        self, form_field_name, orm_lookup, coercion_fuction=None
    ):
        # Numerics are special. We are using a MultiValueField were the value that comes
        # back look like __op__gte~100.
        # We need to crack that and build the right lookup.
        # Because empty lookups look like '__op__gte~'
        # We return a None value for orm_lookup in those
        # cases so we can skip it when we buld the filter query.
        value = self.cleaned_data[form_field_name]
        parts = value.split("~", 1)
        value = parts[1]
        if value:
            extra_lookup = parts[0].replace(FilterForm.OPERATION_PREFIX, "")
            orm_lookup = f"{orm_lookup}__{extra_lookup}"
            if coercion_fuction:
                try:
                    value = coercion_fuction(value)
                except ValueError:
                    # BUGBUG: if the user puts in bad data we should probably
                    # show the error. Right now we just silently swallow it.
                    orm_lookup = None
                    value = None
        else:
            orm_lookup = None
        return (orm_lookup, value)

    def get_visiable_filterable_attributes(self):
        return FilterableAttribute.objects.filter(
            customer=self.request.user.customer, show_in_filters=True
        )

    def get_filterable_attribute_lookup_base(self):
        # Features are feedback__user__xxx and Feedback is just user__xxx
        return ""

    def get_base_filters(self):
        raise NotImplementedError

    def get_search_vector(self):
        raise NotImplementedError

    def get_search_fields(self):
        raise NotImplementedError

    def get_theme_filter(self, value):
        if int(value) == -1:
            lookup = "themes"
            value = None
        else:
            lookup = "themes"
            value = value
        return lookup, value

    def get_queryset_filter_args(self):
        args = {}
        filters = list(self.get_base_filters())

        for fa in self.get_visiable_filterable_attributes():
            if fa.related_object_type == FilterableAttribute.OBJECT_TYPE_APPCOMPANY:
                fieldname = f"user__company__filterable_attributes__{fa.name}"
            else:
                fieldname = f"user__filterable_attributes__{fa.name}"

            lookup_base = self.get_filterable_attribute_lookup_base()
            if lookup_base:
                fieldname = f"{lookup_base}{fieldname}"
            filters.append((fa.name, fieldname, fa.get_coercion_fuction))

        for form_field_name, orm_lookup_or_callable, coercion_fuction in filters:
            print(self.cleaned_data)
            if self.cleaned_data[form_field_name]:
                keyword, value = self.get_filter(
                    form_field_name, orm_lookup_or_callable, coercion_fuction
                )

                # For new numerics we return None for keyword (lookup) if it should
                # be skipped.
                if keyword:
                    args[keyword] = value
        print(args)
        return args

    def get_filtered_queryset(self, request):
        qs = self.get_base_queryset()
        stock_filters = self.get_queryset_filter_args()
        print(f"stock_filters {stock_filters}")
        qs = qs.filter(**stock_filters)

        # This is quick and dirty. When we get a lot of data in the feedback
        # table this probably isn't going to perform all that well. What we
        # need to do then is:
        # 1. Create a 'search' field on Feedback.
        # 2. Index it with a GIN index.
        # 3. Populate it either on save() or in a signal
        # 4. Back fill it with a one time job.
        # 5. Change the code below to use it.
        # See here for details:
        # http://blog.lotech.org/postgres-full-text-search-with-django.html
        #
        # It might also be interesting to create a table that has all of our
        # unique words that are found in key fields e.g. FR.title, FR.description
        # and then use them in conjunction with TrigramSimilarity. Basically
        # we'd "extend" the users search terms which words that were "similar"
        # to what they typed and see if the similar words are in the vector.
        # See:
        # http://rachbelaid.com/postgres-full-text-search-is-good-enough/
        # https://www.compose.com/articles/indexing-for-full-text-search-in-postgresql/
        if self.cleaned_data["search"]:
            vector = self.get_search_vector()
            query = SearchQuery(self.cleaned_data["search"], config="english")

            # For searching we are doing two things:
            # 1. Postgres fulltext search to get stemming etc.
            # 2. Simple icontains so that partial word matches also work.
            # This means we need to build up a fancy dynamic OR using
            # Q expression. That is what this next section does.
            search_filter = Q(search=query)
            for search_field in self.get_search_fields():
                kwargs = {f"{search_field}__icontains": self.cleaned_data["search"]}
                search_filter |= Q(**kwargs)
            qs = (
                qs.annotate(search=vector, rank=SearchRank(vector, query))
                .filter(search_filter)
                .order_by("-rank")
            )
        else:
            qs = qs.order_by("-created")
        return qs


class FeedbackListFilterForm(FilterForm):
    search = forms.CharField(
        required=False, widget=forms.TextInput(attrs={"placeholder": "Search Feedback"})
    )
    user = autocomplete.Select2ListChoiceField(
        required=False,
        widget=autocomplete.Select2(
            url="app-user-autocomplete-no-create",
            attrs={
                "allowClear": True,
                "delay": 50,
                "minimumInputLength": 1,
                "data-html": "true",
            },
        ),
    )
    company = autocomplete.Select2ListChoiceField(
        required=False,
        widget=autocomplete.Select2(
            url="app-company-autocomplete-no-create",
            attrs={
                "allowClear": True,
                "delay": 50,
                "minimumInputLength": 1,
                "data-html": "true",
            },
        ),
    )
    feedback_type = forms.ChoiceField(choices=get_feedback_type_choices, required=False)
    theme = forms.ChoiceField(
        required=False,
        label="Tag",
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    feedback_date_range = forms.CharField(
        required=False,
        label="Feedback received between",
        widget=forms.TextInput(
            attrs={"placeholder": "Choose dates", "autocomplete": "off"}
        ),
    )
    feedback_start_date = forms.DateField(required=False, widget=forms.HiddenInput())
    feedback_end_date = forms.DateField(required=False, widget=forms.HiddenInput())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["theme"].choices = get_theme_choices(self.request.user.customer)

    def get_base_queryset(self):
        feedback_qs = (
            Feedback.objects.select_related(
                "customer", "feature_request", "user", "user__company"
            )
            .prefetch_related("themes")
            .filter(customer=self.request.user.customer)
        )
        return feedback_qs

    def get_search_vector(self):
        return SearchVector(*self.get_search_fields(),)

    def get_search_fields(self):
        return ("problem",)

    def get_base_filters(self):
        return (
            ("user", "user", None),
            ("company", "user__company", None),
            ("feedback_type", "feedback_type", None),
            ("theme", self.get_theme_filter, None),
            ("feedback_start_date", "created__gte", None),
            ("feedback_end_date", "created__lte", None),
        )


class FeatureListFilterForm(FilterForm):
    search = forms.CharField(
        required=False, widget=forms.TextInput(attrs={"placeholder": "Search Features"})
    )
    user = autocomplete.Select2ListChoiceField(
        required=False,
        widget=autocomplete.Select2(
            url="app-user-autocomplete-no-create",
            attrs={
                "allowClear": True,
                "delay": 50,
                "minimumInputLength": 1,
                "data-html": "true",
            },
        ),
    )
    company = autocomplete.Select2ListChoiceField(
        required=False,
        widget=autocomplete.Select2(
            url="app-company-autocomplete-no-create",
            attrs={
                "allowClear": True,
                "delay": 50,
                "minimumInputLength": 1,
                "data-html": "true",
            },
        ),
    )
    feedback_type = forms.ChoiceField(
        choices=get_feedback_type_choices,
        required=False,
        label="Feedback From",
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    state = forms.ChoiceField(
        choices=get_state_choices,
        required=False,
        label="Status",
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    theme = forms.ChoiceField(
        required=False,
        label="Tag",
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    priority = forms.ChoiceField(
        choices=get_priority_choices,
        required=False,
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    effort = forms.ChoiceField(
        choices=get_effort_choices,
        required=False,
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    feedback_date_range = forms.CharField(
        required=False,
        label="Feedback received between",
        widget=forms.TextInput(
            attrs={"placeholder": "Choose dates", "autocomplete": "off"}
        ),
    )
    # BUGBUG: Both filter lists are treating dates as timezone free. We should let user set
    # their timezone and do the conversion to utc before querying.
    feedback_start_date = forms.DateField(required=False, widget=forms.HiddenInput())
    feedback_end_date = forms.DateField(required=False, widget=forms.HiddenInput())

    # BUGBUG: Both filter lists are treating dates as timezone free. We should let user set
    # their timezone and do the conversion to utc before querying.
    shipped_date_range = forms.CharField(
        required=False,
        label="Feature shipped between",
        widget=forms.TextInput(
            attrs={"placeholder": "Choose dates", "autocomplete": "off"}
        ),
        help_text="Change Status to 'All' or 'Shipped'",
    )
    shipped_start_date = forms.DateField(required=False, widget=forms.HiddenInput())
    shipped_end_date = forms.DateField(required=False, widget=forms.HiddenInput())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["theme"].choices = get_theme_choices(self.request.user.customer)

    def get_state_filter(self, value):
        if value is None:
            lookup = "state"
            value = ""
        elif value == "ALL_ACTIVE":
            lookup = "state__in"
            value = FeatureRequest.ACTIVE_STATE_KEYS
        else:
            lookup = "state"
            value = value
        return lookup, value

    def get_priority_filter(self, value):
        if value == "NOT_SET":
            lookup = "priority"
            value = ""
        else:
            lookup = "priority"
            value = value
        return lookup, value

    def get_effort_filter(self, value):
        if value == "NOT_SET":
            lookup = "effort"
            value = ""
        else:
            lookup = "effort"
            value = value
        return lookup, value

    def get_base_queryset(self):
        return FeatureRequest.objects.prefetch_related("themes").filter(
            customer=self.request.user.customer
        )

    def get_filterable_attribute_lookup_base(self):
        # Features are feedback__user__xxx and Feedback is just user__xxx
        return "feedback__"

    def get_search_vector(self):
        return SearchVector(*self.get_search_fields(), config="english")

    def get_search_fields(self):
        return ("title", "description")

    def get_base_filters(self):
        return (
            ("user", "feedback__user", None),
            ("company", "feedback__user__company", None),
            ("state", self.get_state_filter, None),
            ("theme", self.get_theme_filter, None),
            ("priority", self.get_priority_filter, None),
            ("effort", self.get_effort_filter, None),
            ("feedback_type", "feedback__feedback_type", None),
            ("feedback_start_date", "feedback__created__gte", None),
            ("feedback_end_date", "feedback__created__lte", None),
            ("shipped_start_date", "shipped_at__gte", None),
            ("shipped_end_date", "shipped_at__lte", None),
        )


class BaseThemeForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request")
        super().__init__(*args, **kwargs)

    def clean_title(self):
        # Make sure we aren't creating multiple themes
        # with the same name or vary only by case.
        themes_to_check = Theme.objects.filter(
            customer=self.request.user.customer,
            title__iexact=self.cleaned_data["title"],
        )

        if self.instance:
            themes_to_check = themes_to_check.exclude(id=self.instance.id)

        if themes_to_check.exists():
            raise ValidationError(
                "A tag with that title already exists.", code="invalid"
            )
        return self.cleaned_data["title"]

    class Meta:
        model = Theme
        fields = [
            "title",
        ]

        widgets = {"title": forms.TextInput(attrs={"autofocus": True,})}


class ThemeCreateForm(BaseThemeForm):
    def save(self, commit=True):
        theme = super(ThemeCreateForm, self).save(commit=False)
        if commit:
            theme.customer = self.request.user.customer
            theme.save()
        return theme


class ThemeEditForm(BaseThemeForm):
    pass


class FeedbackFromRuleEditForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request")
        super().__init__(*args, **kwargs)

        self.fields[
            "filterable_attribute"
        ].queryset = FilterableAttribute.objects.filter(
            customer=self.request.user.customer,
            widget=FilterableAttribute.WIDGET_TYPE_SELECT,
        )
        self.fields[
            "filterable_attribute"
        ].label_from_instance = (
            lambda obj: f"{obj.friendly_name} ({obj.get_related_object_type_display()})"
        )

    class Meta:
        model = FeedbackFromRule
        fields = [
            "filterable_attribute",
            "attribute_value_trigger",
            "default_feedback_type",
        ]

        labels = {
            "filterable_attribute": "When a Person or Company with this attribute",
            "attribute_value_trigger": "Has this value",
            "default_feedback_type": "Then automatically set new Feedback's 'Feedback From' value to",
        }

        help_texts = {
            "attribute_value_trigger": format_lazy(
                "To see possible values for this attribute, either check the source system (e.g. Intercom, Help Scout, Segment etc.) or <a href='{}' target='_blank'>first show attribute in filters here</a> and then <a href='{}?filter=1' target='_blank'>see the attribute's values here</a>. Still not sure?  <a href='mailto:support@savio.io'>Contact support</a> for help.",
                reverse_lazy("filterable-attributes-list"),
                reverse_lazy("feature-request-list"),
            ),
        }


class FeedbackTemplateEditForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request")
        super().__init__(*args, **kwargs)

    class Meta:
        model = FeedbackTemplate
        fields = [
            "template",
        ]

        labels = {
            "template": "Enter your custom template",
        }

        help_texts = {
            "template": format_lazy(
                "The 'Problem' field will default to the template above when sending feedback from Slack (<a href='{}' target='_blank'>screenshot</a>) or the Chrome Extension. You can include Markdown.",
                static("images/help/slack-feedback-template.png"),
            ),
        }


class CloseLoopForm(forms.Form):
    ACTION_EMAIL = "ACTION_EMAIL"
    ACTION_CLOSE_LOOP = "ACTION_CLOSE_LOOP"
    ACTION_CLOSE_LOOP_AND_MARK_FR_NOTIFIED = "ACTION_CLOSE_LOOP_AND_MARK_FR_NOTIFIED"

    ACTION_CHOICES = (
        ("", "Choose an option"),
        (ACTION_EMAIL, "I'm just emailing these people"),
        (ACTION_CLOSE_LOOP, "I'm closing the loop"),
        (
            ACTION_CLOSE_LOOP_AND_MARK_FR_NOTIFIED,
            "I'm closing the loop and want to set this Feature Request's status to 'Customer notified'",
        ),
    )

    subject = forms.CharField(
        widget=forms.TextInput(
            attrs={"placeholder": "Enter a subject", "autofocus": "autofocus"}
        )
    )
    body = forms.CharField(widget=MarkdownWidget())
    action = forms.ChoiceField(
        choices=ACTION_CHOICES,
        help_text="'Closing the loop' means you're telling users that you built their feature, and we'll record who you closed the loop with.",
    )

    reply_to = forms.CharField(required=False)
    bcc = forms.CharField(required=False)

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request")
        self.feedback_to_notify = Feedback.objects.filter(
            customer=self.request.user.customer,
            id__in=self.request.GET.getlist("feedback_ids"),
        )
        self.feature_request = FeatureRequest.objects.filter(
            customer=self.request.user.customer
        ).get(id=self.request.GET.get("fr_id"))

        super().__init__(*args, **kwargs)

        try:
            frns = FeatureRequestNotificationSettings.objects.get(
                customer=self.request.user.customer
            )
            self.first_name_default = frns.first_name_default or "friend"
            self.fields["reply_to"].help_text = format_lazy(
                "Change or set this <a target='_blank' href='{}'>here</a>.",
                reverse_lazy(
                    "accounts-settings-feature-request-notification-settings",
                    kwargs={"pk": frns.pk},
                ),
            )
            self.fields["bcc"].help_text = format_lazy(
                "Change or set this <a target='_blank' href='{}'>here</a>.",
                reverse_lazy(
                    "accounts-settings-feature-request-notification-settings",
                    kwargs={"pk": frns.pk},
                ),
            )
        except FeatureRequestNotificationSettings.DoesNotExist:
            self.first_name_default = "friend"
            self.fields["reply_to"].help_text = format_lazy(
                "Change or set this in the Feature Request Notification Settings section on <a target='_blank' href='{}#fr_notification_settings'>your Settings page</a>.",
                reverse_lazy("accounts-settings-list"),
            )
            self.fields["bcc"].help_text = format_lazy(
                "Change or set this in the Feature Request Notification Settings section on <a target='_blank' href='{}#fr_notification_settings'>your Settings page</a>.",
                reverse_lazy("accounts-settings-list"),
            )

        self.helper = FormHelper()
        self.helper.layout = Layout(
            Fieldset(
                "",
                "subject",
                "body",
                HTML(
                    """
                <a href="#" value="Send test email" class="js-app-send-test-email-form float-right"><i class="fa fa-plus-circle"></i> Send test email</a>
                """
                ),
            ),
            Fieldset("", "action",),
            HTML(
                """
            <a id="toggle_reply_to_bcc" href="#">Change reply-to or bcc fields</a>
            """
            ),
            Fieldset(
                "",
                "reply_to",
                "bcc",
                style="display: none;",
                id="reply-to-bcc-fieldset",
            ),
            ButtonHolder(
                Submit("submit", "Send Message", css_class="btn btn-primary"),
                HTML(
                    """
                or <a href="{{return}}">cancel</a>
                """
                ),
                css_class="pt-4",
            ),
        )

    def clean_bcc(self):
        total_bcc = len(email_list_from_string(self.cleaned_data["bcc"]))
        if total_bcc > 5 and total_bcc < 25:
            raise ValidationError("You can only include a maximum of 5 bcc emails.")

        if total_bcc > 25:
            mail_admins(
                "Account disabled due to bcc stuffing",
                f"{self.request.user.email} - {self.request.user.customer.name}",
            )
            self.request.user.is_active = False
            self.request.user.save()
            logout(self.request)
            raise ValidationError("You can only include a maximum of 5 bcc emails.")

        return self.cleaned_data["bcc"]

    def clean(self):
        cleaned_data = super().clean()

        if getattr(self.request, "limited", False):
            rate_limit_stats = get_usage(
                self.request,
                group="close-the-loop-emails",
                key="user_or_ip",
                rate="10/h",
                method=["POST",],
            )
            time_left_in_minutes = rate_limit_stats["time_left"] // 60
            raise ValidationError(
                f"You can only send 10 emails per hour. You can send more in {time_left_in_minutes} minutes."
            )

        return cleaned_data

    def send_feedback_emails(self):
        users_emailed = {}
        total_emails_sent = 0
        for feedback in self.feedback_to_notify:
            if feedback.user and feedback.user.email:
                # Don't email the user multiple times if they've submitted
                # feedback for this feature multiple times.
                if feedback.user.email not in users_emailed:
                    self.send_feedback_email(feedback)
                    users_emailed[feedback.user.email] = True
                    total_emails_sent += 1
                    tracking.customer_email_sent(
                        self.request.user, feedback.user, self.cleaned_data["action"]
                    )
        if self.cleaned_data["action"] == CloseLoopForm.ACTION_CLOSE_LOOP:
            self.set_feedback_notified()
        elif (
            self.cleaned_data["action"]
            == CloseLoopForm.ACTION_CLOSE_LOOP_AND_MARK_FR_NOTIFIED
        ):
            self.set_feedback_notified()
            self.set_feature_request_notified()
        return total_emails_sent

    def set_feedback_notified(self):
        self.feedback_to_notify.update(
            notified_at=timezone.now(), notified_by=self.request.user
        )

        OnboardingTask.objects.filter(
            customer=self.request.user.customer,
            task_type=OnboardingTask.TASK_CLOSE_THE_LOOP,
        ).update(completed=True, updated=timezone.now())

    def set_feature_request_notified(self):
        self.feature_request.state = FeatureRequest.CUSTOMER_NOTIFIED
        self.feature_request.save()

    def send_feedback_email(self, feedback):
        if self.cleaned_data["bcc"]:
            bcc = email_list_from_string(self.cleaned_data["bcc"])
        else:
            bcc = None

        if self.cleaned_data["reply_to"]:
            reply_to = [self.cleaned_data["reply_to"]]
        else:
            reply_to = [self.request.user.email]

        app_company_id = -1
        if feedback.user.company:
            app_company_id = feedback.user.company.id

        from_email = (
            f"{self.request.user.get_full_name()} via Savio <email@mg.savio.io>"
        )
        body = self.replace_variables(self.cleaned_data["body"], feedback)
        html_body = loader.render_to_string(
            "email/close_the_loop_email.html",
            {
                "title": self.replace_variables(self.cleaned_data["subject"], feedback),
                "body": body,
                "customer": quote(self.request.user.customer.name),
                "user": feedback.user.id,
                "company": app_company_id,
            },
        )

        txt_email = loader.render_to_string(
            "email/close_the_loop_email.txt", {"body": body,},
        )

        msg = EmailMultiAlternatives(
            self.replace_variables(self.cleaned_data["subject"], feedback),
            txt_email,
            from_email,
            [feedback.user.email,],
            bcc,
            reply_to=reply_to,
        )

        msg.attach_alternative(html_body, "text/html")
        msg.send()

    def replace_variables(self, text, feedback):
        if feedback.user and feedback.user.get_first_name():
            first_name = feedback.user.get_first_name()
        else:
            first_name = self.first_name_default

        variables = {
            "first_name": first_name,
        }

        for k, v in variables.items():
            to_replace = "{" + k + "}"
            text = text.replace(to_replace, v)
        return text


class FeatureRequestNotificationSendTestEmailForm(forms.Form):
    test_email = forms.CharField()
    test_subject = forms.CharField(required=False, widget=forms.HiddenInput())
    test_body = forms.CharField(required=False, widget=forms.HiddenInput())
    test_reply_to = forms.CharField(required=False, widget=forms.HiddenInput())

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request")
        super().__init__(*args, **kwargs)
        self.fields["test_email"].initial = self.request.user.email

    def clean_test_email(self):
        total_test_emails = len(email_list_from_string(self.cleaned_data["test_email"]))
        if total_test_emails > 3 and total_test_emails < 25:
            raise ValidationError("You can only include a maximum of 3 test emails.")

        if total_test_emails > 25:
            mail_admins(
                "Account disabled due to test email stuffing",
                f"{self.request.user.email} - {self.request.user.customer.name}",
            )
            self.request.user.is_active = False
            self.request.user.save()
            logout(self.request)
            raise ValidationError("You can only include a maximum of 3 test emails.")

        return self.cleaned_data["test_email"]

    def clean(self):
        cleaned_data = super().clean()

        if getattr(self.request, "limited", False):
            rate_limit_stats = get_usage(
                self.request,
                group="close-the-loop-test-emails",
                key="user_or_ip",
                rate="10/h",
                method=["POST",],
            )
            time_left_in_minutes = rate_limit_stats["time_left"] // 60
            raise ValidationError(
                f"You can only send 10 test emails per hour. You can send more in {time_left_in_minutes} minutes."
            )

        if not self.cleaned_data["test_subject"] or not self.cleaned_data["test_body"]:
            raise forms.ValidationError("You need to enter a subject and a body first.")
        return cleaned_data

    def send_test_email(self):
        if self.cleaned_data["test_reply_to"]:
            reply_to = [self.cleaned_data["test_reply_to"]]
        else:
            reply_to = None

        subject = f"[TEST] {self.replace_variables(self.cleaned_data['test_subject'])}"
        body = self.replace_variables(self.cleaned_data["test_body"])
        html_body = loader.render_to_string(
            "email/close_the_loop_email.html",
            {
                "body": body,
                "customer": quote(self.request.user.customer.name),
                "user": "TEST",
                "company": "TEST",
            },
        )

        from_email = (
            f"{self.request.user.get_full_name()} via Savio <notifications@savio.io>"
        )
        msg = EmailMessage(
            subject,
            html_body,
            from_email,
            [self.cleaned_data["test_email"],],
            reply_to=reply_to,
        )
        msg.content_subtype = "html"  # Main content is now text/html
        msg.send()

    def replace_variables(self, text):
        try:
            frns = FeatureRequestNotificationSettings.objects.get(
                customer=self.request.user.customer
            )
            self.first_name_default = frns.first_name_default or "friend"
        except FeatureRequestNotificationSettings.DoesNotExist:
            self.first_name_default = "friend"

        variables = {
            "first_name": self.first_name_default,
        }

        for k, v in variables.items():
            to_replace = "{" + k + "}"
            text = text.replace(to_replace, v)
        return text
