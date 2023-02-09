from django import forms
from django.conf import settings
from django.contrib import messages
from django.utils.html import mark_safe
from feedback.models import CustomerFeedbackImporterSettings
from .api import Client, ApiException

class HelpScoutSettingsUpdateForm(forms.ModelForm):
    feedback_tag_name = forms.ChoiceField(
        widget=forms.Select(attrs={
            'autofocus': True,
            'class': 'form-control',
            'data-placeholder': 'Select Help Scout tag',
        })
    )

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request')
        self.cfis = CustomerFeedbackImporterSettings.objects.get(importer__name="Help Scout", customer=self.request.user.customer)
        self.client = Client(self.cfis.api_key, self.cfis.refresh_token, settings.HELPSCOUT_CLIENT_ID, settings.HELPSCOUT_CLIENT_SECRET, self.cfis.save_refreshed_tokens)
        super().__init__(*args, **kwargs)
        self.fields['feedback_tag_name'].choices = self.get_tag_choices()
        self.fields['feedback_tag_name'].help_text = f"To create a new tag, <a target='_blank' href='https://secure.helpscout.net/settings/tags/mailboxes//dateRange//start//end//sort/name/page/1'>first create it in Help Scout</a> by applying the new tag to a conversation, then <a href=''>refresh this page</a>."
        for visible in self.visible_fields():
            visible.field.widget.attrs['class'] = 'form-control'

    def get_tag_choices(self):
        try:
            return [("","") ] + [(tag['name'], tag['name']) for tag in self.client.get_tags()]
        except ApiException as e:
            messages.error(self.request, mark_safe(f"Failed to connect to Help Scout. Please disconnect and reconnect or <a href='mailto:support@savio.io'>contact support</a>.<br> Error details: {e}. "))
            return []

    class Meta:
        model = CustomerFeedbackImporterSettings
        fields = ['feedback_tag_name',]
