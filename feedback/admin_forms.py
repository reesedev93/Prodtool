# -*- coding: utf-8 -*-
from django import forms
from accounts.models import Customer

def get_customer_choices():
    return [(c.id, c.name) for c in Customer.objects.all().order_by('name')]

class UploadFeedbackForm(forms.Form):
    IMPORT_TYPE_ALL = "IMPORT_TYPE_ALL"
    IMPORT_TYPE_FEEDBACK = "IMPORT_TYPE_FEEDBACK"
    IMPORT_TYPE_FEATURE_REQUESTS = "IMPORT_TYPE_FEATURE_REQUESTS"

    IMPORT_TYPE_CHOICES = (
        (IMPORT_TYPE_ALL, "All"),
        (IMPORT_TYPE_FEEDBACK, "Just Feedback"),
        (IMPORT_TYPE_FEATURE_REQUESTS, "Just Feature Requests"),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['customer'].choices = [("","")] + get_customer_choices()

    customer = forms.ChoiceField(
        widget=forms.Select(attrs={'style': 'width: 465px;', 'class': 'right-select'}))
    import_type = forms.ChoiceField(
        choices=IMPORT_TYPE_CHOICES,
        widget=forms.Select(attrs={'style': 'width: 465px;', 'class': 'right-select'}))
    csv_file  = forms.FileField()
    # delete_existing = forms.BooleanField(initial=True, required=False, help_text="Delete existing restaurant infos for this customer")
