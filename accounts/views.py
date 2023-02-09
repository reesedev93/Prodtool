from datetime import datetime
from urllib import parse

import stripe
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.views import LoginView
from django.contrib.messages.views import SuccessMessageMixin
from django.core.mail import send_mail
from django.http import HttpResponse
from django.shortcuts import redirect, render, resolve_url
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.utils.html import mark_safe
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import CreateView, DeleteView, ListView, UpdateView
from rest_framework.authtoken.models import Token

from feedback.models import (
    CustomerFeedbackImporterSettings,
    FeedbackFromRule,
    FeedbackImporter,
    FeedbackTemplate,
)
from integrations.models import SlackSettings

from .decorators import role_required
from .forms import (
    ChromeExtensionJoinForm,
    FeatureRequestNotificationSettingsForm,
    FeedbackTriageSettingsForm,
    JoinForm,
    MyAuthenticationForm,
    StatusEmailSettingsForm,
    SubmittersCanCreateFeaturesSettingsForm,
    SubscriptionEditForm,
    UserCreateForm,
    UserUpdateForm,
    InvitationCreateForm,
    WhitelistForm,
    WhitelistSettingsForm,
)
from .models import (
    Customer,
    Discount,
    FeatureRequestNotificationSettings,
    FeedbackTriageSettings,
    OnboardingTask,
    StatusEmailSettings,
    Subscription,
    User,
    Invitation
)
from .tasks import send_signup_survey_email


class MyLoginView(LoginView):
    form_class = MyAuthenticationForm

    def get_success_url(self):
        url = self.get_redirect_url()
        return url or resolve_url("feedback-inbox-list", state="active")


class ChromeLoginView(LoginView):
    form_class = MyAuthenticationForm

    template_name = "registration/chrome_extension_login.html"

    def get_success_url(self):
        url = self.get_redirect_url()
        return url or resolve_url("accounts-chrome-extension-login-successful")


@role_required(User.ROLE_ANY)
def chrome_extension_login_successful(request):
    return render(request, "registration/chrome_extension_login_successful.html")


def join(request):
    code = None
    promo_text = None
    if request.method == "POST":
        form = JoinForm(request.POST)
        if form.is_valid():
            form.save()
            email = form.cleaned_data.get("email")
            raw_password = form.cleaned_data.get("password1")
            user = authenticate(username=email, password=raw_password)
            login(request, user)

            customer = user.customer
            customer.first_referer = request.COOKIES.get("first_referer", "None")
            customer.first_landing_page = request.COOKIES.get(
                "first_landing_page", "None"
            )
            customer.last_referer = request.COOKIES.get("last_referer", "None")
            customer.last_landing_page = request.COOKIES.get(
                "last_landing_page", "None"
            )
            customer.save()

            marketing_info = f"first_referer: {customer.first_referer}\r\nfirst_landing_page: {customer.first_landing_page}\r\nlast_referer: {customer.last_referer}\r\nlast_landing_page: {customer.last_landing_page}"

            # Get discount object if a code was passed in
            code = form.cleaned_data.get("code")
            if code:
                try:
                    discount = Discount.objects.get(
                        code=code, subscription_id__isnull=True
                    )
                except Discount.DoesNotExist:
                    discount = None

            # Set stripe_id depending on plan
            if discount:
                plan = "appsumo"
                stripe_plan = discount.plan
            else:
                plan = form.cleaned_data.get("plan")
                if plan == "smb":
                    stripe_plan = Subscription.PLAN_3_USERS_25
                elif plan == "growth":
                    stripe_plan = Subscription.PLAN_UNLIMITED_USERS_49
                else:
                    stripe_plan = Subscription.PLAN_1_USER_FREE

            quoted_email = parse.quote(f'"{user.email}"', safe="")
            fs_url = f"https://app.fullstory.com/ui/J3A37/segments/everyone/people:search:((NOW%2FDAY-29DAY:NOW%2FDAY%2B1DAY):((UserEmail:==:{quoted_email})):():():():)/0"
            li_string = f"{user.first_name} {user.last_name} {user.customer.name}"
            quoated_li_string = parse.quote(li_string, safe="")
            li_url = f"https://www.linkedin.com/search/results/all/?keywords={quoated_li_string}"

            Subscription.objects.create_stripe_subscription(user, stripe_plan)

            # Set discount's subscription_id to mark discount code as used
            if discount:
                discount.subscription_id = customer.subscription.id
                discount.save()

            # Send ourselves an email whenever a new user signs up.
            li_url = (
                "https://www.linkedin.com/search/results/all/?keywords="
                + parse.quote(li_string, safe="")
            )

            send_mail(
                f"[Savio] New Sign-up: {user.email} @ {user.customer.name} ({plan})",
                f"Full name:\r\n {user.first_name} {user.last_name}\r\n\r\nFullStory:\r\n{fs_url}\r\n\r\n LinkedIn: \r\n{li_url}\r\n\r\nMarketing Info:\r\n{marketing_info}\r\n\r\nOnboarding Percent:\r\nhttps://www.savio.io/admin/accounts/customer/\r\n\r\nNothing more to say lads.  Onward.",
                "help@savio.io",
                ["k@savio.io", "ryan@savio.io"],
            )

            OnboardingTask.objects.create_initial_tasks(user.customer)

            send_signup_survey_email.apply_async(args=[user.id,], countdown=60 * 5)

            qs = "?onboarding=yes&signup=true"
            if discount:
                qs = qs + "&appsumo=yes"

            return redirect(reverse("accounts-onboarding-checklist") + qs)
    else:
        code = request.GET.get("code", None)
        try:
            discount = Discount.objects.get(code=code, subscription_id__isnull=True)
        except Discount.DoesNotExist:
            discount = None

        if discount:
            promo_text = discount.promo_text

        form = JoinForm()
    return render(
        request, "join.html", {"form": form, "code": code, "promo_text": promo_text},
    )


