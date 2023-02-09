import functools
import operator
import pickle
import re

from django.contrib import messages
from django.contrib.messages.views import SuccessMessageMixin
from django.db.models import Count, Max, Min, Q
from django.http import JsonResponse
from django.http.request import QueryDict
from django.shortcuts import get_object_or_404, redirect
from django.template.defaultfilters import pluralize, truncatechars
from django.template.loader import render_to_string
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.html import format_html
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    FormView,
    ListView,
    UpdateView,
)
from ratelimit.decorators import ratelimit

from accounts.decorators import role_required
from accounts.models import FeatureRequestNotificationSettings, OnboardingTask, User
from appaccounts.models import FilterableAttribute
from common.utils import remove_markdown
from internal_analytics import tracking
from prodtool.views import RequestContextMixin, ReturnUrlMixin
from sharedwidgets.headers import SortHeaders
from sharedwidgets.widgets import SavioAutocomplete

from .forms import (
    CloseLoopForm,
    FeatureListFilterForm,
    FeatureRequestCreateForm,
    FeatureRequestEditForm,
    FeatureRequestMergeForm,
    FeatureRequestNotificationSendTestEmailForm,
    FeedbackCreateForm,
    FeedbackEditForm,
    FeedbackFromRuleEditForm,
    FeedbackListFilterForm,
    FeedbackTemplateEditForm,
    FeedbackTriageEditForm,
    ThemeCreateForm,
    ThemeEditForm,
)
from .models import (
    CustomerFeedbackImporterSettings,
    FeatureRequest,
    Feedback,
    FeedbackFromRule,
    FeedbackTemplate,
    Theme,
)
from .tasks import export_feature_requests_to_csv, export_feedback_to_csv


class FilterFormMixin(object):
    def get_filter_form_class(self):
        raise NotImplementedError

    def get_filter_form(self):
        if not self.filter_form_instance:
            filter_form_instance = self.get_filter_form_class()(
                self.request.GET, request=self.request
            )
            if filter_form_instance.is_valid():
                self.filter_form_instance = filter_form_instance
            else:
                # HACK ALTER:
                # There can be cases where filter form is invalid.
                # For example, if you open the page in a new tab
                # delete a them and then refresh the page.
                # We assume this fitler form is always going to be
                # valid and later on when we call form.get_filter_queryset
                # and blow up because the form is None.
                # This little hack just drops all fitlers in the case
                # where the filter is invalid. We could do something
                # more clever like look at the errors and try and drop
                # only "bad" filters. The other lame thing here is that
                # the URL has qs string that don't really match what's
                # going on. We could also clean this up with share
                # implemention and get calls a method to get the
                # filter form class.
                print(f"Error: {filter_form_instance.errors}")
                qd = QueryDict()
                self.filter_form_instance = self.get_filter_form_class()(
                    qd, request=self.request
                )

                # Caller assumes that we have a validate form with
                # form.cleaned_data in place so we need to call
                # is_valid() before returning.
                self.filter_form_instance.is_valid()
        return self.filter_form_instance


@method_decorator(role_required(User.ROLE_OWNER_OR_ADMIN), name="dispatch")
class FeedbackListView(FilterFormMixin, ListView):
    model = Feedback
    context_object_name = "feedbacks"
    template_name = "feedback_list.html"
    filter_form_instance = None
    paginate_by = 50

    def get_filter_form_class(self):
        return FeedbackListFilterForm

    def get(self, request, *args, **kwargs):
        response = super().get(self, request, *args, **kwargs)
        if self.is_export_request():
            return self.queue_export_and_redirect()
        return response

    def is_export_request(self):
        return self.request.GET.get("format", "") == "csv"

    def queue_export_and_redirect(self):
        pickled_feedback_qs = pickle.dumps(self.get_queryset().query)

        export_feedback_to_csv.delay(self.request.user.id, pickled_feedback_qs)
        messages.success(self.request, "You'll get an email with your export shortly.")
        query_string = self.request.GET.copy()
        query_string.pop("format")
        url = reverse("feedback-list")
        return redirect(f"{url}?{query_string.urlencode()}")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["no_feedback"] = not Feedback.objects.filter(
            customer=self.request.user.customer
        ).exists()
        context["filter_form"] = self.get_filter_form()
        context["clear_url_name"] = "feedback-list"
        context[
            "plan_display_name"
        ] = FilterableAttribute.objects.get_plan_display_name(
            self.request.user.customer
        )
        context["mrr_display_name"] = FilterableAttribute.objects.get_mrr_display_name(
            self.request.user.customer
        )
        context["mrr_attribute"] = FilterableAttribute.objects.get_mrr_attribute(
            self.request.user.customer
        )
        context["plan_attribute"] = FilterableAttribute.objects.get_plan_attribute(
            self.request.user.customer
        )

        return context

    def get_queryset(self):
        tracking.feedback_list_viewed(self.request.user, self.request.GET)
        return self.get_filter_form().get_filtered_queryset(self.request)


