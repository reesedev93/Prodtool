import hashlib
import hmac
import json
import logging
import secrets
import string
from datetime import datetime

import requests
from django.conf import settings
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
from feedback.tasks import import_feedback
from prodtool.views import ReturnUrlMixin

from .forms import IntercomSettingsUpdateForm
from .importers import get_workspace_id

logger = logging.getLogger(__name__)


@role_required(User.ROLE_OWNER_OR_ADMIN)
def intercom_oauth_callback(request):
    auth_url = "https://api.intercom.io/auth/eagle/token"
    data = {
        "code": request.GET.get("code"),
        "client_id": settings.INTERCOM_CLIENT_ID,
        "client_secret": settings.INTERCOM_CLIENT_SECRET,
    }
    response = requests.post(auth_url, data)
    if response.ok:
        intercom_importer = FeedbackImporter.objects.get(name="Intercom")
        (
            customer_importer_settings,
            created,
        ) = CustomerFeedbackImporterSettings.objects.get_or_create(
            importer=intercom_importer, customer=request.user.customer
        )
        customer_importer_settings.api_key = response.json()["token"]
        customer_importer_settings.account_id = get_workspace_id(
            customer_importer_settings.api_key
        )
        customer_importer_settings.save()
        import_feedback.delay(customer_importer_settings.pk, request.user.pk)
        OnboardingTask.objects.filter(
            customer=request.user.customer,
            task_type=OnboardingTask.TASK_CONNECT_HELP_DESK,
        ).update(completed=True, updated=timezone.now())

    if request.GET.get("state") == "onboarding":
        return_url = reverse_lazy("accounts-onboarding-customer-data")
        intercom_settings_url = reverse_lazy("integrations-intercom-update-settings")
        return redirect(f"{intercom_settings_url}?return={return_url}")
    else:
        return_url = reverse_lazy("accounts-integration-settings-list")
        intercom_settings_url = reverse_lazy("integrations-intercom-update-settings")
        return redirect(f"{intercom_settings_url}?return={return_url}")


@method_decorator(role_required(User.ROLE_OWNER_OR_ADMIN), name="dispatch")
class IntercomSettingsUpdateItemView(ReturnUrlMixin, SuccessMessageMixin, UpdateView):
    model = CustomerFeedbackImporterSettings
    form_class = IntercomSettingsUpdateForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["no_feedback_tag"] = self.get_object().feedback_tag_name == ""
        return context

    def get_template_names(self):
        if "onboarding" in self.get_return_url():
            templates = ["intercom/intercom_settings_update_onboarding.html"]
        else:
            templates = ["intercom/intercom_settings_update.html"]
        return templates

    def get_object(self, queryset=None):
        try:
            # Get the single item from the filtered queryset
            obj = self.get_queryset().get(
                customer=self.request.user.customer, importer__name="Intercom"
            )
        except CustomerFeedbackImporterSettings.DoesNotExist:
            raise Http404("Intercom integration doesn't appear to be setup.")
        return obj

    def get_return_url(self):
        return self.request.GET.get(
            "return", reverse_lazy("accounts-integration-settings-list")
        )

    def get_queryset(self):
        return CustomerFeedbackImporterSettings.objects.filter(
            customer=self.request.user.customer, importer__name="Intercom"
        )

    def get_success_url(self):
        return self.get_return_url()

    def get_success_message(self, cleaned_data):
        return f"Intercom feedback tag set to '{cleaned_data['feedback_tag_name']}'"


@csrf_exempt
def receive_intercom_webhook(request):
    if request.method == "POST":
        verify_signature_or_raise(request)
        logger.info("Intercom webhook: signature verified")

        try:
            json_data = json.loads(request.body)
            logger.info(f"Intercom webhook: json data: {json_data}")
        except json.JSONDecodeError:
            logger.info("Intercom webhook: JSONDecodeError")
            HttpResponseServerError("Malformed data!")

        # The same Intercom workspace might be used in multiple Savio accounts.
        account_id = json_data["app_id"]
        logger.info(f"Intercom webhook: app_id {account_id}")
        feedback_importers_for_workspace = CustomerFeedbackImporterSettings.objects.filter(
            account_id=account_id
        )
        for cfis in feedback_importers_for_workspace:
            cfis.handle_webhook(json_data)
    return HttpResponse(status=204)


# Not a view
def verify_signature_or_raise(request):
    KEY = settings.INTERCOM_CLIENT_SECRET
    DATA = request.body
    EXPECTED = str(request.META.get("HTTP_X_HUB_SIGNATURE"))
    calculated = hmac.new(KEY.encode("ascii"), DATA, hashlib.sha1).hexdigest()
    calculated = "sha1=" + (calculated)
    if calculated != EXPECTED:
        raise HttpResponse(status=401)


@role_required(User.ROLE_OWNER_OR_ADMIN)
def generate_random_intercom_user(request):
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

    return render(request, "intercom_random_data.html", context)
