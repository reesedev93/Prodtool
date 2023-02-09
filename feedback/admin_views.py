import csv
import datetime
import os
import tempfile
import uuid
from django.contrib import messages
from django.shortcuts import redirect, render, resolve_url
from django.utils.decorators import method_decorator
from django.views.generic import FormView
from accounts.decorators import user_is_superuser
from accounts.models import Customer
from appaccounts.models import AppUser, AppCompany
from common.utils import textify_html
from feedback.models import FeatureRequest, Feedback, Theme
from .admin_forms import UploadFeedbackForm
from .tasks import admin_csv_feedback_import

@method_decorator(user_is_superuser, name='dispatch')
class UploadFeedbackView(FormView):
    form_class = UploadFeedbackForm
    template_name = 'admin/upload_feedback.html'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.invalid_rows = list()
        self.total_imported = 0
        self.import_token = ""

    def get_success_url(self):
        return resolve_url('feedback-admin-upload-feedback')

    def form_valid(self, form):
        # HACK: override form_valid and return a reponse vs. redirect
        # so we can easily return the valid rows on the same page.
        self.upload_feedback(form)
        return self.render_to_response(self.get_context_data(form=UploadFeedbackForm()))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['invalid_rows'] = self.invalid_rows
        context['total_imported'] = self.total_imported
        context['import_token'] = self.import_token
        return context

    def upload_feedback(self, form):
        self.customer = Customer.objects.get(id=form.cleaned_data['customer'])
        csv_file = self.request.FILES['csv_file']
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            for chunk in csv_file.chunks():
                temp_file.write(chunk)
            temp_file.flush()

            # File ends up owned by root. Celery runs as nobody.
            # Need to grant permissions to Celery can read the file.
            os.chmod(temp_file.name, 0o755)

            admin_csv_feedback_import.delay(self.customer.id, temp_file.name, form.cleaned_data['import_type'])

        messages.success(self.request, "Uploading Feature Requests for %s in the background. You'll get an email with the results." % (self.customer.name))
        return redirect('feedback-admin-upload-feedback')