@method_decorator(role_required(User.ROLE_OWNER_OR_ADMIN), name="dispatch")
class FeedbackItemView(ReturnUrlMixin, DetailView):
    model = Feedback
    context_object_name = "feedback"
    template_name = "feedback_details.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["mrr_attribute"] = FilterableAttribute.objects.get_mrr_attribute(
            self.request.user.customer
        )
        context["plan_attribute"] = FilterableAttribute.objects.get_plan_attribute(
            self.request.user.customer
        )
        context[
            "company_display_attributes"
        ] = FilterableAttribute.objects.get_company_display_attributes(
            self.request.user.customer
        )
        context[
            "user_display_attributes"
        ] = FilterableAttribute.objects.get_user_display_attributes(
            self.request.user.customer
        )
        return context

    def get_return_url(self):
        feedback_list_url = reverse_lazy("feedback-list")
        return self.request.GET.get("return", feedback_list_url)

    def get_queryset(self):
        return Feedback.objects.filter(customer=self.request.user.customer)

    def get_success_url(self):
        return self.get_return_url()


@method_decorator(role_required(User.ROLE_OWNER_OR_ADMIN), name="dispatch")
class FeedbackInboxListView(ListView):
    model = Feedback
    context_object_name = "feedbacks"
    template_name = "feedback_inbox_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["no_feedback"] = not Feedback.objects.filter(
            customer=self.request.user.customer
        ).exists()
        context["state"] = self.get_state()
        context["onboarding"] = self.request.GET.get("onboarding", "no") == "yes"
        return context

    def get_queryset(self):
        return (
            Feedback.objects.select_related("user", "user__company", "feature_request")
            .filter(customer=self.request.user.customer, state=self.get_state())
            .order_by("-created")
        )

    def get_state(self):
        state = self.kwargs["state"].upper()
        if state == Feedback.ACTIVE:
            state = Feedback.ACTIVE
        elif state == Feedback.PENDING:
            state = Feedback.PENDING
        else:
            state = Feedback.ACTIVE
        return state


@method_decorator(role_required(User.ROLE_OWNER_OR_ADMIN), name="dispatch")
class FeedbackInboxItemView(RequestContextMixin, SuccessMessageMixin, UpdateView):
    model = Feedback
    form_class = FeedbackTriageEditForm
    template_name = "feedback_update_linked_feature_requeset.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["mrr_attribute"] = FilterableAttribute.objects.get_mrr_attribute(
            self.request.user.customer
        )
        context["plan_attribute"] = FilterableAttribute.objects.get_plan_attribute(
            self.request.user.customer
        )
        context[
            "company_display_attributes"
        ] = FilterableAttribute.objects.get_company_display_attributes(
            self.request.user.customer
        )
        context[
            "user_display_attributes"
        ] = FilterableAttribute.objects.get_user_display_attributes(
            self.request.user.customer
        )
        context["previous_feedback"] = self.get_previous_item_to_triage()
        context["next_feedback"] = self.get_next_item_to_triage()
        context["onboarding"] = self.request.GET.get("onboarding", "no") == "yes"
        return context

    def form_valid(self, form):
        if self.request.POST.get("action") == "Unarchive":
            form.instance.state = Feedback.ACTIVE
        elif self.request.POST.get("action") == "Active":
            form.instance.state = Feedback.ACTIVE
        elif self.request.POST.get("action") == "Mark Triaged":
            form.instance.state = Feedback.ARCHIVED
        else:
            form.instance.state = Feedback.PENDING
        return super().form_valid(form)

    def get_queryset(self):
        return Feedback.objects.filter(customer=self.request.user.customer)

    def get_success_url(self):
        if self.request.GET.get("onboarding", "no") == "yes":
            try:
                fr = FeatureRequest.objects.filter(
                    feedback=self.object.id, customer=self.request.user.customer
                )
                url = reverse_lazy(
                    "feature-request-feedback-details", kwargs={"pk": fr[0].id}
                )
                url = f"{url}?onboarding=yes&return={reverse_lazy('accounts-onboarding-checklist')}"
            except FeatureRequest.DoesNotExist:
                url = reverse_lazy("accounts-onboarding-checklist")
            return url

        elif self.request.POST.get("initial_state") == Feedback.PENDING:
            return reverse_lazy("feedback-inbox-list", kwargs={"state": "pending"})
        else:
            if self.request.GET.get("return", None) is not None:
                return self.request.GET.get("return")

            next_item = self.get_next_item_to_triage()
            if next_item:
                return reverse_lazy("feedback-inbox-item", kwargs={"pk": next_item.pk})
            else:
                return reverse_lazy("feedback-inbox-list", kwargs={"state": "active"})

    def get_previous_item_to_triage(self):
        # See comment at get_next_item_to_triage
        active_qs = (
            self.get_queryset().filter(state=Feedback.ACTIVE).order_by("-created")
        )
        active_and_newer_qs = active_qs.filter(
            created__gte=self.get_object().created
        ).exclude(id=self.get_object().id)
        if active_and_newer_qs.exists():
            previous_item = active_and_newer_qs.last()
        elif active_qs.exists():
            previous_item = active_qs.last()
        else:
            previous_item = None
        return previous_item

    def get_next_item_to_triage(self):
        # Right now the triage list is sorted by created desc and
        # we don't let you change that. If we change that then
        # this will need to change.

        # Effectively we are getting the next oldest item if there
        # is one. Otherwise we're getting the newest one so we wrap
        # back around to the first one in the list.
        active_qs = (
            self.get_queryset().filter(state=Feedback.ACTIVE).order_by("-created")
        )
        active_and_older_qs = active_qs.filter(
            created__lte=self.get_object().created
        ).exclude(id=self.get_object().id)
        if active_and_older_qs.exists():
            next_item = active_and_older_qs[0]
        elif active_qs.exists():
            next_item = active_qs.first()
        else:
            next_item = None
        return next_item

    def get_action_past_tence(self):
        action = self.request.POST.get("action")
        if action == "Save":
            past_tense = "Saved"
        elif action == "Mark Triaged":
            past_tense = "Triaged"
        elif action == "Unarchive":
            past_tense = "Unarchived"
        elif action == "Active":
            past_tense = "Activated"
        else:
            past_tense = "Snoozed"
        return past_tense

    def get_success_message(self, cleaned_data):
        tracking.feedback_triaged(
            self.request.user, self.model, cleaned_data["snooze_for"]
        )
        url = reverse("feedback-item", kwargs={"pk": self.object.id})
        message = format_html(
            "{} feedback '<a href='{}'>{}</a>'",
            self.get_action_past_tence(),
            url,
            self.get_object().get_problem_snippet(),
        )
        return message