def sign_up(request, id):
    if request.method == "POST":
        form = JoinForm(request.POST)
        if form.is_valid():
            form.save()
            email = form.cleaned_data.get("email")
            raw_password = form.cleaned_data.get("password1")
            user = authenticate(username=email, password=raw_password)
            login(request, user)

            customer = user.customer
            customer.first_referer = request.COOKIES.get("first_referer", "None")
            customer.first_landing_page = request.COOKIES.get(
                "first_landing_page", "None"
            )
            customer.last_referer = request.COOKIES.get("last_referer", "None")
            customer.last_landing_page = request.COOKIES.get(
                "last_landing_page", "None"
            )
            customer.save()

            marketing_info = f"first_referer: {customer.first_referer}\r\nfirst_landing_page: {customer.first_landing_page}\r\nlast_referer: {customer.last_referer}\r\nlast_landing_page: {customer.last_landing_page}"

            
            plan = form.cleaned_data.get("plan")
            if plan == "smb":
                stripe_plan = Subscription.PLAN_3_USERS_25
            elif plan == "growth":
                stripe_plan = Subscription.PLAN_UNLIMITED_USERS_49
            else:
                stripe_plan = Subscription.PLAN_1_USER_FREE

            quoted_email = parse.quote(f'"{user.email}"', safe="")
            fs_url = f"https://app.fullstory.com/ui/J3A37/segments/everyone/people:search:((NOW%2FDAY-29DAY:NOW%2FDAY%2B1DAY):((UserEmail:==:{quoted_email})):():():():)/0"
            li_string = f"{user.first_name} {user.last_name} {user.customer.name}"
            quoated_li_string = parse.quote(li_string, safe="")
            li_url = f"https://www.linkedin.com/search/results/all/?keywords={quoated_li_string}"

            Subscription.objects.create_stripe_subscription(user, stripe_plan)

            # Send ourselves an email whenever a new user signs up.
            li_url = (
                "https://www.linkedin.com/search/results/all/?keywords="
                + parse.quote(li_string, safe="")
            )

            send_mail(
                f"[Savio] New Sign-up: {user.email} @ {user.customer.name} ({plan})",
                f"Full name:\r\n {user.first_name} {user.last_name}\r\n\r\nFullStory:\r\n{fs_url}\r\n\r\n LinkedIn: \r\n{li_url}\r\n\r\nMarketing Info:\r\n{marketing_info}\r\n\r\nOnboarding Percent:\r\nhttps://www.savio.io/admin/accounts/customer/\r\n\r\nNothing more to say lads.  Onward.",
                "help@savio.io",
                ["k@savio.io", "ryan@savio.io"],
            )

            OnboardingTask.objects.create_initial_tasks(user.customer)

            send_signup_survey_email.apply_async(args=[user.id,], countdown=60 * 5)

            return redirect(reverse("login"))
        else:
            invitation = Invitation.objects.get(pk=id)
    else:
        invitation = Invitation.objects.get(pk=id)
        form = JoinForm(initial={'email': invitation.email})
    return render(
        request, "sign_up.html", {"form": form, "email": invitation.email},
    )

