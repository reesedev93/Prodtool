import hashlib
import hmac
import json
import logging
import secrets
import string
from base64 import b64encode
from datetime import datetime
from urllib.parse import urljoin

from django.conf import settings
from django.contrib import messages
from django.contrib.messages.views import SuccessMessageMixin
from django.http import Http404, HttpResponse, HttpResponseServerError
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import UpdateView

from accounts.decorators import role_required
from accounts.models import OnboardingTask, User
from feedback.models import CustomerFeedbackImporterSettings, FeedbackImporter
from prodtool.views import ReturnUrlMixin

from .api import Client
from .forms import HelpScoutSettingsUpdateForm

logger = logging.getLogger(__name__)


@role_required(User.ROLE_OWNER_OR_ADMIN)
def oauth_callback(request):
    client = Client(
        "", "", settings.HELPSCOUT_CLIENT_ID, settings.HELPSCOUT_CLIENT_SECRET, None
    )
    response = client.get_auth_token(request.GET.get("code"))
    if response.ok:
        helpscout_importer = FeedbackImporter.objects.get(name="Help Scout")
        cfis, created = CustomerFeedbackImporterSettings.objects.get_or_create(
            importer=helpscout_importer, customer=request.user.customer
        )
        cfis.api_key = response.json()["access_token"]
        cfis.refresh_token = response.json()["refresh_token"]

        response = client.get_resource_owner()
        cfis.account_id = response.json()["companyId"]
        cfis.save()

        OnboardingTask.objects.filter(
            customer=request.user.customer,
            task_type=OnboardingTask.TASK_CONNECT_HELP_DESK,
        ).update(completed=True, updated=timezone.now())

        webhook_url_base = reverse_lazy(
            "integrations-helpscout-receive-webhook", args=[cfis.webhook_secret]
        )
        webhook_url = urljoin(settings.HOST, str(webhook_url_base))
        response = client.create_webhook(
            webhook_url,
            ("convo.tags", "convo.note.created", "convo.created"),
            settings.HELPSCOUT_WEBHOOK_SIGNING_KEY,
            "Savio new feedback",
        )
        if not response.ok:
            messages.error(
                request,
                "We couldn't add the web hook we need to Help Scout. Please contact suport.",
            )

    if request.GET.get("state") == "onboarding":
        return_url = reverse_lazy("accounts-onboarding-customer-data")
        helpscout_settings_url = reverse_lazy("integrations-helpscout-update-settings")
        return redirect(f"{helpscout_settings_url}?return={return_url}")
    else:
        return_url = reverse_lazy("accounts-integration-settings-list")
        helpscout_settings_url = reverse_lazy("integrations-helpscout-update-settings")
        return redirect(f"{helpscout_settings_url}?return={return_url}")


@method_decorator(role_required(User.ROLE_OWNER_OR_ADMIN), name="dispatch")
class HelpScoutSettingsUpdateItemView(ReturnUrlMixin, SuccessMessageMixin, UpdateView):
    model = CustomerFeedbackImporterSettings
    form_class = HelpScoutSettingsUpdateForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["no_feedback_tag"] = self.get_object().feedback_tag_name == ""
        return context

    def get_template_names(self):
        if "onboarding" in self.get_return_url():
            templates = ["helpscout/helpscout_settings_update_onboarding.html"]
        else:
            templates = ["helpscout/helpscout_settings_update.html"]
        return templates

    def get_object(self, queryset=None):
        try:
            # Get the single item from the filtered queryset
            obj = self.get_queryset().get(
                customer=self.request.user.customer, importer__name="Help Scout"
            )
        except CustomerFeedbackImporterSettings.DoesNotExist:
            raise Http404("Help Scout integration doesn't appear to be setup.")
        return obj

    def get_return_url(self):
        return self.request.GET.get(
            "return", reverse_lazy("accounts-integration-settings-list")
        )

    def get_queryset(self):
        return CustomerFeedbackImporterSettings.objects.filter(
            customer=self.request.user.customer, importer__name="Help Scout"
        )

    def get_success_url(self):
        return self.get_return_url()

    def get_success_message(self, cleaned_data):
        return f"Help Scout feedback tag set to '{cleaned_data['feedback_tag_name']}'"


@role_required(User.ROLE_OWNER_OR_ADMIN)
def generate_random_helpscout_user(request):
    plan_choices = {
        "Plan A": 10.0,
        "Plan B": 50.0,
        "Plan C": 150.0,
        "Plan D": 500.0,
    }

    province_choices = (
        "BC",
        "AB",
        "ON",
    )

    def generate_random_string(count=10):
        return "".join((secrets.choice(string.ascii_letters) for i in range(count)))

    def generate_random_plan():
        return secrets.choice(list(plan_choices.keys()))

    if not request.user.is_superuser and settings.PRODUCTION:
        raise HttpResponse(status=401)

    first_name = generate_random_string(10)
    last_name = generate_random_string(10)
    plan_name = generate_random_plan()
    monthly_spend = plan_choices[plan_name]
    company_name = generate_random_string(10)
    context = {
        "name": f"{first_name} {last_name}",
        "email": f"{first_name}.{last_name}@example.com",
        "user_id": f"{first_name}_{last_name}",
        "user_mrr": monthly_spend,
        "doctor_province": secrets.choice(province_choices),
        "company_id": company_name,
        "company_name": f"{company_name} Corp",
        "created_at": datetime.now().timestamp(),
        "plan_name": plan_name,
        "company_mrr": monthly_spend,
        "is_lighthouse": secrets.choice(("true", "false")),
        "upgraded_at": datetime.now().timestamp(),
    }

    return render(request, "helpscout/helpscout_random_data.html", context)


@csrf_exempt
def receive_webhook(request, secret):
    if request.method == "POST":
        if not verify_signature(request):
            return HttpResponse(status=401)

        try:
            json_data = json.loads(request.body)
        except json.JSONDecodeError:
            HttpResponseServerError("Malformed data!")

        logger.info(json_data)
        event = request.META.get("HTTP_X_HELPSCOUT_EVENT")
        logger.info(f"Event: {event}")

        try:
            cfis = CustomerFeedbackImporterSettings.objects.get(webhook_secret=secret)
            cfis.handle_webhook(json_data, event=event)
        except CustomerFeedbackImporterSettings.DoesNotExist:
            # If we are getting web hooks for secrets we don't have ignore them
            # Per: https://developer.helpscout.com/webhooks/
            # We might want to rerturn a 410 here to deactivate the web hook
            logger.info(f"Ignoring Help Scout web hook for secret {secret}.")
    return HttpResponse(status=204)


# Not a view
def verify_signature(request):
    signature = str(request.META.get("HTTP_X_HELPSCOUT_SIGNATURE"))
    calculated = hmac.new(
        settings.HELPSCOUT_WEBHOOK_SIGNING_KEY.encode("ascii"),
        request.body,
        hashlib.sha1,
    ).digest()
    return b64encode(calculated) != signature