@method_decorator(role_required(User.ROLE_OWNER_OR_ADMIN), name="dispatch")
class FeedbackInboxCreateItemView(ReturnUrlMixin, SuccessMessageMixin, CreateView):
    model = Feedback
    template_name = "feedback_create.html"
    form_class = FeedbackCreateForm

    def get_return_url(self):
        active_feedback_list_url = reverse_lazy(
            "feedback-inbox-list", kwargs={"state": "active"}
        )
        return self.request.GET.get("return", active_feedback_list_url)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["onboarding"] = self.request.GET.get("onboarding", "no") == "yes"
        return context

    def get_queryset(self):
        return Feedback.objects.filter(customer=self.request.user.customer)

    def get_success_url(self):
        return self.get_return_url()

    def get_success_message(self, cleaned_data):
        url = reverse("feedback-item", kwargs={"pk": self.object.id})
        message = format_html(
            "Created feedback '<a href='{}'>{}</a>'",
            url,
            remove_markdown(cleaned_data["problem"], 100),
        )
        return message


@method_decorator(role_required(User.ROLE_OWNER_OR_ADMIN), name="dispatch")
class FeedbackCreateItemView(ReturnUrlMixin, SuccessMessageMixin, CreateView):
    model = Feedback
    template_name = "feedback_create.html"
    form_class = FeedbackCreateForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["onboarding"] = self.request.GET.get("onboarding", "no") == "yes"
        return context

    def get_return_url(self):
        feedback_list_url = reverse_lazy("feedback-list")
        return self.request.GET.get("return", feedback_list_url)

    def get_queryset(self):
        return Feedback.objects.filter(customer=self.request.user.customer)

    def get_success_url(self):
        return self.get_return_url()

    def get_success_message(self, cleaned_data):
        url = reverse("feedback-item", kwargs={"pk": self.object.id})
        message = format_html(
            "Created feedback '<a href='{}'>{}</a>'",
            url,
            remove_markdown(cleaned_data["problem"], 100),
        )
        return message

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        initial = kwargs.get("initial", {})

        # If we are adding a new FR from the blank slate of FR list
        # we pass in the `feature_request_id` to prelink the FR to
        # the new feedback.
        fr_id = self.request.GET.get("feature_request_id", None)
        if fr_id:
            try:
                fr = FeatureRequest.objects.filter(
                    customer=self.request.user.customer
                ).get(id=fr_id)
                initial["feature_request"] = fr
            except FeatureRequest.DoesNotExist:
                pass

        # If we are triaging a pice of feedback the user can select some
        # text in the problem which will pop up some ui to let them create
        # a new piece of feedback. In that case we pass `split_feedback_id`
        # and `problem` so we can prepopulate the fields we already know
        # about.
        split_feedback_id = self.request.GET.get("split_feedback_id", None)
        if split_feedback_id:
            split_feedback_url = ""
            try:
                feedback = Feedback.objects.filter(
                    customer=self.request.user.customer
                ).get(id=split_feedback_id)
                initial["user"] = feedback.user
                initial["feedback_type"] = feedback.feedback_type
                split_feedback_url = f"\r\n\r\nThis was originally feedback in [{feedback.get_problem_snippet(100, '')}]({reverse_lazy('feedback-item', kwargs={'pk': split_feedback_id})})"
            except Feedback.DoesNotExist:
                pass

            problem = self.request.GET.get("problem", None)
            if problem:
                initial["problem"] = problem + split_feedback_url

        kwargs["initial"] = initial
        return kwargs


@method_decorator(role_required(User.ROLE_OWNER_OR_ADMIN), name="dispatch")
class FeedbackInboxUpdateItemView(ReturnUrlMixin, SuccessMessageMixin, UpdateView):
    model = Feedback
    template_name = "feedback_update_feedback.html"
    form_class = FeedbackEditForm

    def get_return_url(self):
        return reverse_lazy("feedback-inbox-item", kwargs={"pk": self.get_object().pk})

    def get_queryset(self):
        return Feedback.objects.filter(customer=self.request.user.customer)

    def get_success_url(self):
        return reverse_lazy("feedback-inbox-item", kwargs={"pk": self.get_object().pk})

    def get_success_message(self, cleaned_data):
        url = reverse("feedback-item", kwargs={"pk": self.object.id})
        message = format_html(
            "Saved feedback '<a href='{}'>{}</a>'",
            url,
            remove_markdown(cleaned_data["problem"], 100),
        )
        return message