@method_decorator(role_required(User.ROLE_OWNER), name="dispatch")
class SubscriptionUpdateItemView(SuccessMessageMixin, UpdateView):
    model = Subscription
    template_name = "subscription_update.html"
    form_class = SubscriptionEditForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        if hasattr(self, "request"):
            kwargs.update({"request": self.request})
        return kwargs

    def get_object(self):
        return self.get_queryset().get(customer=self.request.user.customer)

    def get_return_url(self):
        return_url = reverse_lazy("accounts-settings-list")
        return self.request.GET.get("return", return_url)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["return"] = self.get_return_url()
        context["inactive_subscription"] = (
            self.request.user.customer.has_subscription()
            and self.request.user.customer.subscription.inactive()
        )
        context["STRIPE_PUBLISHABLE_KEY"] = settings.STRIPE_PUBLISHABLE_KEY
        context["feedback_count"] = self.request.user.customer.total_feedback_count()

        context["show_add_card"] = self.request.GET.get("add_card", None) == "1"

        context[
            "is_usage_tiered"
        ] = self.request.user.customer.subscription.is_usage_tiered()

        context[
            "is_plan_per_seat"
        ] = self.request.user.customer.subscription.is_plan_per_seat()

        context[
            "is_feature_tiered"
        ] = self.request.user.customer.subscription.is_feature_tiered()

        context["number_users"] = self.request.user.customer.num_users()

        context["plan"] = self.request.user.customer.subscription.get_plan_display()

        context["card_on_file"] = (
            self.request.user.customer.has_subscription()
            and self.request.user.customer.subscription.card_on_file
        )
        if self.request.user.customer.subscription.is_usage_tiered():
            context[
                "newest_feedback_created_one_hour_ago"
            ] = self.request.user.customer.newest_feedback_created_one_hour_ago()
            context["over_free_feedback_limit_and_needs_to_pay"] = (
                self.request.user.customer.has_subscription()
                and self.request.user.customer.subscription.over_free_feedback_limit_and_needs_to_pay()
            )
            context["under_free_feedback_limit"] = (
                self.request.user.customer.has_subscription()
                and self.request.user.customer.subscription.under_free_feedback_limit()
            )
            context["next_plan_price"] = self.request.user.customer.next_plan_price()
            context[
                "next_plan_feedback_count"
            ] = self.request.user.customer.next_plan_feedback_count()
            context[
                "current_plan_price"
            ] = self.request.user.customer.current_plan_price()
            context[
                "current_plan_feedback_count"
            ] = self.request.user.customer.current_plan_feedback_count()

        return context

    def get_queryset(self):
        return Subscription.objects.filter(customer=self.request.user.customer)

    def get_success_url(self):
        return self.get_return_url()

    def get_success_message(self, cleaned_data):
        return "Your changes were successful.  Thank you!"


@role_required(User.ROLE_ANY)
def no_payment_source_on_file(request):
    owner = User.objects.filter(
        customer=request.user.customer, role=User.ROLE_OWNER
    ).first()
    return render(request, "no_payment_source_on_file.html", {"owner": owner})


