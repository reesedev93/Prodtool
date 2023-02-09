from dal import autocomplete
from django import forms
from django.contrib.staticfiles.templatetags.staticfiles import static

from .models import AppCompany, AppUser, FilterableAttribute


class AppUserAjaxCreateForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request")
        super().__init__(*args, **kwargs)

    def clean_email(self):
        existing_qs = AppUser.objects.filter(
            customer=self.request.user.customer, email=self.cleaned_data["email"]
        ).exclude(email__isnull=True)
        if existing_qs.exists():
            raise forms.ValidationError("User with that email already exists")
        return self.cleaned_data["email"]

    def save(self, commit=True):
        app_user = super(AppUserAjaxCreateForm, self).save(commit=False)
        if commit:
            app_user.customer = self.request.user.customer
            app_user.save()
        return app_user

    class Meta:
        model = AppUser
        fields = ["name", "email", "company"]
        widgets = {
            "company": autocomplete.ModelSelect2(
                url="app-company-autocomplete",
                attrs={
                    "tabindex": "3",
                    "allowClear": True,
                    "data-placeholder": "Select company...",
                    "delay": 250,
                    "minimumInputLength": 1,
                    "data-html": "true",
                },
            ),
        }


class AppUserEditForm(AppUserAjaxCreateForm):
    def clean_email(self):
        existing_qs = (
            AppUser.objects.filter(
                customer=self.request.user.customer, email=self.cleaned_data["email"]
            )
            .exclude(email__isnull=True)
            .exclude(id=self.instance.id)
        )
        if existing_qs.exists():
            raise forms.ValidationError("User with that email already exists")
        return self.cleaned_data["email"]


class AppCompanyEditForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request")
        super().__init__(*args, **kwargs)

    # TODO: deal with filterable attributes. Not like this though.
    # we probably need to do something smarter like what we do in
    # filter forms.
    # NB: monthly_spend and plan hanging directly off the model
    # aren't really used so the below is flat wrong. Also if we
    # let people change these various attributes we have collision
    # issues with what's in external systems. Maybe that's ok and
    # we want these to get overidden with what comes from the other
    # source system but maybe not and we don't have a good answer
    # for that.
    # def save(self, commit=True):
    #     app_company = super().save(commit=False)
    #     if commit:
    #         filterable_attributes = dict()
    #         filterable_attributes["monthly_spend"] = self.cleaned_data["monthly_spend"]
    #         filterable_attributes["plan"] = self.cleaned_data["plan"]
    #         app_company.filterable_attributes = filterable_attributes
    #         app_company.save()
    #     return app_company

    class Meta:
        model = AppCompany
        fields = [
            "name",
        ]


class FilterableAttributeEditForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def save(self, commit=True):
        fa = super().save(commit=False)

        # We only want one field set is_mrr or is_plan so if the user
        # sets those fields unset the existing if there is one.
        existing_is_plan = FilterableAttribute.objects.filter(
            customer=fa.customer, is_plan=True
        ).exclude(pk=fa.pk)
        if self.cleaned_data["is_plan"] and existing_is_plan.exists():
            existing_is_plan.update(is_plan=False)

        existing_is_mrr = FilterableAttribute.objects.filter(
            customer=fa.customer, is_mrr=True
        ).exclude(pk=fa.pk)
        if self.cleaned_data["is_mrr"] and existing_is_mrr.exists():
            existing_is_mrr.update(is_mrr=False)

        if commit:
            fa.save()
            fa.refresh_cache()
        return fa

    class Meta:
        model = FilterableAttribute
        fields = [
            "friendly_name",
            "show_in_filters",
            "show_in_badge",
            "is_mrr",
            "is_plan",
        ]

        user_info_help_image = static("images/displayed-customer-attributes.png")

        widgets = {"friendly_name": forms.TextInput(attrs={"autofocus": True,})}

        labels = {
            "is_plan": 'This attribute stores the customer\'s plan <i class="text-muted far fa-question-circle"  data-toggle="tooltip" data-original-title="When checked, Savio will use this attribute\'s value when it needs to display a customer\'s Plan"></i>',
            "is_mrr": 'This attribute stores the customer\'s MRR <i data-toggle="tooltip" data-original-title="When checked, Savio will use this attribute when it needs to display a customer\'s MRR" class="text-muted far fa-question-circle"></i>',
            "friendly_name": "Display name",
            "show_in_filters": 'Show in filters <i class="text-muted far fa-question-circle"  data-toggle="tooltip" data-original-title="Use this attribute to filter feedback and feature requests"></i>',
            "show_in_badge": f"""Show with User Info <i class="text-muted far fa-question-circle tooltip-large" data-html="true" data-position="right" data-original-title="Display this attribute wherever your customers' details are shown.<br><br><img width='400' src='{user_info_help_image}'>"></i>""",
        }