@method_decorator(role_required(User.ROLE_OWNER_OR_ADMIN), name="dispatch")
class FeedbackUpdateItemView(FeedbackInboxUpdateItemView):
    def get_return_url(self):
        feedback_item_view = reverse_lazy(
            "feedback-item", kwargs={"pk": self.get_object().pk}
        )
        return self.request.GET.get("return", feedback_item_view)

    def get_success_url(self):
        tracking.feedback_edited(self.request.user)
        return self.get_return_url()


@method_decorator(role_required(User.ROLE_OWNER_OR_ADMIN), name="dispatch")
class FeedbackDeleteItemView(ReturnUrlMixin, DeleteView):
    model = Feedback
    template_name = "generic_confirm_delete.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["type"] = "Feedback"
        context["name"] = self.get_object().get_problem_snippet()
        return context

    def get_queryset(self):
        return Feedback.objects.filter(customer=self.request.user.customer)

    def get_return_url(self):
        return_url = reverse_lazy("feedback-list")
        return self.request.GET.get("return", return_url)

    def get_success_url(self):
        return self.get_return_url()

    def delete(self, request, *args, **kwargs):
        messages.success(
            self.request, f"Delete feedback '{self.get_object().get_problem_snippet()}'"
        )
        return super(FeedbackDeleteItemView, self).delete(request, *args, **kwargs)


@method_decorator(role_required(User.ROLE_OWNER_OR_ADMIN), name="dispatch")
class FeatureRequestAutocomplete(SavioAutocomplete):
    QUERY_REGEX = re.compile(r"(?P<query>.*)\s*tags?:(?P<tags>.*)")

    def get_create_option(self, context, q):
        matches = self.QUERY_REGEX.match(q or "")
        if matches and matches.group("query").strip():
            # We've got both a query and some tags
            # Let them make a new item but only with the
            # query part stripping out "tag:xxx,yyy" syntax.
            create_option = super().get_create_option(
                context, matches.group("query").strip()
            )
        elif matches:
            # either "tags:" or "tags:sometag,oranother"
            # in this case there is no query so we don't want
            # to let them create a new FR that is just the
            # tag filter syntax.
            create_option = []
        else:
            # No "tag:xxx" nonsense they can make a new item
            # using whatever they've typed in.
            create_option = super().get_create_option(context, q)
        return create_option

    def get_create_result_label(self, new_value):
        return f"<strong>New Feature: {new_value}</strong>"

    def has_add_permission(self, request):
        return request.user.is_authenticated

    def create_object(self, text):
        """Create an object given a text."""
        fr, created = self.get_queryset().get_or_create(
            **{"customer": self.request.user.customer, self.create_field: text,}
        )
        if created:
            tracking.feature_request_created(
                self.request.user, tracking.EVENT_SOURCE_WEB_APP
            )
        return fr

    def get_queryset(self):
        # See 1e2bb17ff678542a93ad5917e8907fead6e154c4 for doing this w/o
        # django-autocomplete-light
        if not self.request.user.is_authenticated:
            return FeatureRequest.objects.none()

        qs = FeatureRequest.objects.filter(customer=self.request.user.customer)

        order_by = [
            "title",
        ]
        if self.q:
            matches = self.QUERY_REGEX.match(self.q)
            if matches:
                query = matches.group("query").strip()
                themes = matches.group("tags")
            else:
                themes = None
                query = self.q.strip()
            qs = qs.filter(Q(title__icontains=query) | Q(description__icontains=query))
            if themes:
                # We've got one or more themes limit the results
                # to only those results that have one of those themes.
                theme_filters = []
                for theme in themes.split(","):
                    theme = theme.strip()
                    theme_filters.append(Q(themes__title__icontains=theme))
                qs = qs.filter(functools.reduce(operator.or_, theme_filters))

                # Since we're limiting the results based on themes, group
                # results by theme as well.
                order_by = ("themes__title", "title")
        return qs.order_by(*order_by)

    def get_result_label(self, fr):
        theme_names = fr.themes.all().values_list("title", flat=True)
        if theme_names:
            themes_html = ""
            for name in theme_names:
                themes_html += f"<span class='small-badge badge badge-text badge-light'>{name}</span>&nbsp;"
        else:
            themes_html = ""
        return f"{fr.title}<br>{themes_html}"

    def get_selected_result_label(self, fr):
        return fr.title

    def get_result_label_without_formating(self, fr):
        return fr.title


@method_decorator(role_required(User.ROLE_OWNER_OR_ADMIN), name="dispatch")
class FeatureRequestAutocompleteNoCreate(FeatureRequestAutocomplete):
    def has_add_permission(self, request):
        return False


@method_decorator(role_required(User.ROLE_OWNER_OR_ADMIN), name="dispatch")
class ThemeAutocomplete(SavioAutocomplete):
    def get_create_result_label(self, new_value):
        return f"<strong>New Tag: {new_value}</strong>"

    def has_add_permission(self, request):
        return request.user.is_authenticated

    def create_object(self, text):
        """Create an object given a text."""
        theme, created = self.get_queryset().get_or_create(
            **{"customer": self.request.user.customer, self.create_field: text,}
        )

        if created:
            tracking.theme_created(self.request.user)
        return theme

    def get_queryset(self):
        # See 1e2bb17ff678542a93ad5917e8907fead6e154c4 for doing this w/o
        # django-autocomplete-light
        if not self.request.user.is_authenticated:
            return FeatureRequest.objects.none()

        qs = Theme.objects.filter(customer=self.request.user.customer)

        if self.q:
            qs = qs.filter(title__icontains=self.q)
        return qs.order_by("title")