def activate_account(request, uid, token):
    try:
        token_valid = False
        user = User.objects.get(pk=uid)
        if default_token_generator.check_token(user, token):
            token_valid = True
            user.is_active = True
            user.save()
            login(request, user)
            send_mail(
                f"[Savio] New CE User: {user.email} @ {user.customer.name}",
                "",
                "help@savio.io",
                ["k@savio.io"],
            )

    except User.DoesNotExist:
        pass
    return render(
        request,
        "chrome_extension_activate_account.html",
        {"token_valid": token_valid, "user": user,},
    )


def chrome_extension_join(request):
    if request.method == "POST":
        form = ChromeExtensionJoinForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("accounts-chrome-extension-join-successful")
        else:
            if form.has_error("email", "not_whitelisted"):
                return redirect("accounts-chrome-extension-email-not-whitelisted")
    else:
        form = ChromeExtensionJoinForm()
    return render(request, "chrome_extension_join.html", {"form": form})


def chrome_extension_join_successful(request):
    return render(request, "chrome_extension_join_successful.html")


def chrome_extension_email_not_whitelisted(request):
    return render(request, "chrome_extension_email_not_whitelisted.html")


@role_required(User.ROLE_OWNER_OR_ADMIN)
def onboarding_tour(request):
    return render(request, "onboarding_tour.html")


@role_required(User.ROLE_ANY)
def onboarding_chrome_extension(request):
    return render(request, "onboarding_chrome_extension.html")


@role_required(User.ROLE_OWNER_OR_ADMIN)
def onboarding_whitelist(request):
    if request.method == "POST":
        form = WhitelistForm(request.POST, instance=request.user.customer)
        if form.is_valid():
            if form.cleaned_data["whitelist_domain"]:
                form.save()
            return redirect("accounts-onboarding-done")
    else:
        form = WhitelistForm(
            instance=request.user.customer,
            initial={"whitelisted_domain": request.user.get_email_domain()},
        )

    return render(request, "onboarding_whitelist.html", {"form": form})


@role_required(User.ROLE_OWNER_OR_ADMIN)
def onboarding_customer_data(request):
    intercom_connected = CustomerFeedbackImporterSettings.objects.filter(
        importer__name="Intercom", customer=request.user.customer
    ).exists()

    helpscout_connected = CustomerFeedbackImporterSettings.objects.filter(
        importer__name="Help Scout", customer=request.user.customer
    ).exists()

    segment_importer = FeedbackImporter.objects.get(name="Segment")
    segment_cfis, created = CustomerFeedbackImporterSettings.objects.get_or_create(
        importer=segment_importer, customer=request.user.customer,
    )

    return render(
        request,
        "onboarding_customer_data.html",
        context={
            "intercom_client_id": settings.INTERCOM_CLIENT_ID,
            "helpscout_client_id": settings.HELPSCOUT_CLIENT_ID,
            "intercom_connected": intercom_connected,
            "helpscout_connected": helpscout_connected,
            "segment_cfis": segment_cfis,
        },
    )


@role_required(User.ROLE_OWNER_OR_ADMIN)
def onboarding_done(request):
    return render(request, "onboarding_done.html")


@role_required(User.ROLE_OWNER_OR_ADMIN)
def onboarding_checklist(request):
    return render(
        request,
        "onboarding-checklist.html",
        context={
            "first_name": request.user.first_name,
            "company_name": request.user.customer.name,
            "appsumo": request.GET.get("appsumo", None),
            "tasks": OnboardingTask.objects.filter(
                customer=request.user.customer
            ).order_by("created"),
        },
    )


@role_required(User.ROLE_OWNER_OR_ADMIN)
def invite_teammates(request):
    return render(request, "invite_teammates.html")


@role_required(User.ROLE_OWNER_OR_ADMIN)
def my_settings_list(request):
    status_email_settings, created = StatusEmailSettings.objects.get_or_create(
        customer=request.user.customer, user=request.user,
    )

    user_api_token = Token.objects.get(user=request.user).key

    context = {
        "status_email_settings": status_email_settings,
        "user_api_token": user_api_token,
    }
    return render(request, "my_settings_list.html", context)


