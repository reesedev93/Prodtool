from django.contrib.messages.views import SuccessMessageMixin
from django.db.models import Q
from django.http import JsonResponse
from django.template.loader import render_to_string
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.views.generic import ListView, UpdateView

from accounts.decorators import role_required
from accounts.models import User
from prodtool.views import ReturnUrlMixin
from sharedwidgets.widgets import SavioAutocomplete

from .forms import (
    AppCompanyEditForm,
    AppUserAjaxCreateForm,
    AppUserEditForm,
    FilterableAttributeEditForm,
)
from .models import AppCompany, AppUser, FilterableAttribute


@method_decorator(role_required(User.ROLE_OWNER_OR_ADMIN), name="dispatch")
class AppUserAutocompleteNoCreate(SavioAutocomplete):
    def get_result_label(self, item):
        return item.get_dropdown_display()

    def get_queryset(self):
        # Don't forget to filter out results depending on the visitor !
        if not self.request.user.is_authenticated:
            return AppUser.objects.none()

        qs = AppUser.objects.filter(customer=self.request.user.customer)

        if self.q:
            qs = qs.filter(Q(name__icontains=self.q) | Q(email__icontains=self.q))
        return qs.order_by("name", "email")


# Hitting this endpoint lets you create companies
@method_decorator(role_required(User.ROLE_OWNER_OR_ADMIN), name="dispatch")
class AppCompanyAutocomplete(SavioAutocomplete):
    def get_create_result_label(self, new_value):
        return f"<strong>New Company: {new_value}</strong>"

    def has_add_permission(self, request):
        return request.user.is_authenticated

    def create_object(self, text):
        """Create an object given a text."""
        company, created = self.get_queryset().get_or_create(
            **{"customer": self.request.user.customer, self.create_field: text,}
        )

        return company

    def get_queryset(self):
        # Don't forget to filter out results depending on the visitor !
        if not self.request.user.is_authenticated:
            return AppCompany.objects.none()

        qs = AppCompany.objects.filter(customer=self.request.user.customer)

        if self.q:
            qs = qs.filter(name__icontains=self.q)
        return qs.order_by("name")


# Hitting the endpoint that calls this view does NOT let you create companies.
# This is because has_add_permission needs to be true in SavioAutocomplete.get_create_option for
# a user to be able to create a company.  In this case we set it to false so we have an endpoint to
# call with Select2 that won't let you create companies (like in feedback and FR filtering)
@method_decorator(role_required(User.ROLE_OWNER_OR_ADMIN), name="dispatch")
class AppCompanyAutocompleteNoCreate(AppCompanyAutocomplete):
    def has_add_permission(self, request):
        return False


@role_required(User.ROLE_OWNER_OR_ADMIN)
def app_user_ajax_create(request):
    data = dict()

    if request.method == "POST":
        form = AppUserAjaxCreateForm(request.POST, request=request)
        if form.is_valid():
            form.save()
            data["form_is_valid"] = True
            data["id"] = form.instance.id
            data["text"] = form.instance.get_dropdown_display()
        else:
            data["form_is_valid"] = False
    else:
        form = AppUserAjaxCreateForm(request=request)

    context = {"form": form}
    data["html_form"] = render_to_string(
        "app_user_ajax_create.html", context, request=request,
    )
    return JsonResponse(data)


@method_decorator(role_required(User.ROLE_OWNER_OR_ADMIN), name="dispatch")
class AppUserUpdateItemView(ReturnUrlMixin, SuccessMessageMixin, UpdateView):
    model = AppUser
    template_name = "app_user_update.html"
    form_class = AppUserEditForm

    def get_return_url(self):
        fr_list_view = None  # reverse_lazy('feature-request-list')
        return self.request.GET.get("return", fr_list_view)

    def get_success_url(self):
        return self.get_return_url()

    def get_success_message(self, cleaned_data):
        return f"Saved {self.object.get_name_or_email()}"


@method_decorator(role_required(User.ROLE_OWNER_OR_ADMIN), name="dispatch")
class AppCompanyUpdateItemView(ReturnUrlMixin, SuccessMessageMixin, UpdateView):
    model = AppCompany
    template_name = "app_company_update.html"
    form_class = AppCompanyEditForm

    def get_return_url(self):
        fr_list_view = None  # reverse_lazy('feature-request-list')
        return self.request.GET.get("return", fr_list_view)

    def get_success_url(self):
        return self.get_return_url()

    def get_success_message(self, cleaned_data):
        return f"Saved {self.object.name}"


@method_decorator(role_required(User.ROLE_OWNER_OR_ADMIN), name="dispatch")
class FilterableAttributeListView(ListView):
    model = FilterableAttribute
    context_object_name = "filterable_attributes"
    template_name = "filterable_attribute_list.html"

    def get_queryset(self):
        return FilterableAttribute.objects.filter(
            customer=self.request.user.customer
        ).order_by("related_object_type", "friendly_name")


@method_decorator(role_required(User.ROLE_OWNER_OR_ADMIN), name="dispatch")
class FilterableAttributeUpdateItemView(SuccessMessageMixin, UpdateView):
    model = FilterableAttribute
    context_object_name = "filterable_attribute"
    template_name = "filterable_attribute_update.html"
    form_class = FilterableAttributeEditForm

    def get_return_url(self):
        fa_list_url = reverse_lazy("filterable-attributes-list")
        return self.request.GET.get("return", fa_list_url)

    def get_queryset(self):
        return FilterableAttribute.objects.filter(customer=self.request.user.customer)

    def get_success_url(self):
        return self.get_return_url()

    def get_success_message(self, cleaned_data):
        return f"Updated attribute '{cleaned_data['friendly_name']}'"
