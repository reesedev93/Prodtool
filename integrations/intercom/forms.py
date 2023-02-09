from django import forms
from django.contrib import messages
from django.urls import reverse
from django.utils.html import mark_safe
from intercom.client import Client
from intercom.errors import TokenUnauthorizedError, TokenNotFoundError
from feedback.models import CustomerFeedbackImporterSettings

class IntercomSettingsUpdateForm(forms.ModelForm):
    feedback_tag_name = forms.ChoiceField()

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request')
        self.cfis = CustomerFeedbackImporterSettings.objects.get(importer__name="Intercom", customer=self.request.user.customer)
        self.client = Client(personal_access_token=self.cfis.api_key)

        super().__init__(*args, **kwargs)
        self.fields['feedback_tag_name'].choices = self.get_tag_choices()
        self.fields['feedback_tag_name'].help_text = f"To create a new tag, <a target='_blank' href='https://app.intercom.io/a/apps/{self.cfis.account_id}/settings/tags/'>first create it in Intercom</a>, then <a href=''>refresh this page</a>."
        for visible in self.visible_fields():
            visible.field.widget.attrs['class'] = 'form-control'

    def get_tag_choices(self):
        try:
            tag_choices = [(None, 'Choose a tag')] + [(tag.name, tag.name) for tag in self.client.tags.all()]
        except (TokenUnauthorizedError, TokenNotFoundError):
            tag_choices = []
            intercom_disconnect_url = reverse('customer-feedback-importer-settings-delete-item', args=[self.cfis.pk,])
            messages.add_message(
                self.request,
                messages.ERROR,
                mark_safe(f"Your Intercom token is invalid. Please <a href='{intercom_disconnect_url}'>disconnect</a> from intercom and reconnect."))
        return tag_choices

    class Meta:
        model = CustomerFeedbackImporterSettings
        fields = ['feedback_tag_name',]

        widgets = {
            'feedback_tag_name': forms.Select(
                attrs={
                    'autofocus': True,
                    'class': 'form-control',
                }
            )
        }