@role_required(User.ROLE_OWNER_OR_ADMIN)
def integration_settings_list(request):
    try:
        intercom_cfis = CustomerFeedbackImporterSettings.objects.get(
            importer__name="Intercom", customer=request.user.customer
        )
        intercom_enabled = True
    except CustomerFeedbackImporterSettings.DoesNotExist:
        intercom_cfis = None
        intercom_enabled = False

    try:
        helpscout_cfis = CustomerFeedbackImporterSettings.objects.get(
            importer__name="Help Scout", customer=request.user.customer
        )
        helpscout_enabled = True
    except CustomerFeedbackImporterSettings.DoesNotExist:
        helpscout_cfis = None
        helpscout_enabled = False

    if SlackSettings.objects.has_slack_settings(request.user.customer):
        slack_enabled = True
    else:
        slack_enabled = False

    segment_importer = FeedbackImporter.objects.get(name="Segment")
    segment_cfis, created = CustomerFeedbackImporterSettings.objects.get_or_create(
        importer=segment_importer, customer=request.user.customer,
    )

    context = {
        "client_id": settings.INTERCOM_CLIENT_ID,
        "helpscout_client_id": settings.HELPSCOUT_CLIENT_ID,
        "intercom_enabled": intercom_enabled,
        "intercom_cfis": intercom_cfis,
        "helpscout_enabled": helpscout_enabled,
        "helpscout_cfis": helpscout_cfis,
        "segment_cfis": segment_cfis,
        "slack_enabled": slack_enabled,
        "slack_client_id": settings.SLACK_CLIENT_ID,
        "host": settings.HOST,
        "onboarding": request.GET.get("onboarding", "no") == "yes",
    }
    return render(request, "integration_settings_list.html", context)


@role_required(User.ROLE_OWNER_OR_ADMIN)
def settings_list(request):
    try:
        subscription = Subscription.objects.get(customer=request.user.customer)
    except Subscription.DoesNotExist:
        subscription = None

    feedback_from_rule, created = FeedbackFromRule.objects.get_or_create(
        customer=request.user.customer,
    )

    feedback_template, created = FeedbackTemplate.objects.get_or_create(
        customer=request.user.customer,
    )

    (
        fr_notification_settings,
        created,
    ) = FeatureRequestNotificationSettings.objects.get_or_create(
        customer=request.user.customer
    )

    feedback_triage_settings, created = FeedbackTriageSettings.objects.get_or_create(
        customer=request.user.customer
    )

    context = {
        "whitelisting_enabled": request.user.customer.whitelisted_domain is not None,
        "submitters_can_create_features": request.user.customer.submitters_can_create_features,
        "subscription": subscription,
        "feedback_from_rule": feedback_from_rule,
        "feedback_template": feedback_template,
        "fr_notification_settings": fr_notification_settings,
        "feedback_triage_settings": feedback_triage_settings,
    }
    return render(request, "settings_list.html", context)


@method_decorator(role_required(User.ROLE_OWNER_OR_ADMIN), name="dispatch")
class StatusEmailSettingsUpdateItemView(SuccessMessageMixin, UpdateView):
    model = StatusEmailSettings
    template_name = "my_settings_update_status_email.html"
    form_class = StatusEmailSettingsForm

    def get_return_url(self):
        return reverse_lazy("accounts-my-settings-list")

    def get_queryset(self):
        return StatusEmailSettings.objects.filter(
            customer=self.request.user.customer, user=self.request.user
        )

    def get_success_url(self):
        return self.get_return_url()

    def get_success_message(self, cleaned_data):
        return mark_safe(
            f"Feedback digest email delivery changed to: <strong>{self.get_object().get_notify_display()}</strong>."
        )


def status_email_unsubscribe(request, unsubscribe_token):
    try:
        ses = StatusEmailSettings.objects.get(unsubscribe_token=unsubscribe_token)
        ses.notify = StatusEmailSettings.NOTIFY_NEVER
        ses.save()
    except StatusEmailSettings.DoesNotExist:
        pass
    return render(request, "unsubscribe.html", {})