@method_decorator(role_required(User.ROLE_OWNER_OR_ADMIN), name="dispatch")
class FeatureRequestListView(FilterFormMixin, ListView):
    model = FeatureRequest
    context_object_name = "feature_requests"
    template_name = "feature_request_list.html"
    filter_form_instance = None
    paginate_by = 50

    LIST_HEADERS = (
        ("Feature Request", "title", {"width": "40%", "class": "pt-0 bt-0"}),
        ("Feedback", "total_feedback", {"width": "10%", "class": "pt-0 bt-0 right"}),
        ("MRR", "total_mrr", {"width": "15%", "class": "pt-0 bt-0 right"}),
        ("Status", "state", {"width": "15%", "class": "pt-0 bt-0"}),
        ("Priority", "priority", {"width": "10%", "class": "pt-0 bt-0"}),
        ("Effort", "effort", {"width": "10%", "class": "pt-0 bt-0"}),
    )

    def get_filter_form_class(self):
        return FeatureListFilterForm

    def get(self, request, *args, **kwargs):
        response = super().get(self, request, *args, **kwargs)
        if self.is_export_request():
            return self.queue_export_and_redirect()
        return response

    def is_export_request(self):
        return self.request.GET.get("format", "") == "csv"

    def queue_export_and_redirect(self):
        pickled_fr_qs = pickle.dumps(self.get_queryset().query)

        filter_form_instance = FeedbackListFilterForm(
            self.request.GET, request=self.request
        )
        if filter_form_instance.is_valid():
            feedback_qs = filter_form_instance.get_filtered_queryset(self.request)
        else:
            feedback_qs = Feedback.filter(customer=self.request.user.customer)
        pickled_feedback_qs = pickle.dumps(feedback_qs.query)

        export_feature_requests_to_csv.delay(
            self.request.user.id, pickled_fr_qs, pickled_feedback_qs
        )
        messages.success(self.request, "You'll get an email with your export shortly.")
        query_string = self.request.GET.copy()
        query_string.pop("format")
        url = reverse("feature-request-list")
        return redirect(f"{url}?{query_string.urlencode()}")

    def get_sort_headers(self):
        return SortHeaders(
            self.request,
            self.LIST_HEADERS,
            default_order_field=1,
            default_order_type="desc",
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filter_form"] = self.get_filter_form()
        context["has_features"] = FeatureRequest.objects.filter(
            customer=self.request.user.customer
        ).exists()
        context["clear_url_name"] = "feature-request-list"
        context["mrr_display_name"] = FilterableAttribute.objects.get_mrr_display_name(
            self.request.user.customer
        )
        context["filter_params"] = self.get_feedback_filter_params().urlencode()
        context["headers"] = self.get_sort_headers().headers()
        context["onboarding"] = self.request.GET.get("onboarding", "no") == "yes"
        return context

    def get_feedback_filter_params(self):
        # We need to be careful here because some of the filter_form params
        # are for FRs not the nested Feedback. If we include those and then
        # we edit the FR in a way where it no longer matches the params we'll
        # get a 404 as we'll exclude ourself. Given that we only want to pass
        # along params that are for Feedback.
        params_to_exclude = (
            "search",
            "state",
            "theme",
            "priority",
            "effort",
            "shipped_start_date",
            "shipped_end_date",
            "shipped_date_range",
        )
        filter_dict = self.get_filter_form().data
        qd = QueryDict(mutable=True)
        qd.update(filter_dict)
        for param_name in params_to_exclude:
            if param_name in qd:
                qd.pop(param_name)

        # HACK: there is surely a better way but the form returns empty values
        # here as None but when we urlencode that we get 'None'. DateField
        # doesn't like 'None' b/c it's not a valid date. So... here we just
        # turn None into '' which the form is happy with.
        if qd.get("feedback_date_range", None) is None:
            qd["feedback_date_range"] = ""
        if qd.get("feedback_start_date", None) is None:
            qd["feedback_start_date"] = ""
        if qd.get("feedback_end_date", None) is None:
            qd["feedback_end_date"] = ""

        return qd

    def get_queryset(self):
        tracking.feature_request_list_viewed(self.request.user, self.request.GET)
        qs = self.get_filter_form().get_filtered_queryset(self.request)

        # If the user has clicked the specific mrr value in the user details
        # chiclet we need to filter the results down to just those with that
        # mrr. We can't reuse the filter form for that because it's a grouped
        # select list and that value might not be there.
        # See:
        # https://app.clubhouse.io/savio/story/1528/attributeerror-nonetype-object-has-no-attribute-get-filtered-queryset
        if self.request.GET.get("_uc_mrr"):
            qs = self.apply_specific_mrr_filter(qs)
        qs = qs.with_counts(self.request.user.customer)
        return qs.order_by(self.get_sort_headers().get_order_by_expression())

    def apply_specific_mrr_filter(self, qs):
        lookup = FilterableAttribute.objects.get_mrr_lookup(self.request.user.customer)
        if lookup:
            lookup = f"feedback__{lookup[0]}__{lookup[1]}"
            try:
                mrr_value = float(self.request.GET.get("_uc_mrr"))
                filters = {lookup: mrr_value}
                qs = qs.filter(**filters)
            except ValueError:
                pass
        return qs


@method_decorator(role_required(User.ROLE_OWNER_OR_ADMIN), name="dispatch")
class FeatureRequestUpdateItemView(ReturnUrlMixin, SuccessMessageMixin, UpdateView):
    model = FeatureRequest
    template_name = "feature_request_update.html"
    form_class = FeatureRequestEditForm

    def get_return_url(self):
        feature_request_list_url = reverse_lazy("feature-request-list")
        return self.request.GET.get("return", feature_request_list_url)

    def get_queryset(self):
        return FeatureRequest.objects.filter(customer=self.request.user.customer)

    def get_success_url(self):
        return self.get_return_url()

    def get_success_message(self, cleaned_data):
        tracking.feature_request_edited(self.request.user)
        url = reverse("feature-request-feedback-details", kwargs={"pk": self.object.id})
        message = format_html(
            "Saved feature '<a href='{}'>{}</a>'",
            url,
            remove_markdown(cleaned_data["title"], 100),
        )
        return message


@method_decorator(role_required(User.ROLE_OWNER_OR_ADMIN), name="dispatch")
class FeatureRequestCreateItemView(ReturnUrlMixin, SuccessMessageMixin, CreateView):
    model = FeatureRequest
    template_name = "feature_request_create.html"
    form_class = FeatureRequestCreateForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["onboarding"] = self.request.GET.get("onboarding", "no") == "yes"
        context["has_feedback"] = Feedback.objects.filter(
            customer=self.request.user.customer
        ).exists()
        return context

    def get_return_url(self):
        feature_request_list_url = reverse_lazy("feature-request-list")
        return self.request.GET.get("return", feature_request_list_url)

    def get_queryset(self):
        return Feedback.objects.filter(customer=self.request.user.customer)

    def get_success_url(self):
        return self.get_return_url()

    def get_success_message(self, cleaned_data):
        tracking.feature_request_created(
            self.request.user, tracking.EVENT_SOURCE_WEB_APP
        )
        url = reverse("feature-request-feedback-details", kwargs={"pk": self.object.id})
        message = format_html(
            "Created feature '<a href='{}'>{}</a>'",
            url,
            remove_markdown(cleaned_data["title"], 100),
        )
        return message


@role_required(User.ROLE_OWNER_OR_ADMIN)
def feature_request_ajax_create(request):
    data = dict()

    if request.method == "POST":
        form = FeatureRequestCreateForm(request.POST, request=request)
        if form.is_valid():
            form.save()
            data["form_is_valid"] = True
            data["id"] = form.instance.id
            data["text"] = form.instance.title
        else:
            data["form_is_valid"] = False
    else:
        form = FeatureRequestCreateForm(request=request)

    context = {"form": form}
    data["html_form"] = render_to_string(
        "feature_request_ajax_create.html", context, request=request,
    )
    return JsonResponse(data)


@method_decorator(role_required(User.ROLE_OWNER_OR_ADMIN), name="dispatch")
class FeatureRequestDeleteItemView(ReturnUrlMixin, DeleteView):
    model = FeatureRequest
    template_name = "generic_confirm_delete.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["type"] = "Feature Request"
        context["name"] = truncatechars(self.get_object().title, 100)
        total_related_feedback = self.get_object().feedback_set.all().count()
        if total_related_feedback:
            context[
                "extra_message"
            ] = f"{total_related_feedback} pieces of related feedback will be unlinked but not deleted."

        return context

    def get_return_url(self):
        return_url = reverse_lazy("feature-request-list")
        return self.request.GET.get("return", return_url)

    def get_success_url(self):
        return self.get_return_url()

    def delete(self, request, *args, **kwargs):
        messages.success(
            self.request, f"Delete feature request '{self.get_object().title}'"
        )
        return super(FeatureRequestDeleteItemView, self).delete(
            request, *args, **kwargs
        )


@method_decorator(role_required(User.ROLE_OWNER_OR_ADMIN), name="dispatch")
class FeatureRequestMergeItemView(ReturnUrlMixin, FormView):
    template_name = "feature_request_merge.html"
    form_class = FeatureRequestMergeForm

    def get_initial(self):
        initial = super().get_initial()
        feature_request_to_keep = get_object_or_404(
            FeatureRequest,
            customer=self.request.user.customer,
            pk=self.request.GET.get("fr", None),
        )
        initial["feature_request_to_keep"] = feature_request_to_keep.pk
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        feature_request_to_keep = get_object_or_404(
            FeatureRequest,
            customer=self.request.user.customer,
            pk=self.request.GET.get("fr", None),
        )

        context["feature_request_to_keep"] = feature_request_to_keep
        return context

    def form_valid(self, form):
        form.save()
        return super().form_valid(form)

    def get_return_url(self):
        return_url = reverse_lazy("feature-request-list")
        return self.request.GET.get("return", return_url)

    def get_success_url(self):
        return self.get_return_url()


@method_decorator(role_required(User.ROLE_OWNER_OR_ADMIN), name="dispatch")
class FeatureRequestFeedbackDetailsView(ReturnUrlMixin, FilterFormMixin, DetailView):
    model = FeatureRequest
    context_object_name = "feature_request"
    template_name = "feature_request_feedback_details.html"
    filter_form_instance = None
    feedback_filter_form_instance = None

    def get_return_url(self):
        feature_request_list_url = reverse_lazy("feature-request-list")
        return self.request.GET.get("return", feature_request_list_url)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["days_open"] = max(1, (timezone.now() - self.get_object().created).days)
        context["onboarding"] = self.request.GET.get("onboarding", "no") == "yes"

        # feedback_duration doesn't seem to be used anywhere.
        if self.get_object().newest and self.get_object().oldest:
            context["feedback_duration"] = (
                self.get_object().newest - self.get_object().oldest
            ).days

        if self.get_object().feedback_set.all().exists():
            most_recent_feedback = (
                self.get_object().feedback_set.all().order_by("-created")[0]
            )
            context["last_seen"] = max(
                1, (timezone.now() - most_recent_feedback.created).days
            )
            context["requested"] = True
        else:
            context["last_seen"] = "No requests"
            context["requested"] = False

        context["mrr_attribute"] = FilterableAttribute.objects.get_mrr_attribute(
            self.request.user.customer
        )
        context["plan_attribute"] = FilterableAttribute.objects.get_plan_attribute(
            self.request.user.customer
        )
        context[
            "company_display_attributes"
        ] = FilterableAttribute.objects.get_company_display_attributes(
            self.request.user.customer
        )
        context[
            "user_display_attributes"
        ] = FilterableAttribute.objects.get_user_display_attributes(
            self.request.user.customer
        )

        context["feature_feedback"] = (
            self.get_feedback_filter_form()
            .get_filtered_queryset(self.request)
            .filter(feature_request=self.get_object())
            .select_related("user", "user__company")
        )

        context["feedback_count_difference"] = (
            self.get_object().feedback_set.all().count()
            - context["feature_feedback"].count()
        )

        return context

    def get_filter_form_class(self):
        return FeatureListFilterForm

    def get_feedback_filter_form(self):
        if not self.feedback_filter_form_instance:
            feedback_filter_form_instance = FeedbackListFilterForm(
                self.request.GET, request=self.request
            )
            if feedback_filter_form_instance.is_valid():
                # We can't carry 'search' because search in the feature list
                # means searching the feature not the feedback.
                feedback_filter_form_instance.cleaned_data["search"] = ""
                self.feedback_filter_form_instance = feedback_filter_form_instance
        return self.feedback_filter_form_instance

    def get_queryset(self):
        OnboardingTask.objects.filter(
            customer=self.request.user.customer,
            task_type=OnboardingTask.TASK_VIEW_FEATURE_REQUEST_DETAILS,
        ).update(completed=True, updated=timezone.now())

        tracking.feature_request_feedback_details_viewed(self.request.user)
        qs = self.get_filter_form().get_filtered_queryset(self.request)
        qs = qs.with_counts(self.request.user.customer)
        qs = qs.annotate(
            oldest=Min("feedback__created"), newest=Max("feedback__created")
        )
        qs = qs.order_by("-created")
        return qs

    def get_success_url(self):
        return self.get_return_url()


@method_decorator(role_required(User.ROLE_OWNER_OR_ADMIN), name="dispatch")
class ThemeListView(ListView):
    model = Theme
    context_object_name = "themes"
    template_name = "theme_list.html"

    LIST_HEADERS = (
        ("Name", "title", {}),
        ("Feature Requests", "total_features", {"style": "text-align: center"}),
        ("Feedback", "total_feedback", {"style": "text-align: center"}),
    )

    def get_sort_headers(self):
        return SortHeaders(
            self.request,
            self.LIST_HEADERS,
            default_order_field=0,
            default_order_type="asc",
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["headers"] = self.get_sort_headers().headers()
        return context

    def get_queryset(self):
        order_by = self.get_sort_headers().get_order_by()

        return (
            Theme.objects.filter(customer=self.request.user.customer)
            .annotate(
                total_features=Count("featurerequest__id", distinct=True),
                total_feedback=Count("feedback__id", distinct=True),
            )
            .order_by(order_by)
        )


@method_decorator(role_required(User.ROLE_OWNER_OR_ADMIN), name="dispatch")
class ThemeCreateItemView(ReturnUrlMixin, SuccessMessageMixin, CreateView):
    model = Theme
    template_name = "theme_create.html"
    form_class = ThemeCreateForm

    def get_return_url(self):
        theme_list_url = reverse_lazy("theme-list")
        return self.request.GET.get("return", theme_list_url)

    def get_queryset(self):
        return Theme.objects.filter(customer=self.request.user.customer)

    def get_success_url(self):
        tracking.theme_created(self.request.user)
        return self.get_return_url()

    def get_success_message(self, cleaned_data):
        return f"Created tag '{truncatechars(cleaned_data['title'], 100)}'"


@method_decorator(role_required(User.ROLE_OWNER_OR_ADMIN), name="dispatch")
class ThemeUpdateItemView(ReturnUrlMixin, SuccessMessageMixin, UpdateView):
    model = Theme
    template_name = "theme_update.html"
    form_class = ThemeEditForm

    def get_return_url(self):
        theme_list_url = reverse_lazy("theme-list")
        return self.request.GET.get("return", theme_list_url)

    def get_queryset(self):
        return Theme.objects.filter(customer=self.request.user.customer)

    def get_success_url(self):
        return self.get_return_url()

    def get_success_message(self, cleaned_data):
        return f"Update tag '{truncatechars(cleaned_data['title'], 100)}'"


@method_decorator(role_required(User.ROLE_OWNER_OR_ADMIN), name="dispatch")
class ThemeDeleteItemView(DeleteView):
    model = Theme
    template_name = "theme_confirm_delete.html"
    success_url = reverse_lazy("theme-list")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["total_fr_links"] = FeatureRequest.objects.filter(
            themes=self.object
        ).count()
        # context['has_features'] = FeatureRequest.objects.filter(customer=self.request.user.customer).exists()
        context["total_feedback_links"] = Feedback.objects.filter(
            themes=self.object
        ).count()
        # context['has_feedback'] = Feedback.objects.filter(customer=self.request.user.customer).exists()
        return context

    def delete(self, request, *args, **kwargs):
        messages.success(
            self.request, f"Delete tag '{truncatechars(self.get_object().title, 100)}'"
        )
        return super(ThemeDeleteItemView, self).delete(request, *args, **kwargs)


@method_decorator(role_required(User.ROLE_OWNER_OR_ADMIN), name="dispatch")
class CustomerFeedbackImporterSettingsDeleteItemView(DeleteView):
    model = CustomerFeedbackImporterSettings
    context_object_name = "cfis"
    template_name = "cfis_confirm_delete.html"
    success_url = reverse_lazy("accounts-integration-settings-list")

    def delete(self, request, *args, **kwargs):
        messages.success(
            self.request,
            f"You've been disconnected from {self.get_object().importer.name}",
        )
        return super().delete(request, *args, **kwargs)


@method_decorator(role_required(User.ROLE_OWNER_OR_ADMIN), name="dispatch")
class FeedbackFromRuleEditItemView(ReturnUrlMixin, SuccessMessageMixin, UpdateView):
    model = FeedbackFromRule
    template_name = "feedback_from_rule_update.html"
    form_class = FeedbackFromRuleEditForm

    def get_return_url(self):
        settings_list_url = reverse_lazy("accounts-settings-list")
        return self.request.GET.get("return", settings_list_url)

    def get_queryset(self):
        return FeedbackFromRule.objects.filter(customer=self.request.user.customer)

    def get_success_url(self):
        return self.get_return_url()

    def get_success_message(self, cleaned_data):
        return "Feedback From rule updated"


@method_decorator(role_required(User.ROLE_OWNER_OR_ADMIN), name="dispatch")
class FeedbackTemplateEditItemView(ReturnUrlMixin, SuccessMessageMixin, UpdateView):
    model = FeedbackTemplate
    template_name = "feedback_template_update.html"
    form_class = FeedbackTemplateEditForm

    def get_return_url(self):
        settings_list_url = reverse_lazy("accounts-settings-list")
        return self.request.GET.get("return", settings_list_url)

    def get_queryset(self):
        return FeedbackTemplate.objects.filter(customer=self.request.user.customer)

    def get_success_url(self):
        return self.get_return_url()

    def get_success_message(self, cleaned_data):
        return "Feedback Template updated"


@method_decorator(role_required(User.ROLE_OWNER_OR_ADMIN), name="dispatch")
@method_decorator(
    ratelimit(
        group="close-the-loop-emails",
        key="user_or_ip",
        rate="10/h",
        method=["POST",],
        block=False,
    ),
    name="post",
)  # Actual blocking is done in the form with validation
class CloseLoopView(ReturnUrlMixin, SuccessMessageMixin, FormView):
    template_name = "close_loop.html"
    form_class = CloseLoopForm

    def get_initial(self):
        initial = super().get_initial()
        try:
            frns, created = FeatureRequestNotificationSettings.objects.get_or_create(
                customer=self.request.user.customer
            )
            if frns.reply_to:
                initial["reply_to"] = frns.reply_to
            if frns.bcc:
                initial["bcc"] = frns.bcc
            if frns.template:
                initial["body"] = frns.template
        except FeatureRequestNotificationSettings.DoesNotExist:
            pass
        return initial

    def form_valid(self, form):
        # This method is called when valid form data has been POSTed.
        # It should return an HttpResponse.
        self.total_emails_sent = form.send_feedback_emails()
        return super().form_valid(form)

    def get_return_url(self):
        fr_list_url = reverse_lazy("feature-request-list")
        return self.request.GET.get("return", fr_list_url)

    def get_success_url(self):
        return self.get_return_url()

    def get_success_message(self, cleaned_data):
        return f"Your {self.total_emails_sent} message{pluralize(self.total_emails_sent, ' is,s are')} on the way!"


@role_required(User.ROLE_OWNER_OR_ADMIN)
@ratelimit(
    group="close-the-loop-test-emails",
    key="user_or_ip",
    rate="10/h",
    method=["POST",],
    block=False,
)  # Actual blocking is done in the form with validation
def fr_send_test_email(request):
    data = dict()
    if request.method == "POST":
        form = FeatureRequestNotificationSendTestEmailForm(
            request.POST, request=request
        )
        if form.is_valid():
            form.send_test_email()
            data["form_is_valid"] = True
        else:
            data["form_is_valid"] = False
    else:
        form = FeatureRequestNotificationSendTestEmailForm(request=request)

    context = {"form": form}
    data["html_form"] = render_to_string(
        "feature_request_send_test_email.html", context, request=request,
    )
    return JsonResponse(data)