@method_decorator(role_required(User.ROLE_OWNER_OR_ADMIN), name="dispatch")
class FeatureRequestNotificationSettingsUpdateItemView(SuccessMessageMixin, UpdateView):
    model = FeatureRequestNotificationSettings
    template_name = "feature_request_notification_settings.html"
    form_class = FeatureRequestNotificationSettingsForm

    def get_return_url(self):
        return reverse_lazy("accounts-settings-list")

    def get_queryset(self):
        return FeatureRequestNotificationSettings.objects.filter(
            customer=self.request.user.customer
        )

    def get_success_url(self):
        return self.get_return_url()

    def get_success_message(self, cleaned_data):
        return mark_safe("Feature Request notification settings updated.")


@method_decorator(role_required(User.ROLE_OWNER_OR_ADMIN), name="dispatch")
class FeedbackTriageSettingsUpdateItemView(SuccessMessageMixin, UpdateView):
    model = FeedbackTriageSettings
    template_name = "feedback_triage_settings.html"
    form_class = FeedbackTriageSettingsForm

    def get_object(self):
        return self.get_queryset().get(customer=self.request.user.customer)

    def get_return_url(self):
        return reverse_lazy("accounts-settings-list")

    def get_queryset(self):
        return FeedbackTriageSettings.objects.filter(
            customer=self.request.user.customer
        )

    def get_success_url(self):
        return self.get_return_url()

    def get_success_message(self, cleaned_data):
        return mark_safe("Automatically triage feedback settings updated.")


@method_decorator(role_required(User.ROLE_OWNER_OR_ADMIN), name="dispatch")
class WhitelistedDomainSettingsUpdateItemView(SuccessMessageMixin, UpdateView):
    model = Customer
    template_name = "settings_update_whitelisted_domain.html"
    form_class = WhitelistSettingsForm

    def get_return_url(self):
        return reverse_lazy("accounts-settings-list")

    def get_object(self):
        return Customer.objects.get(pk=self.request.user.customer.pk)

    # def get_initial(self):
    #     initial = self.initial.copy()
    #     initial['whitelisted_domain'] = self.request.user.get_email_domain()
    #     return initial

    def get_success_url(self):
        return self.get_return_url()

    def get_success_message(self, cleaned_data):
        if cleaned_data["whitelisted_domain"]:
            return f"Users will be able to automatically join from their verified {cleaned_data['whitelisted_domain']} email address."
        else:
            return "Automatically joining via a whitelisted domain is disabled."


@method_decorator(role_required(User.ROLE_OWNER_OR_ADMIN), name="dispatch")
class SubmittersCanCreateFeaturesSettingsUpdateItemView(
    SuccessMessageMixin, UpdateView
):
    model = Customer
    template_name = "settings_update_submitters_can_create_features.html"
    form_class = SubmittersCanCreateFeaturesSettingsForm

    def get_return_url(self):
        return reverse_lazy("accounts-settings-list")

    def get_object(self):
        return Customer.objects.get(pk=self.request.user.customer.pk)

    # def get_initial(self):
    #     initial = self.initial.copy()
    #     initial['whitelisted_domain'] = self.request.user.get_email_domain()
    #     return initial

    def get_success_url(self):
        return self.get_return_url()

    def get_success_message(self, cleaned_data):
        if cleaned_data["submitters_can_create_features"]:
            return "Submitters will be able to create new Feature Requests when submitting Feedback using the Chrome Extension."
        else:
            return "Submitters will NOT be able to create new Feature Requests when submitting Feedback using the Chrome Extension (but can choose existing ones)."


@method_decorator(role_required(User.ROLE_OWNER_OR_ADMIN), name="dispatch")
class UserListView(ListView):
    model = User
    context_object_name = "users"
    template_name = "user_list.html"

    def get_queryset(self):
        return User.objects.filter(customer=self.request.user.customer)


@method_decorator(role_required(User.ROLE_OWNER_OR_ADMIN), name="dispatch")
class InvitationListView(ListView):
    model = Invitation
    context_object_name = "invites"
    template_name = "user_list.html"

    def get_queryset(self):
        return Invitation.objects.filter(customer=self.request.user.customer)


@method_decorator(role_required((User.ROLE_OWNER_OR_ADMIN)), name="dispatch")
class UserCreateItemView(SuccessMessageMixin, CreateView):
    model = User
    template_name = "user_create.html"
    form_class = UserCreateForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        if hasattr(self, "request"):
            kwargs.update({"request": self.request})
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        if self.request.user.customer.has_subscription():
            context[
                "is_plan_per_seat"
            ] = self.request.user.customer.subscription.is_plan_per_seat()
        else:
            context["is_plan_per_seat"] = False
        return context

    def get_queryset(self):
        return User.objects.filter(customer=self.request.user.customer)

    def get_success_url(self):
        if (
            self.request.user.customer.has_subscription()
            and self.request.user.customer.subscription.is_plan_per_seat()
        ):
            self.request.user.customer.subscription.sync_stripe_subscription_quantity()

        return reverse_lazy("accounts-user-list")

    def get_success_message(self, cleaned_data):
        s = (
            f"Created person '{cleaned_data['first_name']} {cleaned_data['last_name']}'. <a href='"
            + reverse("accounts-invite-teammates")
            + f"'>Let {cleaned_data['first_name']} know they've been added here →</a>"
        )
        return mark_safe(s)


@method_decorator(role_required((User.ROLE_OWNER_OR_ADMIN)), name="dispatch")
class InviteCreateItemView(SuccessMessageMixin, CreateView):
    model = Invitation
    template_name = "invite_create.html"
    form_class = InvitationCreateForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        if hasattr(self, "request"):
            kwargs.update({"request": self.request})
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        if self.request.user.customer.has_subscription():
            context[
                "is_plan_per_seat"
            ] = self.request.user.customer.subscription.is_plan_per_seat()
        else:
            context["is_plan_per_seat"] = False
        return context

    def get_queryset(self):
        return Invite.objects.filter(customer=self.request.user.customer)

    def get_success_url(self):
        if (
            self.request.user.customer.has_subscription()
            and self.request.user.customer.subscription.is_plan_per_seat()
        ):
            self.request.user.customer.subscription.sync_stripe_subscription_quantity()

        return reverse_lazy("accounts-invitation-list")

    def get_success_message(self, cleaned_data):
        s = "Invitation has been sent"
        return mark_safe(s)


@method_decorator(role_required(User.ROLE_OWNER_OR_ADMIN), name="dispatch")
class UserUpdateItemView(SuccessMessageMixin, UpdateView):
    model = User
    template_name = "user_update.html"
    form_class = UserUpdateForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        if hasattr(self, "request"):
            kwargs.update({"request": self.request})
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        if self.request.user.customer.has_subscription():
            context[
                "is_plan_per_seat"
            ] = self.request.user.customer.subscription.is_plan_per_seat()
        else:
            context["is_per_seat_plan"] = False
        return context

    def get_return_url(self):
        user_list_url = reverse_lazy("accounts-user-list")
        return self.request.GET.get("return", user_list_url)

    def get_queryset(self):
        return User.objects.filter(customer=self.request.user.customer)

    def get_success_url(self):
        if (
            self.request.user.customer.has_subscription()
            and self.request.user.customer.subscription.is_plan_per_seat()
        ):
            self.request.user.customer.subscription.sync_stripe_subscription_quantity()

        return self.get_return_url()

    def get_success_message(self, cleaned_data):
        return (
            f"Updated user '{cleaned_data['first_name']} {cleaned_data['last_name']}'"
        )


@method_decorator(role_required(User.ROLE_OWNER_OR_ADMIN), name="dispatch")
class UserDeleteItemView(DeleteView):
    model = User
    template_name = "user_confirm_delete.html"
    success_url = reverse_lazy("accounts-user-list")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        return context

    def delete(self, request, *args, **kwargs):
        deleting_owner = self.get_object().role == User.ROLE_OWNER
        only_one_owner = (
            User.objects.filter(
                customer=self.request.user.customer, role=User.ROLE_OWNER
            ).count()
            == 1
        )
        if deleting_owner and only_one_owner:
            messages.error(
                self.request,
                f"Could not delete user '{self.get_object().get_full_name()}'. You must have at least one owner.",
            )
            self.object = self.get_object()
            success_url = self.get_success_url()
            return redirect(success_url)
        else:
            messages.success(
                self.request, f"Delete user '{self.get_object().get_full_name()}'"
            )

            response = super().delete(request, *args, **kwargs)
            if (
                self.request.user.customer.has_subscription()
                and self.request.user.customer.subscription.is_plan_per_seat()
            ):
                self.request.user.customer.subscription.sync_stripe_subscription_quantity()
            return response


@csrf_exempt
def stripe_webhook(request):
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")
    event = None
    try:
        stripe.api_key = settings.STRIPE_API_KEY
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_ENDPOINT_SECRET
        )

        # NB: Since the canceling can lead to a different Sub getting created
        # later we prefer to look up OUR sub by Stripe customer id.
        if event["type"] in (
            "customer.subscription.created",
            "customer.subscription.updated",
        ):
            # We normally make the sub when they join but if you cancel the sub
            # in Stripe's UI and then make it again this will get triggered and we'll
            # fix up our sub with the new data.
            stripe_customer_id = event["data"]["object"]["customer"]

            # We should already have one of our subs. In theory this is a noop
            # in the normal join case. 1) Create Our and Stripe sub during join
            # then 2) this webhook fires and we just redo what we already did.
            # But in the cancel and then recreate case we'll fix things up.
            our_sub = Subscription.objects.get(stripe_customer_id=stripe_customer_id)

            # Let's just grab the real data directly from Stripe vs. using the
            # webhook so we can be sure it's fresh.
            stripe_customer = stripe.Customer.retrieve(stripe_customer_id)
            stripe_sub = stripe_customer["subscriptions"].data[0]
            our_sub.status = stripe_sub.status
            if stripe_sub.trial_end:
                our_sub.trial_end_date = datetime.utcfromtimestamp(stripe_sub.trial_end)
            our_sub.stripe_subscription_id = stripe_sub.id
            our_sub.save()
        elif event["type"] == "customer.subscription.deleted":
            # Stripe canceled this sub. In this case we are going to look up our sub by
            # Stripe sub id to avoid any potential race conditions gotchas where
            # we might cancel the wrong sub if it was cancel then create and things
            # arrived out of order.
            stripe_customer_id = event["data"]["object"]["customer"]
            stripe_subscription_id = event["data"]["object"]["id"]
            try:
                our_sub = Subscription.objects.get(
                    stripe_customer_id=stripe_customer_id,
                    stripe_subscription_id=stripe_subscription_id,
                )
                our_sub.status = Subscription.STATUS_CANCELED
                our_sub.save()
            except Subscription.DoesNotExist:
                # If we've already deleted the customer and their sub we don't care.
                pass
        elif event["type"].startswith("customer.source"):
            # Keep track over whether or not they have a payment method on file.
            # Normally we set this when they add the card but this allows us to
            # do the right thing if we add or remove a payment method manually.
            stripe_customer_id = event["data"]["object"]["customer"]
            stripe_customer = stripe.Customer.retrieve(stripe_customer_id)
            our_sub = Subscription.objects.get(stripe_customer_id=stripe_customer_id)
            if stripe_customer["sources"]["data"]:
                our_sub.card_on_file = True
            else:
                our_sub.card_on_file = False
            our_sub.save()
    except Subscription.DoesNotExist:
        raise Exception(f"No sub for customer {stripe_customer_id}")
    except ValueError:
        return HttpResponse(status=400)
    except stripe.error.SignatureVerificationError:
        return HttpResponse(status=400)
    return HttpResponse(status=200)
